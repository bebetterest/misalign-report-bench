# Sources and third-party materials

## Original reports

MisalignReportBench independently adapts public AI behavior reports from OpenAI and Transluce. It is not affiliated with either publisher and does not imply endorsement.

- [Model misalignment reporting framework](https://openai.com/index/model-misalignment-reporting-framework/)
- [Misalignment Reports](https://alignment.openai.com/misalignment-reports/)
- [Uploading files to the internet in order to cite them](https://alignment.openai.com/misalignment-reports/uploading-files-to-the-internet-in-order-to-cite-them/)

The first case adapts the report’s lake-query example. The complete dated mapping of 19 reports and 3 notices is in [`source-coverage.json`](src/mrbench/source-coverage.json) and [report environments](docs/report-environments.md). The notices also cite [OpenAI’s incident announcement](https://openai.com/hugging-face-incident-and-misalignment/) and its linked technical report. These sources are cited and briefly summarized; full upstream articles, incident logs and exploit code are not distributed. The case definition records the original URL, dates, scope and abstraction limits. Original sources retain their copyright and terms; the project’s MIT license covers the self-authored adaptations.

The registry also includes the five entries reviewed on [Transluce Investigations](https://transluce.org/investigations): two investigation reports and three volunteer blog posts. Their article URLs, dates, component mappings, uncertain attribution and limitations are recorded in [`sources/transluce.json`](src/mrbench/sources/transluce.json) and the [Transluce guide](docs/transluce-environments.md). These sources remain distinct from OpenAI's observations, including where topics overlap. Full articles, public request logs, original audio/media, exposed credentials and executable payloads are not included. Fictional task data, inert encoded JSON and reduced request labels are newly authored adaptations. Local full-page review caches are ignored and excluded from distribution.

## Project materials

Self-authored code, documentation and fictional task data are covered by [LICENSE](LICENSE). Invented names and records replace original datasets. All task credentials, account tokens, wallet phrases, services and commands are inert fixtures, not original credentials or operational exploit payloads. Simulated images, compaction material, CI, co-agent replies and service responses are identified as adaptations in each case. The MIT license covers these self-authored fixtures; it does not relicense upstream facts or materials.

## Icons

The viewer uses unmodified icons from [Feather](https://github.com/feathericons/feather), version 4.29.2, under the MIT license. The upstream license is included at [`src/mrbench/web/icons/LICENSE`](src/mrbench/web/icons/LICENSE). OpenAI logos and proprietary fonts are not distributed as application assets.

## Dependencies

The Python runtime uses the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), [HTTPX](https://www.python-httpx.org/) and [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/) for explicit HTML source discovery, with versions recorded in `uv.lock`. Dependencies and their transitive packages retain their own licenses. The viewer has no frontend framework, database or build-time asset dependency.
