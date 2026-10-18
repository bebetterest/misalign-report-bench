"""Reviewed source snapshots and opt-in, read-only website update checks.

Normal benchmark commands read local JSON only. Discovery produces a review
report; it never edits snapshots, cases, tasks, scores or saved model runs.
"""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from .catalog import digest, identifier, read_json

SOURCE_INDEX = Path(__file__).with_name("source-coverage.json")
EVIDENCE_STATUSES = {
    "reported_behavior",
    "simulated_demonstration",
    "reported_non_misalignment",
    "unverified_allegation",
    "observed_activity",
}


def canonical_url(value):
    if not isinstance(value, str):
        raise ValueError("Source URLs must be strings")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Source URLs must be HTTPS without embedded credentials")
    return urlunsplit(
        ("https", parsed.hostname.lower(), parsed.path or "/", parsed.query, "")
    )


def load_registry(path=SOURCE_INDEX):
    """Read v2 provider files, or a historical v1 single-index snapshot."""
    path = Path(path).resolve()
    raw = read_json(path)
    if not isinstance(raw, dict):
        raise ValueError("A source registry must be a JSON object")
    if raw.get("schema_version") == 1:
        providers = [
            {
                "id": "legacy",
                "name": raw.get("publisher", "Legacy source index"),
                "index_url": raw["index_url"],
                "snapshot_data": raw,
            }
        ]
    elif raw.get("schema_version") == 2 and isinstance(raw.get("providers"), list):
        providers = deepcopy(raw["providers"])
    else:
        raise ValueError(
            "Source registry must use schema 2, or a legacy schema-1 snapshot"
        )
    seen, entries, result = set(), [], []
    for provider in providers:
        if not isinstance(provider, dict) or not all(
            key in provider for key in ("id", "index_url")
        ):
            raise ValueError("Every website requires an id and index_url")
        pid = identifier(provider["id"])
        if (
            pid in seen
            or not isinstance(provider.get("name"), str)
            or not provider["name"].strip()
        ):
            raise ValueError("Website IDs must be unique and have a display name")
        seen.add(pid)
        if not isinstance(provider.get("discovery", {}), dict):
            raise ValueError("Website discovery configuration must be an object")
        provider["index_url"] = canonical_url(provider["index_url"])
        if "snapshot_data" in provider:
            snapshot = provider.pop("snapshot_data")
        else:
            if (
                not isinstance(provider.get("snapshot"), str)
                or not provider["snapshot"]
            ):
                raise ValueError("Every website requires a reviewed snapshot path")
            reference = Path(provider["snapshot"])
            if reference.is_absolute() or ".." in reference.parts:
                raise ValueError(
                    "Snapshot paths must stay inside the source registry directory"
                )
            target = path.parent / reference
            if target.is_symlink() or not target.resolve().is_relative_to(path.parent):
                raise ValueError("Linked/outside source snapshots are not allowed")
            snapshot = read_json(target)
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("schema_version") != 1
            or not isinstance(snapshot.get("sources"), list)
        ):
            raise ValueError(f"Invalid source snapshot for {pid}")
        if any(
            not isinstance(source, dict)
            or not isinstance(source.get("kind"), str)
            or not source["kind"]
            for source in snapshot["sources"]
        ):
            raise ValueError("Every source requires a kind")
        if not all(
            isinstance(snapshot.get(key), str) and snapshot[key]
            for key in ("index_url", "observed_at", "scope")
        ):
            raise ValueError("Snapshots require index_url, observed_at and scope")
        if canonical_url(snapshot["index_url"]) != provider["index_url"]:
            raise ValueError(f"Snapshot and website index URL differ for {pid}")
        datetime.strptime(snapshot["observed_at"], "%Y-%m-%d")
        counts = dict(Counter(source["kind"] + "s" for source in snapshot["sources"]))
        if counts != snapshot.get("snapshot_counts"):
            raise ValueError(f"Snapshot source counts do not match for {pid}")
        local_ids, identities = set(), set()
        for source in snapshot["sources"]:
            sid = source.get("id")
            if not isinstance(sid, str) or not sid or sid in local_ids:
                raise ValueError(f"Source IDs must be unique inside {pid}")
            local_ids.add(sid)
            canonical_url(source.get("url"))
            if source.get("evidence_status") not in EVIDENCE_STATUSES:
                raise ValueError("Every source requires an explicit evidence status")
            if not isinstance(source.get("title"), str) or not source["title"].strip():
                raise ValueError("Every source needs a title")
            identity = entry_identity(source)
            if identity in identities:
                raise ValueError(
                    "Duplicate reviewed source identity; use url-title for intentionally shared URLs"
                )
            identities.add(identity)
            if not isinstance(source.get("updated"), str):
                raise ValueError("Every source requires an ISO date")
            datetime.strptime(source["updated"], "%Y-%m-%d")
            if not isinstance(source.get("related_sources", []), list) or any(
                not isinstance(ref, dict) or not isinstance(ref.get("source_key"), str)
                for ref in source.get("related_sources", [])
            ):
                raise ValueError(
                    "Related sources must reference namespaced source_key values"
                )
            entries.append(
                {
                    **source,
                    "provider_id": pid,
                    "provider_name": provider["name"],
                    "source_key": pid + "/" + sid,
                }
            )
        result.append(
            {
                **provider,
                "observed_at": snapshot["observed_at"],
                "snapshot_counts": counts,
                "scope": snapshot["scope"],
                "source_count": len(snapshot["sources"]),
                "sources": snapshot["sources"],
            }
        )
    if not result:
        raise ValueError("Register at least one source website")
    return {
        "schema_version": 2,
        "registry_path": str(path),
        "providers": result,
        "sources": entries,
    }


