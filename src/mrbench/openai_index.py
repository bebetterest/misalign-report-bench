"""Read the full public report list embedded in OpenAI's paginated index."""

from collections import Counter
from datetime import date
import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .source_registry import canonical_url, entry_identity

LEGACY_PREFIX = "https://alignment.openai.com/misalignment-reports/"
CURRENT_PREFIX = "https://openai.com/safety-alignment/misalignment-reports/"
GROUPS = {
    "reports": ("report", "lastUpdated", "report_updated"),
    "notices": ("notice", "firstPosted", "index_first_posted"),
}


def report_identity(entry):
    """Recognize pre-migration source URLs without changing reviewed records."""
    url = entry["url"]
    if url.startswith(LEGACY_PREFIX):
        entry = {**entry, "url": CURRENT_PREFIX + url[len(LEGACY_PREFIX):]}
    return entry_identity(entry)


def parse_report_index(html, index_url):
    page = BeautifulSoup(html, "html.parser")
    counts = {}
    chunks = []
    for group in GROUPS:
        tab = page.select_one(f'main a[href="#{group}"]')
        label = tab.get_text(" ", strip=True) if tab else ""
        count = re.fullmatch(rf"{group} (\d+)", label, re.IGNORECASE)
        if not count:
            raise ValueError("OpenAI report index is missing a section count")
        counts[group] = int(count[1])
    for script in page.find_all("script"):
        push = re.fullmatch(
            r"self\.__next_f\.push\((.*)\);?", (script.string or "").strip(), re.DOTALL
        )
        if push:
            data = json.loads(push[1])
            if (
                isinstance(data, list) and len(data) == 2
                and data[0] == 1 and isinstance(data[1], str)
            ):
                chunks.append(data[1])

    payload = "".join(chunks)
    candidates = []
    decoder = json.JSONDecoder()
    for field in re.finditer(r'"items"\s*:\s*(?=\[)', payload):
        rows, _ = decoder.raw_decode(payload, field.end())
        if rows and isinstance(rows[0], dict) and "reportDates" in rows[0]:
            candidates.append(rows)
    if len(candidates) != 1:
        raise ValueError("OpenAI report index did not contain one complete report list")

    entries = {}
    observed = Counter()
    for row in candidates[0]:
        try:
            (group,) = row["filters"]["type"]
            kind, date_field, date_basis = GROUPS[group]
            title = " ".join(row["title"].split())
            if not title or not row["href"]:
                raise ValueError("empty title or link")
            entry = {
                "url": canonical_url(urljoin(index_url, row["href"])),
                "title": title,
                "kind": kind,
                "updated": date.fromisoformat(row["reportDates"][date_field]).isoformat(),
                "date_basis": date_basis,
            }
            if kind == "notice":
                entry["discovery_identity"] = "url-title"
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid entry in the OpenAI report index") from exc
        identity = report_identity(entry)
        if identity in entries:
            raise ValueError("Duplicate entry in the OpenAI report index")
        entries[identity] = entry
        observed[group] += 1
    if any(observed[group] != count for group, count in counts.items()):
        raise ValueError("OpenAI report list does not match the published section counts")
    return sorted(entries.values(), key=lambda entry: (entry["url"], entry["title"]))
