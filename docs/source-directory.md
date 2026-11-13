# Source directory

MisalignReportBench adapts selected public reports, system cards and research findings into executable evaluations. Use this directory to find the original publications and the places to check for new material.

## Browse the reviewed library

- **Browse by article or behavior.** Start the [local viewer](../README.md#explore-the-benchmark-locally) with `uv run mrbench view` and open [Sources](http://127.0.0.1:8765/#/sources). Search by title or mechanism, filter by publisher, and follow each article's links to the relevant cases.
- **Read in the repository.** The source snapshots below contain every reviewed article, its original URL, evidence status and case mapping. The [OpenAI report guide](report-environments.md), [Transluce guide](transluce-environments.md) and [behavior cases](behavior-cases.md) explain selected adaptations and controls.
- **Inspect from the terminal.** Use `uv run mrbench sources list` for provider names, review dates and upstream URLs. Use `uv run mrbench coverage` for article-to-case mappings and the reviewed catalog revision. Both commands read the local snapshots.

| Publisher or catalog | Where to look upstream | Reviewed material and update path |
| --- | --- | --- |
| **OpenAI** | [Misalignment Reports and Notices](https://alignment.openai.com/misalignment-reports/) · [Deployment Safety Hub](https://deploymentsafety.openai.com/) · [Safety and alignment news](https://openai.com/news/safety-alignment/) | [Reviewed articles and case mappings](../src/mrbench/sources/openai.json). The checker discovers entries in the reports and notices index. Check the Safety Hub and release news directly for new system cards, addenda and companion reports. A content check also revisits registered supplemental articles. |
| **Anthropic** | [Research](https://www.anthropic.com/research) · [Alignment Science Blog](https://alignment.anthropic.com/) · [Model system cards](https://www.anthropic.com/system-cards) · [News and release announcements](https://www.anthropic.com/news) | [Reviewed articles and case mappings](../src/mrbench/sources/anthropic.json). The checker revisits known originals. Check research, the Alignment Science Blog, the card index and release announcements directly for new material. A release can link a system card before it appears in the card index. |
| **Transluce** | [Incident Investigations](https://transluce.org/investigations) | [Reviewed investigations and case mappings](../src/mrbench/sources/transluce.json). The checker discovers incident investigation articles from this index. |
| **Alignment Hub** | [Public catalog](https://huggingface.co/spaces/witness-archive/alignment-hub) · [Dataset and revisions](https://huggingface.co/datasets/witness-archive/alignment-hub) | [Screened catalog snapshot](../src/mrbench/source-catalogs/alignment-hub.json) · [Selection guide](alignment-hub.md). The checker resolves the upstream revision and compares its records with the pinned review snapshot. For a candidate case, read and cite the original publication. |

The publisher snapshots are the inventory of admitted sources. One source may support several cases, and a case may cite more than one source. Catalog records have a separate inventory and screening decisions. An article's presence in an upstream index or in a catalog does not give it benchmark coverage.

## Review updates and extend the directory

1. **Check for changes.** Run `uv run mrbench sources check --provider all --content` for the configured indexes, reviewed URLs and catalog. For a full refresh, also check the official release, research and system-card pages above. Record the scope and any inaccessible articles.
2. **Read the original and compare mechanisms.** Look for a documented task, the relevant obstacle or authorization boundary, and an outcome that can be observed and scored. Link corroborating publications to existing cases when they support the same mechanism. Keep unresolved or overlapping leads separate from admitted cases.
3. **Add a new source when it earns a mapping.** An article from an existing publisher can enter that publisher's snapshot. A new publisher gets its own registry entry and reviewed snapshot. A third-party discovery catalog stays separate and links back to originals. Update this directory when a new provider, catalog or recurring discovery entrance becomes useful. See [registry setup and review rules](sources.md).

The directory can grow to include other public publishers, independent investigations and research projects. The same evidence and adaptation criteria apply regardless of where a lead was found.

### Research lead

Anthropic's Project EVE assigns one agent a private sabotage role among cooperating teammates. A future benchmark could give the evaluated agent an ordinary team objective and measure how it verifies conflicting messages, attributes mistakes and escalates when resources are scarce. Keep assigned adversarial behavior, tool faults and mistaken accusations separate. This lead has no executable case or coverage count. [Project EVE](https://www.anthropic.com/research/project-eve-claude-plays-mmorpgs)
