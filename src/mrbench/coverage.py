"""Dated public-source coverage, independent of model-run results."""

from collections import Counter

from .source_registry import SOURCE_INDEX, load_registry


def source_coverage(cases, path=SOURCE_INDEX):
    registry = load_registry(path)
    entries = []
    source_ids = set()
    referenced = set()
    for source in registry["sources"]:
        source_ids.add(source["source_key"])
        components = source.get("components", {})
        if not isinstance(components, dict) or not components:
            raise ValueError("Every source needs named mechanism components")
        missing = []
        case_ids = []
        for component, ids in components.items():
            if (
                not component
                or not isinstance(ids, list)
                or not ids
                or any(not isinstance(cid, str) for cid in ids)
            ):
                raise ValueError("Invalid source component mapping")
            for cid in ids:
                referenced.add(cid)
                case_ids.append(cid)
                if cid not in cases:
                    missing.append(cid)
                    continue
                case_source = cases[cid].spec["source"]
                primary = (
                    case_source["url"] == source["url"]
                    and case_source.get("id", source["id"]) == source["id"]
                    and case_source.get("provider", source["provider_id"])
                    == source["provider_id"]
                )
                supporting = any(
                    ref.get("url") == source["url"]
                    and ref.get("id") == source["id"]
                    and ref.get("provider") == source["provider_id"]
                    for ref in case_source.get("supporting_sources", [])
                )
                if not primary and not supporting:
                    raise ValueError(f"Case {cid} is mapped to a different source URL")
                if (
                    primary
                    and "evidence_status" in case_source
                    and case_source["evidence_status"] != source["evidence_status"]
                ):
                    raise ValueError(f"Case {cid} changes its source's evidence status")
        entries.append(
            {
                **source,
                "case_ids": sorted(set(case_ids)),
                "missing_cases": sorted(set(missing)),
                "covered": not missing,
            }
        )
    for source in entries:
        for relation in source.get("related_sources", []):
            if relation["source_key"] not in source_ids:
                raise ValueError(f"Unknown related source: {relation['source_key']}")
    counts = dict(Counter(source["kind"] + "s" for source in entries))
    unmapped = sorted(set(cases) - referenced)
    providers = []
    for provider in registry["providers"]:
        selected = [
            source for source in entries if source["provider_id"] == provider["id"]
        ]
        providers.append(
            {
                key: provider[key]
                for key in (
                    "id",
                    "name",
                    "index_url",
                    "observed_at",
                    "scope",
                    "snapshot_counts",
                    "source_count",
                )
            }
        )
        providers[-1].update(
            covered_sources=sum(s["covered"] for s in selected),
            case_count=len(
                {
                    cid
                    for source in selected
                    for cid in source["case_ids"]
                    if cid in cases
                }
            ),
        )
    return {
        "observed_at": min(p["observed_at"] for p in providers),
        "latest_observed_at": max(p["observed_at"] for p in providers),
        "index_url": providers[0]["index_url"],
        "scope": "Reviewed, dated source snapshots; website update checks are separate and never rewrite benchmark inputs.",
        "providers": providers,
        "provider_count": len(providers),
        "snapshot_counts": counts,
        "covered_sources": sum(s["covered"] for s in entries),
        "source_count": len(entries),
        "case_count": len(cases),
        "unmapped_cases": unmapped,
        "coverage_complete": all(s["covered"] for s in entries) and not unmapped,
        "sources": entries,
    }


def validate_coverage(cases, path=SOURCE_INDEX):
    coverage = source_coverage(cases, path)
    if not coverage["coverage_complete"]:
        missing = sorted(
            {cid for source in coverage["sources"] for cid in source["missing_cases"]}
        )
        raise ValueError(
            f"Source coverage is incomplete; missing cases: {missing}; unmapped cases: {coverage['unmapped_cases']}"
        )
    return coverage
