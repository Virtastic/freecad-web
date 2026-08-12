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
# The mesher, fetched by the page on first use (FEM meshing 404s without it).
COPY play-gui/gmsh.js play-gui/gmsh.wasm /usr/share/nginx/html/
# CalculiX solver module, fetched on first solve.
COPY play-gui/ccx.js play-gui/ccx.wasm /usr/share/nginx/html/

EXPOSE 80
