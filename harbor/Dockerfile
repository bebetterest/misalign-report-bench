# Build with the wheel and locked requirements from the same checkout as the export.
FROM python:3.12-slim AS runtime
ARG PIP_NO_INDEX
COPY requirements.txt /tmp/requirements.txt
COPY *.whl /tmp/wheels/
RUN pip install --no-cache-dir --require-hashes --find-links /tmp/wheels -r /tmp/requirements.txt \
 && pip install --no-cache-dir --no-deps /tmp/wheels/misalign_report_bench-*.whl \
 && rm -rf /tmp/wheels /tmp/requirements.txt \
 && mkdir /tests \
 && printf '#!/bin/sh\nset -eu\nexec python -m mrbench.harbor_bridge verify\n' > /tests/test.sh \
 && chmod 755 /tests/test.sh

FROM runtime AS agent
# Use the matching Codex companion, or an installed Grok Build binary, in bin/.
COPY bin/ /usr/local/bin/
RUN rm -rf /usr/local/lib/python3.12/site-packages/mrbench/cases /tests
