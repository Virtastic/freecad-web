# SPDX-License-Identifier: LGPL-2.1-or-later
# freecad-wasm as a self-contained static-site container: nginx + the built site, serving
# the cross-origin-isolation headers itself so it works behind ANY host-routing reverse
# proxy on the shared box. TLS is terminated upstream (the shared proxy / Cloudflare).
#
# Build context is the REPO ROOT (needs infra/nginx.conf + play-gui/). The large build
# artifacts (FreeCAD.wasm/.data/.js) are gitignored; CI downloads them into play-gui/ from a
# GitHub Release before building (see .github/workflows/deploy-freecad.yml).
FROM nginx:1.27-alpine

RUN rm -f /etc/nginx/conf.d/default.conf
COPY infra/nginx.conf /etc/nginx/conf.d/freecad.conf

# Front-end (in git).
COPY play-gui/freecad-gui.html play-gui/qtloader.js /usr/share/nginx/html/
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
RUN V=$(md5sum /usr/share/nginx/html/FreeCAD.data | cut -c1-12) \
 && sed -i "s|FreeCAD\.data\.gz?v=[A-Za-z0-9]*|FreeCAD.data.gz?v=$V|g" \
        /usr/share/nginx/html/freecad-gui.html \
 && grep -q "FreeCAD.data.gz?v=$V" /usr/share/nginx/html/freecad-gui.html \
 && echo "data URL stamped with $V"
# The mesher, fetched by the page on first use (FEM meshing 404s without it).
COPY play-gui/gmsh.js play-gui/gmsh.wasm /usr/share/nginx/html/
# CalculiX solver module, fetched on first solve.
COPY play-gui/ccx.js play-gui/ccx.wasm /usr/share/nginx/html/

EXPOSE 80
