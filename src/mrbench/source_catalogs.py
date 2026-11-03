"""Versioned discovery catalogs, separate from reviewed experimental sources.

Catalog annotations are leads. A clean catalog comparison does not verify its
claims or the linked primary reports. Normal evaluation never fetches a catalog.
"""

from collections import Counter
from datetime import datetime
from pathlib import Path
import json
import re

import httpx

from .catalog import digest, identifier, read_json

DECISIONS = {"included", "covered", "deferred", "excluded"}


def normalize_rows(text, fields):
    """Read bounded JSONL metadata without executing source content."""
    from .source_registry import canonical_url

    rows = []
    seen = set()
    for line in text.splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError("Catalog rows must be JSON objects")
        item = {key: raw.get(field) for key, field in fields.items()}
        for key in ("id", "title", "url"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError("Catalog rows require an id, title and source URL")
        if len(item["id"]) > 100 or item["id"] in seen:
            raise ValueError("Catalog record IDs must be unique and bounded")
        item["url"] = canonical_url(item["url"])
        item["content_hash"] = digest(raw)
        seen.add(item["id"])
        rows.append(item)
        if len(rows) > 500:
            raise ValueError("Catalog exceeded the 500-entry discovery limit")
    if not rows:
        raise ValueError("Empty catalog is not evidence that all entries disappeared")
    return rows


def load_catalogs(configs, root):
    """Load metadata and editorial decisions; do not claim report verification."""
    from .source_registry import canonical_url

    if not isinstance(configs, list):
        raise ValueError("Discovery catalogs must be a list")
    catalogs = []
    seen = set()
    for config in configs:
        if not isinstance(config, dict):
            raise ValueError("Catalog configuration must be an object")
        cid = identifier(config.get("id"))
        if (
            cid in seen
            or not isinstance(config.get("name"), str)
            or not config["name"].strip()
        ):
            raise ValueError("Catalog IDs must be unique and have names")
        seen.add(cid)
        for key in ("index_url", "revision_url", "data_url"):
            value = config.get(key)
            if not isinstance(value, str):
                raise ValueError("Catalog URLs are required")
            canonical_url(value.replace("{revision}", "0" * 40))
        if config.get("adapter") != "jsonl" or "{revision}" not in config["data_url"]:
            raise ValueError("Catalog discovery requires revision-pinned JSONL")
        fields = config.get("fields")
        if (
            not isinstance(fields, dict)
            or not {"id", "title", "url"} <= fields.keys()
            or any(
                not isinstance(k, str) or not isinstance(v, str) or not v
                for k, v in fields.items()
            )
        ):
            raise ValueError("Catalog fields require explicit JSON keys")
        if not isinstance(config.get("snapshot"), str) or not config["snapshot"]:
            raise ValueError("Catalog requires a reviewed snapshot path")
        reference = Path(config["snapshot"])
        target = Path(root) / reference
        if (
            reference.is_absolute()
            or ".." in reference.parts
            or target.is_symlink()
            or not target.resolve().is_relative_to(Path(root).resolve())
        ):
            raise ValueError("Catalog snapshot must stay in the registry directory")
        snapshot = read_json(target)
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("schema_version") != 1
            or snapshot.get("id") != cid
        ):
            raise ValueError("Invalid catalog snapshot identity")
        datetime.strptime(snapshot["reviewed_at"], "%Y-%m-%d")
        if not re.fullmatch(r"[0-9a-f]{40,64}", snapshot.get("upstream_revision", "")):
            raise ValueError("Catalog snapshot needs an upstream revision")
        if any(
            not isinstance(snapshot.get(k), str) or not snapshot[k].strip()
            for k in ("license", "scope")
        ):
            raise ValueError("Catalog snapshot needs license and scope information")
        entries = snapshot.get("entries")
        if not isinstance(entries, list) or not entries or len(entries) > 500:
            raise ValueError("Catalog snapshot requires bounded baseline entries")
        entry_ids = set()
        for entry in entries:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("id"), str)
                or entry["id"] in entry_ids
            ):
                raise ValueError("Invalid or duplicate catalog snapshot entry")
            entry_ids.add(entry["id"])
            canonical_url(entry.get("url"))
            if not re.fullmatch(r"[0-9a-f]{64}", entry.get("content_hash", "")):
                raise ValueError("Catalog entry requires a content hash")
            decision = entry.get("decision", {})
            if not isinstance(decision, dict):
                raise ValueError("Catalog inclusion decision must be an object")
            if (
                decision.get("status") not in DECISIONS
                or not isinstance(decision.get("reason"), str)
                or not decision["reason"].strip()
            ):
                raise ValueError(
                    "Each catalog entry requires an explicit inclusion decision"
                )
            case_ids = decision.get("case_ids", [])
            if not isinstance(case_ids, list):
                raise ValueError("Catalog case references must be a list")
            for case_id in case_ids:
                identifier(case_id)
            if decision["status"] in {"included", "covered"} and not case_ids:
                raise ValueError("Included and covered entries must name real cases")
        catalogs.append({**snapshot, **config})
    return catalogs


