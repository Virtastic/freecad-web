# SPDX-License-Identifier: LGPL-2.1-or-later
# freecad-web as a self-contained static-site container: nginx + the built site, serving
# the cross-origin-isolation headers itself so it works behind ANY host-routing reverse
# proxy on the shared box. TLS is terminated upstream (the shared proxy / Cloudflare).
#
# Build context is the REPO ROOT (needs infra/nginx.conf + play-gui/). The large build
# artifacts (FreeCAD.wasm/.data/.js) are gitignored; CI downloads them into play-gui/ from a
# GitHub Release before building (see .github/workflows/deploy-ovh.yml).
FROM nginx:1.27-alpine

RUN rm -f /etc/nginx/conf.d/default.conf
COPY infra/nginx.conf /etc/nginx/conf.d/freecad.conf

# Front-end (in git).
COPY play-gui/freecad-gui.html play-gui/qtloader.js /usr/share/nginx/html/
# Installability: an installed app is the only case where Chrome grants persistent
# storage without a prompt, which is what protects a user's documents from eviction.
COPY play-gui/manifest.webmanifest play-gui/sw.js play-gui/icon-192.png play-gui/icon-512.png /usr/share/nginx/html/
# Build artifacts (fetched into play-gui/ by CI from the release).
COPY play-gui/FreeCAD.js play-gui/FreeCAD.wasm play-gui/FreeCAD.data /usr/share/nginx/html/
# FreeCAD.data is 341 MB and gzips to 83 MB. Cloudflare does not compress it (wrong
# content type) so it used to go over the wire raw -- 84% of a first-time visitor's
# download. nginx serves this copy to anything that accepts gzip; see infra/nginx.conf.
# -6 rather than -9: within a megabyte of the same size for a fraction of the build time.
RUN gzip -6 -k /usr/share/nginx/html/FreeCAD.data \
 && test -s /usr/share/nginx/html/FreeCAD.data.gz
# Tie the data URL to the data's CONTENT. The page requests FreeCAD.data.gz?v=... and that
# response is Cache-Control: immutable for a year, so a hand-written version is a trap:
# ship new data under the old ?v= and every returning visitor keeps the stale copy until
# 2027. Stamping the checksum makes a changed file a different URL automatically, and an
# unchanged one keep its cache. Fails the build rather than shipping an unstamped page.
# Content-address the ENGINE TRIPLE together. These three are one unit: FreeCAD.js
# carries the byte offsets of every file inside FreeCAD.data, and the wasm is built
# against both. They are served Cache-Control: immutable for a year, so a returning
# browser kept its cached FreeCAD.js while fetching new data and CPython's own stdlib
# failed to load -- "Failed to import encodings module". Stamping each URL with its
# content makes a changed file a new URL and keeps an unchanged one cached.
RUN JS=$(md5sum /usr/share/nginx/html/FreeCAD.js   | cut -c1-12) \
 && WA=$(md5sum /usr/share/nginx/html/FreeCAD.wasm | cut -c1-12) \
 && DA=$(md5sum /usr/share/nginx/html/FreeCAD.data | cut -c1-12) \
 && sed -i "s|FreeCAD\.data\.gz?v=[A-Za-z0-9]*|FreeCAD.data.gz?v=$DA|g; \
            s|'FreeCAD\.js'|'FreeCAD.js?v=$JS'|g; \
            s|'FreeCAD\.wasm'|'FreeCAD.wasm?v=$WA'|g" \
        /usr/share/nginx/html/freecad-gui.html \
 && grep -q "FreeCAD.data.gz?v=$DA" /usr/share/nginx/html/freecad-gui.html \
 && grep -q "FreeCAD.js?v=$JS"      /usr/share/nginx/html/freecad-gui.html \
 && grep -q "FreeCAD.wasm?v=$WA"    /usr/share/nginx/html/freecad-gui.html \
 && echo "stamped js=$JS wasm=$WA data=$DA"
# The mesher, fetched by the page on first use (FEM meshing 404s without it).
COPY play-gui/gmsh.js play-gui/gmsh.wasm /usr/share/nginx/html/
# CalculiX solver module, fetched on first solve.
COPY play-gui/ccx.js play-gui/ccx.wasm /usr/share/nginx/html/

# Stamp the mesher and solver too. They were served Cache-Control: immutable for a YEAR
# while their URLs were bare, so a rebuilt gmsh or ccx would have stayed stale in a
# returning browser for up to twelve months -- a correctness bug wearing a caching costume.
# A Cloudflare purge cannot fix that; only a different URL can.
RUN GM=$(md5sum /usr/share/nginx/html/gmsh.wasm | cut -c1-12) \
 && CX=$(md5sum /usr/share/nginx/html/ccx.wasm  | cut -c1-12) \
 && sed -i "s|'gmsh\.js'|'gmsh.js?v=$GM'|g; \
            s|'ccx\.js'|'ccx.js?v=$CX'|g" \
        /usr/share/nginx/html/freecad-gui.html \
 && grep -q "gmsh.js?v=$GM" /usr/share/nginx/html/freecad-gui.html \
 && grep -q "ccx.js?v=$CX"  /usr/share/nginx/html/freecad-gui.html \
 && echo "stamped gmsh=$GM ccx=$CX"

# Build identity, so a bug report can name the build it came from. Supplied by CI as the
# release tag + short SHA; defaults to "unknown" for a local image build.
ARG FCWEB_BUILD=unknown
RUN sed -i "s|__FCWEB_BUILD__|${FCWEB_BUILD}|g" /usr/share/nginx/html/freecad-gui.html \
 && ! grep -q "__FCWEB_BUILD__" /usr/share/nginx/html/freecad-gui.html \
 && echo "stamped build=${FCWEB_BUILD}"

EXPOSE 80

# `restart: unless-stopped` only restarts a container that EXITED. An nginx that is up but
# wedged is never noticed, and nothing outside watches this box. Checking the entry page
# (not just the port) also catches the case where the html failed to stamp or copy.
HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/freecad-gui.html || exit 1
