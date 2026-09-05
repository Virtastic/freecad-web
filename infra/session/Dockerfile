# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# The optional shared-session service: the stdlib session core plus the MCP layer.
# share.py is stdlib and carries the protocol; app.py is Starlette + FastMCP over it.
FROM python:3.12-alpine
WORKDIR /srv
COPY infra/session/share.py infra/session/app.py /srv/
# The selftest is the build gate: an image whose protocol is broken must not build.
RUN python /srv/share.py --selftest
# The one place this project breaks stdlib-first: MCP's Streamable HTTP transport has
# client-visible details worth not owning. Pinned by minimum, not exact, on purpose --
# Starlette are pinned by minimum only.
RUN pip install --no-cache-dir "mcp>=1.10,<2" "uvicorn>=0.30" "starlette>=0.40" \
 && python -c "import app"
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8000/share/health || exit 1
CMD ["python", "/srv/app.py"]