def check_catalog(client, catalog):
    """Detect record changes; never follow arbitrary primary-source links."""
    from .source_registry import _fetch
    from urllib.parse import urlsplit

    result = {
        "id": catalog["id"],
        "name": catalog["name"],
        "role": "discovery_catalog",
        "new": [],
        "changed": [],
        "not_listed": [],
        "untracked": [],
        "errors": [],
        "entries": [],
        "status": "clean",
        "scope": "Catalog annotation changes only; primary reports require separate review.",
    }
    hosts = {urlsplit(catalog["index_url"]).hostname, *catalog.get("allowed_hosts", [])}
    try:
        metadata = json.loads(_fetch(client, catalog["revision_url"], hosts))
        revision = metadata.get("sha")
        if not isinstance(revision, str) or not re.fullmatch(
            r"[0-9a-f]{40,64}", revision
        ):
            raise ValueError("Catalog revision metadata is invalid")
        text = _fetch(
            client, catalog["data_url"].replace("{revision}", revision), hosts
        )
        entries = normalize_rows(text, catalog["fields"])
        known = {x["id"]: x for x in catalog["entries"]}
        found = {x["id"] for x in entries}
        for entry in entries:
            old = known.get(entry["id"])
            if old is None:
                result["new"].append(entry)
            elif entry["content_hash"] != old["content_hash"]:
                result["changed"].append(
                    {
                        "id": entry["id"],
                        "url": entry["url"],
                        "reasons": ["catalog_record_changed"],
                    }
                )
        result["not_listed"] = [
            {"id": x["id"], "url": x["url"]}
            for x in catalog["entries"]
            if x["id"] not in found
        ]
        result.update(entries=entries, upstream_revision=revision)
        if result["new"] or result["changed"] or result["not_listed"]:
            result["status"] = "review"
    except (ValueError, KeyError, TypeError, OSError, httpx.HTTPError) as exc:
        result["errors"].append(
            {
                "stage": "catalog",
                "error_type": type(exc).__name__,
                "detail": str(exc)[:250],
            }
        )
        result["status"] = "error"
    return result


def catalog_summary(catalog):
    """A separate discovery inventory, never an executable-coverage denominator."""
    return {
        "id": catalog["id"],
        "name": catalog["name"],
        "index_url": catalog["index_url"],
        "reviewed_at": catalog["reviewed_at"],
        "upstream_revision": catalog["upstream_revision"],
        "entry_count": len(catalog["entries"]),
        "decisions": dict(Counter(x["decision"]["status"] for x in catalog["entries"])),
        "license": catalog["license"],
        "scope": catalog["scope"],
        "entries": catalog["entries"],
    }
