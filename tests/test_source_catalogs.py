"""Discovery leads are versioned, bounded and separate from source verification."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import tempfile
import unittest

import httpx
from mrbench.catalog import catalog, read_json, write_json
from mrbench.coverage import source_coverage
from mrbench.source_catalogs import normalize_rows
from mrbench.source_registry import check_updates, load_registry, index_fingerprint

FIELDS = {"id": "id", "title": "title", "url": "source_url", "publisher": "reporter"}
ROW = {
    "id": "MSI-1",
    "title": "Example",
    "source_url": "https://original.test/report",
    "reporter": "OpenAI",
    "annotation": "lead only",
}


class DiscoveryCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "registry.json"
        self.config = {
            "id": "leads",
            "name": "Example catalog",
            "index_url": "https://catalog.test/",
            "snapshot": "catalog.json",
            "adapter": "jsonl",
            "revision_url": "https://catalog.test/api/revision",
            "data_url": "https://catalog.test/raw/{revision}/data.jsonl",
            "fields": FIELDS,
        }
        self.snapshot = {
            "schema_version": 1,
            "id": "leads",
            "reviewed_at": "2026-11-03",
            "upstream_revision": "a" * 40,
            "license": "CC BY 4.0",
            "scope": "Discovery only",
            "entries": normalize_rows(json.dumps(ROW), FIELDS),
        }
        self.snapshot["entries"][0]["decision"] = {
            "status": "deferred",
            "reason": "Task context is not disclosed.",
            "case_ids": [],
        }
        self.provider = {
            "id": "publisher",
            "name": "Publisher",
            "index_url": "https://publisher.test/",
            "snapshot": "publisher.json",
            "discovery": {"adapter": "reviewed"},
        }
        self.sources = {
            "schema_version": 1,
            "index_url": "https://publisher.test/",
            "observed_at": "2026-11-03",
            "scope": "Reviewed URLs only",
            "sources": [],
            "snapshot_counts": {},
        }
        self.save()

    def save(self):
        write_json(
            self.path,
            {
                "schema_version": 2,
                "providers": [self.provider],
                "catalogs": [self.config],
            },
        )
        write_json(self.root / "catalog.json", self.snapshot)
        write_json(self.root / "publisher.json", self.sources)

    def check(self, rows=None):
        visited = []

        def handler(request):
            visited.append(str(request.url))
            if request.url.path == "/api/revision":
                return httpx.Response(200, json={"sha": "b" * 40})
            return httpx.Response(
                200,
                text="\n".join(
                    json.dumps(x) for x in ([ROW] if rows is None else rows)
                ),
            )

        result = check_updates(
            self.path,
            selected="leads",
            content=True,
            transport=httpx.MockTransport(handler),
        )
        self.assertTrue(all("original.test" not in url for url in visited))
        self.assertIn("/raw/" + "b" * 40 + "/", visited[1])
        return result["catalogs"][0]

    def test_pinned_catalog_is_not_an_executable_source_denominator(self):
        self.assertEqual(self.check()["status"], "clean")
        result = source_coverage({}, self.path)
        self.assertEqual(result["source_count"], 0)
        self.assertEqual(result["catalogs"][0]["decisions"], {"deferred": 1})
        self.assertEqual(result["catalogs"][0]["entry_count"], 1)

    def test_new_changed_and_missing_records_are_distinct(self):
        result = self.check(
            [{**ROW, "id": "MSI-2"}, {**ROW, "annotation": "revised claim"}]
        )
        self.assertEqual(result["new"][0]["id"], "MSI-2")
        self.assertEqual(result["changed"][0]["id"], "MSI-1")
        self.assertEqual(
            self.check([{**ROW, "id": "MSI-2"}])["not_listed"][0]["id"], "MSI-1"
        )

    def test_empty_duplicate_and_malformed_catalogs_are_errors(self):
        for rows in ([], [ROW, ROW], [{"id": "missing-url"}]):
            with self.subTest(rows=rows):
                self.assertEqual(self.check(rows)["status"], "error")
        with self.assertRaises(ValueError):
            normalize_rows(
                "\n".join(json.dumps({**ROW, "id": str(n)}) for n in range(501)), FIELDS
            )

    def test_redirect_size_and_revision_errors_never_follow_primary_urls(self):
        for response in (
            httpx.Response(200, json={"sha": "main"}),
            httpx.Response(302, headers={"location": "https://outside.test/"}),
            httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1)),
        ):
            visited = []

            def fetch(request):
                visited.append(request.url.host)
                return response

            result = check_updates(
                self.path, selected="leads", transport=httpx.MockTransport(fetch)
            )
            self.assertEqual(result["status"], "partial")
            self.assertEqual(set(visited), {"catalog.test"})

    def test_snapshots_require_decisions_attribution_scope_and_real_case_references(
        self,
    ):
        mutations = [
            lambda s: s["entries"][0].update(decision=None),
            lambda s: s["entries"][0].update(
                decision={"status": "included", "reason": "Missing case"}
            ),
            lambda s: s.update(upstream_revision="main"),
            lambda s: s.update(license=""),
            lambda s: s.update(entries=[]),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                old = deepcopy(self.snapshot)
                mutation(self.snapshot)
                self.save()
                with self.assertRaises(ValueError):
                    load_registry(self.path)
                self.snapshot = old

    def test_pdf_byte_checks_and_reviewed_urls_do_not_claim_index_discovery(self):
        payload = b"%PDF-1.7\nfictional bounded fixture"
        entry = {
            "id": "card",
            "kind": "system-card",
            "title": "Card",
            "url": "https://publisher.test/card",
            "updated": "2026-11-03",
            "evidence_status": "reported_behavior",
            "components": {"Selected task": ["example"]},
            "content_format": "pdf",
            "content_hash": sha256(payload).hexdigest(),
        }
        entry["index_fingerprint"] = index_fingerprint(entry)
        self.sources.update(sources=[entry], snapshot_counts={"system-cards": 1})
        self.save()

        def fetch(request):
            self.assertEqual(request.url.path, "/card")
            return httpx.Response(200, content=payload)

        result = check_updates(
            self.path,
            selected="publisher",
            content=True,
            transport=httpx.MockTransport(fetch),
        )["providers"][0]
        self.assertEqual(result["status"], "clean")
        self.assertIn("Previously reviewed", result["discovery_scope"])
        result = check_updates(
            self.path,
            selected="publisher",
            content=True,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, text="<main>Not a PDF</main>")
            ),
        )["providers"][0]
        self.assertEqual(result["status"], "partial")

    def test_builtin_decisions_preserve_overlap_weak_evidence_and_ai_review(self):
        result = source_coverage(catalog())
        lead = result["catalogs"][0]
        self.assertEqual(lead["entry_count"], 130)
        self.assertEqual(
            lead["decisions"], {"covered": 30, "deferred": 68, "included": 32}
        )
        entries = {r["id"]: r for r in lead["entries"]}
        self.assertEqual(entries["MSI-0068"]["parent_incident_id"], "MSI-0021")
        self.assertEqual(entries["MSI-0076"]["decision"]["status"], "deferred")
        self.assertIn(
            "audit-source-integrity", entries["MSI-0076"]["decision"]["case_ids"]
        )
        self.assertEqual(entries["MSI-0009"]["decision"]["status"], "deferred")
        self.assertTrue(all(r["upstream_review_status"] for r in entries.values()))
        self.assertEqual(result["source_count"], 55)
