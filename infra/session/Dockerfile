# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# The optional shared-session service. One stdlib Python file for the session protocol;
# the MCP layer (app.py) is added in a later step and swaps CMD to uvicorn.
FROM python:3.12-alpine
WORKDIR /srv
COPY infra/session/share.py /srv/share.py
# The selftest is the build gate: an image whose protocol is broken must not build.
RUN python /srv/share.py --selftest
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8000/share/health || exit 1
CMD ["python", "/srv/share.py", "--serve", "8000"]