def entry_identity(entry):
    value = canonical_url(entry["url"])
    if entry.get("discovery_identity") == "url-title":
        value += "#" + " ".join(entry["title"].split()).casefold()
    return value


def index_fingerprint(entry):
    return digest({key: entry.get(key) for key in ("url", "title", "updated", "kind")})


def parse_index(html, index_url, rules):
    """CSS selectors describe entries; no website-specific Python branches."""
    from bs4 import BeautifulSoup
    from soupsieve.util import SelectorSyntaxError

    soup = BeautifulSoup(html, "html.parser")
    discovered = {}
    if not isinstance(rules, list) or not rules:
        raise ValueError("HTML discovery requires entry selectors")
    for rule in rules:
        try:
            rows = soup.select(rule["selector"])
            for row in rows:
                link = (
                    row.select_one(rule["url_selector"])
                    if rule.get("url_selector")
                    else row
                )
                title_node = (
                    row.select_one(rule["title_selector"])
                    if rule.get("title_selector")
                    else link
                )
                if link is None or title_node is None or not link.get("href"):
                    raise ValueError(
                        "An index entry is missing its configured link/title"
                    )
                title = " ".join(title_node.get_text(" ", strip=True).split())
                entry = {
                    "url": canonical_url(urljoin(index_url, link["href"])),
                    "title": title,
                    "kind": rule["kind"],
                    "updated": None,
                    "date_basis": rule.get("date_basis", "published"),
                }
                if not title:
                    raise ValueError("An index entry has an empty title")
                if rule.get("identity") == "url-title":
                    entry["discovery_identity"] = "url-title"
                if rule.get("date_selector"):
                    time = row.select_one(rule["date_selector"])
                    if time is None:
                        raise ValueError(
                            "An index entry is missing its configured date"
                        )
                    value = time.get("datetime") or time.get_text(" ", strip=True)
                    formats = rule.get("date_formats", ["%Y-%m-%d"])
                    for fmt in formats:
                        try:
                            entry["updated"] = (
                                datetime.strptime(value, fmt).date().isoformat()
                            )
                            break
                        except ValueError:
                            continue
                    if entry["updated"] is None:
                        raise ValueError(
                            "An index date does not match its configured formats"
                        )
                identity = entry_identity(entry)
                if identity in discovered and discovered[identity] != entry:
                    raise ValueError("Conflicting metadata for a duplicate source URL")
                discovered[identity] = entry
        except (KeyError, TypeError, ValueError, SelectorSyntaxError) as exc:
            raise ValueError(f"Invalid HTML discovery entry: {exc}") from exc
    if not discovered:
        raise ValueError(
            "No source entries matched; review the website selectors instead of accepting an empty index"
        )
    return sorted(discovered.values(), key=lambda entry: (entry["url"], entry["title"]))


def article_fingerprint(html, selector):
    from bs4 import BeautifulSoup
    from soupsieve.util import SelectorSyntaxError

    soup = BeautifulSoup(html, "html.parser")
    try:
        content = soup.select_one(selector)
    except SelectorSyntaxError as exc:
        raise ValueError("Invalid article content selector") from exc
    if content is None:
        raise ValueError("Article content selector did not match")
    for tag in content.select("script, style, nav, footer, noscript"):
        tag.decompose()
    text = " ".join(content.get_text(" ", strip=True).split())
    if not text:
        raise ValueError("Article content was empty")
    return digest(text)


def _fetch(client, url, hosts):
    """Only GET registered hosts, including each redirect; bound response size."""
    url = canonical_url(url)
    for _ in range(4):
        if urlsplit(url).hostname not in hosts:
            raise ValueError("A source URL/redirect left the configured website hosts")
        with client.stream("GET", url) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                url = canonical_url(urljoin(url, response.headers["location"]))
                continue
            if response.status_code != 200:
                raise ValueError(f"Source HTTP status {response.status_code}")
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 2 * 1024 * 1024:
                    raise ValueError("Source page exceeded the 2 MiB limit")
                chunks.append(chunk)
            return b"".join(chunks).decode(
                response.encoding or "utf-8", errors="replace"
            )
    raise ValueError("Source page exceeded the redirect limit")


