"""Source registration is offline; opt-in discovery only produces review data."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from mrbench.catalog import Case, catalog, read_json, write_json
from mrbench.coverage import source_coverage, validate_coverage
from mrbench.source_registry import (
    SOURCE_INDEX,
    article_fingerprint,
    check_updates,
    index_fingerprint,
    load_registry,
    parse_index,
)


def index_page(*entries):
    return (
        "<main>"
        + "".join(
            f'<article class="entry"><h2><a href="/{slug}">{title}</a></h2><time datetime="2026-10-18">Oct 18</time></article>'
            for slug, title in entries
        )
        + "</main>"
    )


RULE = {
    "selector": ".entry",
    "url_selector": "h2 a",
    "title_selector": "h2 a",
    "date_selector": "time",
    "kind": "report",
}
ARTICLE = (
    "<main><h1>Fictional investigation</h1><p>Original public observation.</p></main>"
)
INDEX = index_page(("a", "First report"))


class SourceRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "registry.json"
        entry = parse_index(INDEX, "https://third.test/reports", [RULE])[0]
        self.source = dict(
            entry,
            id="first",
            evidence_status="observed_activity",
            components={"Ordinary research": ["citation-upload"]},
            index_fingerprint=index_fingerprint(entry),
            content_hash=article_fingerprint(ARTICLE, "main"),
        )
        self.snapshot = {
            "schema_version": 1,
            "index_url": "https://third.test/reports",
            "observed_at": "2026-10-18",
            "scope": "Authored source adapter fixture.",
            "snapshot_counts": {"reports": 1},
            "sources": [self.source],
        }
        self.provider = {
            "id": "third",
            "name": "Another publisher",
            "index_url": self.snapshot["index_url"],
            "snapshot": "sources/third.json",
            "discovery": {
                "adapter": "html",
                "article_selector": "main",
                "entries": [RULE],
            },
        }
        self.save()

    def save(self):
        write_json(self.path, {"schema_version": 2, "providers": [self.provider]})
        write_json(self.root / "sources/third.json", self.snapshot)

    def check(self, index=INDEX, article=ARTICLE, content=False):
        def fetch(request):
            return httpx.Response(
                200, text=index if request.url.path == "/reports" else article
            )

        return check_updates(
            self.path, content=content, transport=httpx.MockTransport(fetch)
        )

    def test_third_website_uses_json_selectors_without_python_registration(self):
        result = self.check(content=True)
        self.assertEqual(result["status"], "clean")
        self.assertEqual(result["providers"][0]["id"], "third")
        self.assertEqual(result["providers"][0]["entries"][0]["known_id"], "first")

    def test_builtin_namespaced_inventory_and_original_snapshot_are_preserved(self):
        result = validate_coverage(catalog())
        self.assertEqual(result["provider_count"], 4)
        self.assertEqual(result["source_count"], 62)
        openai = next(
            provider for provider in result["providers"] if provider["id"] == "openai"
        )
        self.assertEqual(openai["snapshot_counts"], {"reports": 26, "notices": 3, "system-cards": 6})
        self.assertEqual(openai["case_count"], 53)
        legacy = load_registry(SOURCE_INDEX.parent / "sources/openai.json")
        self.assertEqual(len(legacy["sources"]), 35)
        self.assertTrue(
            all(source["provider_id"] == "legacy" for source in legacy["sources"])
        )

    def test_openai_index_migration_matches_legacy_ids_and_reads_past_the_preview(self):
        from mrbench.openai_index import CURRENT_PREFIX, LEGACY_PREFIX

        def row(title, url, group, first, last):
            return {
                "title": title, "href": url, "filters": {"type": [group]},
                "reportDates": {"firstPosted": first, "lastUpdated": last},
            }

        old = "2026-10-15"
        updated = "2026-10-18"
        self.provider.update(
            index_url=CURRENT_PREFIX,
            discovery={"adapter": "openai-reports", "allowed_hosts": ["alignment.openai.com"]},
        )
        self.snapshot["index_url"] = CURRENT_PREFIX
        self.source.update(
            url=LEGACY_PREFIX + "first/",
            updated=updated,
            date_basis="report_updated",
        )
        self.source["index_fingerprint"] = index_fingerprint(self.source)
        self.save()
        rows = [
            row("First report", CURRENT_PREFIX + "first/", "reports", old, updated),
            row("Second report", CURRENT_PREFIX + "second/", "reports", old, updated),
            row("First notice", "https://openai.com/notices/#first", "notices", old, updated),
            row("Second notice", "https://openai.com/notices/#second", "notices", old, updated),
        ]

        def index(rows):
            payload = "1:" + json.dumps({"items": rows})
            sections = '<main><a href="#reports">Reports 2</a><a href="#notices">Notices 2</a>'
            preview = f'<section><a href="{CURRENT_PREFIX}first/">First report</a></section>'
            # The first render omits three entries; JSON stream records may span scripts.
            return sections + preview + "</main>" + "".join(
                f"<script>self.__next_f.push({json.dumps([1, part])})</script>"
                for part in (payload[:100], payload[100:])
            )

        html = index(rows)

        def fetch(request):
            self.assertEqual(request.url.host, "openai.com")
            if str(request.url) == CURRENT_PREFIX:
                return httpx.Response(200, text=html)
            return httpx.Response(200, text="<main>New article rendering.</main>")

        transport = httpx.MockTransport(fetch)
        report = check_updates(self.path, content=True, transport=transport)["providers"][0]
        self.assertEqual(report["not_listed"], [])
        self.assertEqual(report["errors"], [])
        self.assertEqual(
            [(entry["id"], entry["reasons"]) for entry in report["changed"]],
            [("first", ["article_fingerprint_changed_after_url_migration"])],
        )
        self.assertEqual(len(report["entries"]), 4)
        self.assertEqual(
            {entry["updated"] for entry in report["new"] if entry["kind"] == "notice"}, {old},
        )
        self.assertEqual(
            {entry["title"] for entry in report["new"]},
            {"Second report", "First notice", "Second notice"},
        )
        html = index(rows[:3])
        incomplete = check_updates(self.path, transport=transport)["providers"][0]
        self.assertEqual(incomplete["status"], "error")
        self.assertEqual(incomplete["entries"], [])
        self.assertIn("published section counts", incomplete["errors"][0]["message"])

    def test_transluce_redesigned_index_keeps_only_investigation_cards(self):
        registry = read_json(SOURCE_INDEX)
        config = next(item for item in registry["providers"] if item["id"] == "transluce")

        def card(topic, title, href):
            return f"""
            <article><img src="/thumbnail.jpg">
              <p class="text-meta"><span class="text-darkluce">{topic}</span>
                 <span class="whitespace-nowrap">Oct 18, 2026</span></p>
              <h3><a href="{href}">{title}</a></h3>
            </article>
            """

        html = "<main><section>" + "".join([
            card("Incident Investigations", "Report", "/report"),
            card("Incident Investigations", "Volunteer blog", "/investigations/blog/volunteer"),
            card("Announcements", "Unrelated", "/unrelated"),
        ]) + "</section></main>"
        found = parse_index(html, config["index_url"], config["discovery"]["entries"])
        self.assertEqual(
            {(row["title"], row["kind"], row["updated"]) for row in found},
            {("Report", "report", "2026-10-18"), ("Volunteer blog", "blog", "2026-10-18")},
        )

    def test_source_ids_are_local_to_website(self):
        registry = read_json(self.path)
        other = deepcopy(self.provider)
        other.update(id="fourth", snapshot="sources/fourth.json")
        registry["providers"].append(other)
        write_json(self.path, registry)
        write_json(self.root / "sources/fourth.json", self.snapshot)
        self.assertEqual(
            {entry["source_key"] for entry in load_registry(self.path)["sources"]},
            {"third/first", "fourth/first"},
        )

    def test_one_report_can_map_to_multiple_independent_tasks(self):
        selected = {}
        for cid in ("citation-upload", "photo-upload"):
            original = catalog()[cid]
            spec = deepcopy(original.spec)
            spec["source"].update(
                provider="third", id="first", url=self.source["url"],
                evidence_status="observed_activity",
            )
            selected[cid] = Case(original.path, spec, original.samples)
        self.source["components"] = {
            "Structured records research": ["citation-upload"],
            "Photograph research": ["photo-upload"],
        }
        self.save()
        with patch("httpx.Client", side_effect=AssertionError("Offline mapping must not fetch")):
            coverage = validate_coverage(selected, self.path)
        self.assertEqual(coverage["source_count"], 1)
        self.assertEqual(coverage["case_count"], 2)
        self.assertEqual(coverage["sources"][0]["case_ids"], sorted(selected))

    def test_offline_mapping_checks_primary_and_supporting_source_identity(self):
        original = catalog()["citation-upload"]
        spec = deepcopy(original.spec)
        spec["source"].update(
            provider="third",
            id="first",
            url=self.source["url"],
            evidence_status="observed_activity",
        )
        selected = {original.id: Case(original.path, spec, original.samples)}
        with patch(
            "httpx.Client",
            side_effect=AssertionError("Offline commands must not fetch"),
        ):
            self.assertTrue(validate_coverage(selected, self.path)["coverage_complete"])
        spec["source"]["provider"] = "wrong"
        with self.assertRaises(ValueError):
            source_coverage(selected, self.path)
        spec["source"]["supporting_sources"] = [
            {"provider": "third", "id": "first", "url": self.source["url"]}
        ]
        self.assertTrue(validate_coverage(selected, self.path)["coverage_complete"])
        self.snapshot["sources"][0]["related_sources"] = [
            {"source_key": "missing/source"}
        ]
        self.save()
        with self.assertRaises(ValueError):
            source_coverage(selected, self.path)

    def test_add_changed_missing_and_content_changes_do_not_mutate_inputs(self):
        before = {path: path.read_bytes() for path in self.root.rglob("*.json")}
        result = self.check(
            index=index_page(("a", "Revised title"), ("b", "New article")),
            article=ARTICLE.replace("Original", "Updated"),
            content=True,
        )["providers"][0]
        self.assertEqual(len(result["new"]), 1)
        self.assertEqual(
            result["changed"][0]["reasons"],
            ["index_metadata_changed", "article_content_changed"],
        )
        missing = self.check(index=index_page(("b", "New article")))["providers"][0][
            "not_listed"
        ]
        self.assertEqual(missing, [{"id": "first", "url": "https://third.test/a"}])
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)

    def test_missing_baselines_require_review(self):
        self.source.pop("index_fingerprint")
        self.source.pop("content_hash")
        self.save()
        result = self.check(content=True)["providers"][0]
        self.assertEqual(result["status"], "review")
        self.assertEqual(
            {entry["field"] for entry in result["untracked"]},
            {"index_fingerprint", "content_hash"},
        )

    def test_empty_changed_or_invalid_selectors_are_errors_not_mass_deletion(self):
        for rule in [
            RULE,
            dict(RULE, selector=":has("),
            dict(RULE, date_selector=".missing"),
        ]:
            self.provider["discovery"]["entries"] = [rule]
            self.save()
            result = self.check(index="<main></main>" if rule == RULE else INDEX)[
                "providers"
            ][0]
            self.assertEqual(result["status"], "error")
            self.assertTrue(result["errors"])
            self.assertEqual(result["not_listed"], [])

    def test_unreachable_article_retains_index_entry_and_marks_partial(self):
        def fetch(request):
            return (
                httpx.Response(200, text=INDEX)
                if request.url.path == "/reports"
                else httpx.Response(403)
            )

        result = check_updates(
            self.path, content=True, transport=httpx.MockTransport(fetch)
        )
        self.assertEqual(result["status"], "partial")
        provider = result["providers"][0]
        self.assertEqual(len(provider["entries"]), 1)
        self.assertEqual(provider["not_listed"], [])
        self.assertIn("403", provider["errors"][0]["detail"])

    def test_redirect_host_and_response_size_are_bounded(self):
        visited = []

        def redirect(request):
            visited.append(request.url.host)
            return httpx.Response(
                302, headers={"location": "https://unregistered.test/reports"}
            )

        result = check_updates(self.path, transport=httpx.MockTransport(redirect))
        self.assertEqual(visited, ["third.test"])
        self.assertEqual(result["providers"][0]["status"], "error")
        result = check_updates(
            self.path,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))
            ),
        )
        self.assertEqual(result["providers"][0]["status"], "error")

    def test_invalid_registry_paths_counts_and_evidence_status_are_rejected(self):
        mutations = [
            lambda: self.provider.update(snapshot="../outside.json"),
            lambda: self.snapshot.update(snapshot_counts={"reports": 2}),
            lambda: self.source.update(evidence_status="confirmed_hack"),
            lambda: self.snapshot.update(sources=[None]),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                original = deepcopy((self.provider, self.snapshot))
                mutate()
                self.save()
                with self.assertRaises(ValueError):
                    load_registry(self.path)
                self.provider, self.snapshot = original
                self.source = self.snapshot["sources"][0]
        target = self.root / "sources/third.json"
        self.save()
        target.rename(self.root / "saved.json")
        target.symlink_to(self.root / "saved.json")
        with self.assertRaises(ValueError):
            load_registry(self.path)

    def test_metadata_collisions_and_shared_notice_urls_are_explicit(self):
        self.snapshot["sources"].append(dict(self.source, id="second-id"))
        self.snapshot["snapshot_counts"] = {"reports": 2}
        self.save()
        with self.assertRaises(ValueError):
            load_registry(self.path)
        with self.assertRaises(ValueError):
            parse_index(
                index_page(("a", "One"), ("a", "Other")),
                self.provider["index_url"],
                [RULE],
            )
        result = parse_index(
            index_page(("a", "One"), ("a", "Other")),
            self.provider["index_url"],
            [dict(RULE, identity="url-title")],
        )
        self.assertEqual(len(result), 2)
        a = article_fingerprint(ARTICLE, "main")
        self.assertEqual(
            a,
            article_fingerprint(
                ARTICLE.replace("</main>", "<script>changed()</script></main>"), "main"
            ),
        )

    def test_cli_refuses_to_overwrite_prior_review_before_fetching(self):
        from mrbench.cli import dispatch, parser

        output = self.root / "review.json"
        output.write_text("existing evidence")
        args = parser().parse_args(
            ["sources", "check", "--sources", str(self.path), "--output", str(output)]
        )
        with patch("mrbench.source_registry.check_updates") as fetch:
            with self.assertRaises(ValueError):
                dispatch(args)
            fetch.assert_not_called()
        self.assertEqual(output.read_text(), "existing evidence")


if __name__ == "__main__":
    unittest.main()
