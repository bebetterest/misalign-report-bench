# Register and update source websites

A website, an article and a test case are different objects. The website describes how to discover articles. A reviewed snapshot records article provenance, evidence status and the components being adapted. A case defines an executable experiment. Updating an upstream article never silently changes a task, score or saved result.

An article can map to multiple independent cases through `components`; there is no one-article/one-task restriction. Split distinct work requests or independently testable threats, keep connected stages in their appropriate task, and document exclusions. Vary concrete data with samples and controlled permissions/availability with conditions. The current 28 source entries map to 61 cases; those counts describe the selected inventory, not exhaustive reproduction of every upstream detail. See [task boundaries](extending.md#choose-case-sample-and-condition-boundaries).

The packaged registry is [`source-coverage.json`](../src/mrbench/source-coverage.json), schema 2. It points to independent snapshots in [`sources/`](../src/mrbench/sources/): OpenAI and Transluce. The source key is `website-id/article-id`; article IDs need only be unique within their website. A historical schema-1 single-index snapshot remains readable.

## Inspect and check

```sh
uv run mrbench sources list
uv run mrbench coverage
uv run mrbench sources check --provider transluce
uv run mrbench sources check --provider all --content
```

`list`, `coverage`, `validate`, evaluation and the viewer read local reviewed JSON. Only the explicit `sources check` command fetches source websites. It performs bounded GET requests to configured hosts; it does not use a model, credentials, a browser, form submission or a background scheduler. A default check compares index URLs, titles, kinds and dates. `--content` additionally compares normalized article text, excluding scripts, navigation and footers. These are change detectors, not semantic judgments: layout or editorial changes can still require review, and text hashes do not detect every image/video or JavaScript-only change.

Each check saves a new JSON report under `.cache/source-checks/`. Choose a new explicit path with `--output path/to/review.json`; an existing output is refused before fetching. The reviewed snapshots and cases are never modified by this command.

| Result field | Meaning |
| --- | --- |
| `new` | Discovered article not present in the reviewed snapshot |
| `changed` | Index metadata or normalized article text differs from its baseline |
| `not_listed` | Reviewed entry was absent from this discovery scope; this does not establish deletion or retraction |
| `untracked` | A comparison baseline is missing; review is required |
| `errors` | Fetch, selector or parsing failure; missing evidence is never interpreted as a clean check |
| `entries` | Parsed index entries, plus content hashes when successfully requested |

`clean` means no detected differences within that check's scope. `review` means differences require review. `partial` or provider-level `error` means some requested evidence could not be checked. A partial check exits nonzero; a review report can be valid even when changes exist. An empty index match is an error, rather than a mass-removal report. Some sites block direct article requests; retain that error and review through an allowed public surface. Do not interpret an inaccessible article as unchanged.

## Add another website

Copy the registry and its snapshot folder to an editable directory, then append a provider. Relative snapshot paths must remain inside the registry directory. The following uses a fictional site and selectors; replace them with the actual public page structure.

```json
{
  "id": "another-publisher",
  "name": "Another publisher",
  "index_url": "https://example.org/investigations",
  "snapshot": "sources/another-publisher.json",
  "discovery": {
    "adapter": "html",
    "article_selector": "main",
    "entries": [{
      "selector": "article.report",
      "url_selector": "h2 a",
      "title_selector": "h2 a",
      "date_selector": "time",
      "date_formats": ["%Y-%m-%d"],
      "date_basis": "published",
      "kind": "report"
    }]
  }
}
```

The `html` adapter uses [Beautiful Soup CSS selectors](https://www.crummy.com/software/BeautifulSoup/bs4/doc/#css-selectors). Standard HTML sites need only JSON, without a provider-specific Python class. Multiple entry rules can distinguish reports, notices and blog posts. Dates come from a `datetime` attribute or visible text, parsed using explicit formats. Set `identity: "url-title"` for entries that intentionally share a URL, as OpenAI's three notices do. Conflicting metadata for the same identity is rejected.

An optional `allowed_hosts` array permits explicitly reviewed article/redirect hosts. An optional `index_urls` array lists up to ten exact public index pages for pagination. There is no recursive crawler. The checker caps discovery at 250 entries and each response at 2 MiB, and validates every redirect against the host list. A JavaScript-only index or JSON API needs an explicit new adapter in `source_registry.py`; the case environments and Codex harness remain independent of that change.

Start its reviewed snapshot with an empty list to discover candidates:

```json
{
  "schema_version": 1,
  "index_url": "https://example.org/investigations",
  "observed_at": "2026-10-18",
  "snapshot_counts": {},
  "scope": "Discovery only; no articles reviewed yet.",
  "sources": []
}
```

```sh
uv run mrbench sources check --sources my-sources/source-coverage.json --provider another-publisher --content
```

This produces candidate metadata and fingerprints. It does not convert arbitrary prose into a scientifically valid test. Read each article before adding a reviewed source entry and environment.

## Review an article or revision

1. Record a stable article ID, original title/URL, date and date basis. Keep the source's date separate from the snapshot review date.
2. Distinguish reported behavior, a simulated demonstration, legitimate behavior, an unverified allegation, or observed activity with uncertain AI attribution. Do not infer a successful exploit from a request, HTTP status or tool success message.
3. Name the components you actually adapt, and map each to one or more case IDs. A representative component can summarize related public endpoints if that reduction and its limits are explicit. Counts describe this reviewed mapping, not independent original incidents.
4. Extract the ordinary task, available evidence and authorization boundary. Any invented policy, control, permission or concrete task data must be identified as an adaptation. Follow the [case guide](extending.md).
5. Copy `index_fingerprint` and, when checked, `content_hash` from the reviewed discovery report. Update `observed_at`, `scope` and `snapshot_counts` only after review. Do not approve an article merely to make a diff disappear.
6. If a revision changes an experiment, update its case/sample version and expectations. Preserve prior run evidence and grades; rerun meaningful checks before inclusion. An editorial source correction that does not affect the experiment can update provenance without rewriting benchmark inputs.

Each reviewed entry has this shape:

```json
{
  "id": "article-id",
  "title": "Original title",
  "url": "https://example.org/investigations/article-id",
  "updated": "2026-10-18",
  "date_basis": "published",
  "kind": "report",
  "evidence_status": "observed_activity",
  "components": {"Specific reviewed mechanism": ["my-case-id"]},
  "index_fingerprint": "COPY_FROM_REVIEWED_DISCOVERY",
  "content_hash": "COPY_FROM_REVIEWED_DISCOVERY"
}
```

The case's `source` contains matching `provider`, `id`, `url` and evidence status. A case can explicitly list `source.supporting_sources` with the same identity fields when more than one article supports that abstraction. Use `related_sources` references such as `openai/article-id` in a snapshot for related reading. A relation does not merge evidence, provider attribution or incident counts.

```sh
uv run mrbench validate --cases my-cases --sources my-sources/source-coverage.json
uv run mrbench view --cases my-cases --sources my-sources/source-coverage.json
```

The coverage validator checks every registered component, primary/supporting source identity and case mapping. A custom case library can be a subset; use a matching custom registry when you want complete coverage validation. Normal evaluation never depends on the source site being online. Packaging includes all registered snapshot JSON files, so source browsing works after installation.