def check_updates(
    path=SOURCE_INDEX, selected=None, *, content=False, timeout=30, transport=None
):
    """Return discovery differences only. Curated files are never mutated."""
    registry = load_registry(path)
    providers = registry["providers"]
    if selected and selected != "all":
        providers = [p for p in providers if p["id"] == selected]
        if not providers:
            raise ValueError(f"Unknown source website: {selected}")
    report = {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Configured public index pages and, when requested, article text; differences require review and never change benchmark inputs automatically.",
        "content_checked": content,
        "providers": [],
        "status": "clean",
    }
    with httpx.Client(
        timeout=timeout,
        transport=transport,
        follow_redirects=False,
        headers={"User-Agent": "MisalignReportBench source-review/0.5"},
    ) as client:
        for provider in providers:
            result = {
                "id": provider["id"],
                "name": provider["name"],
                "new": [],
                "changed": [],
                "not_listed": [],
                "untracked": [],
                "errors": [],
                "entries": [],
                "status": "clean",
            }
            config = provider.get("discovery", {})
            hosts = {
                urlsplit(provider["index_url"]).hostname,
                *config.get("allowed_hosts", []),
            }
            try:
                if config.get("adapter") != "html":
                    raise ValueError(
                        "Configure the html discovery adapter before checking this website"
                    )
                urls = config.get("index_urls", [provider["index_url"]])
                if not 1 <= len(urls) <= 10:
                    raise ValueError(
                        "Configure between one and ten explicit index pages"
                    )
                discovered = {}
                for url in urls:
                    for entry in parse_index(
                        _fetch(client, url, hosts), url, config["entries"]
                    ):
                        if urlsplit(entry["url"]).hostname not in hosts:
                            raise ValueError(
                                "An index entry left the configured website hosts"
                            )
                        discovered[entry_identity(entry)] = entry
                if len(discovered) > 250:
                    raise ValueError(
                        "More than 250 entries found; scope the index before fetching articles"
                    )
                known = {
                    entry_identity(source): source for source in provider["sources"]
                }
                body_hashes, body_errors = {}, {}
                for identity, entry in discovered.items():
                    source = known.get(identity)
                    reasons = []
                    if content:
                        try:
                            if entry["url"] in body_errors:
                                raise body_errors[entry["url"]]
                            if entry["url"] not in body_hashes:
                                body_hashes[entry["url"]] = article_fingerprint(
                                    _fetch(client, entry["url"], hosts),
                                    config.get("article_selector", "article, main"),
                                )
                            entry["content_hash"] = body_hashes[entry["url"]]
                        except (httpx.HTTPError, ValueError, KeyError) as exc:
                            body_errors[entry["url"]] = exc
                            result["errors"].append(
                                {
                                    "url": entry["url"],
                                    "stage": "article",
                                    "error_type": type(exc).__name__,
                                    "detail": str(exc)
                                    if isinstance(exc, ValueError)
                                    else "Source request failed",
                                }
                            )
                    if source is None:
                        result["new"].append(entry)
                    else:
                        entry["known_id"] = source["id"]
                        baseline = source.get("index_fingerprint")
                        if baseline is None:
                            result["untracked"].append(
                                {"id": source["id"], "field": "index_fingerprint"}
                            )
                        elif index_fingerprint(entry) != baseline:
                            reasons.append("index_metadata_changed")
                        if content and "content_hash" in entry:
                            if not source.get("content_hash"):
                                result["untracked"].append(
                                    {"id": source["id"], "field": "content_hash"}
                                )
                            elif entry["content_hash"] != source["content_hash"]:
                                reasons.append("article_content_changed")
                        if reasons:
                            result["changed"].append(
                                {
                                    "id": source["id"],
                                    "url": entry["url"],
                                    "reasons": reasons,
                                }
                            )
                    result["entries"].append(entry)
                result["not_listed"] = [
                    {"id": s["id"], "url": s["url"]}
                    for identity, s in known.items()
                    if identity not in discovered
                ]
                if (
                    result["new"]
                    or result["changed"]
                    or result["not_listed"]
                    or result["untracked"]
                ):
                    result["status"] = "review"
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                result["errors"].append(
                    {
                        "stage": "index",
                        "error_type": type(exc).__name__,
                        "message": str(exc)
                        if isinstance(exc, ValueError)
                        else "Source fetch/adapter failed",
                    }
                )
            if result["errors"]:
                result["status"] = "partial" if result["entries"] else "error"
            report["providers"].append(result)
    if any(p["errors"] for p in report["providers"]):
        report["status"] = "partial"
    elif any(p["status"] == "review" for p in report["providers"]):
        report["status"] = "review"
    return report
