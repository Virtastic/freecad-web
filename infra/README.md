<!-- SPDX-License-Identifier: LGPL-2.1-or-later -->
# freecad-web deploy (freecad.virtastic.app)

The live site is deployed by a **self-hosted GitHub Actions runner that runs ON the origin VPS**,
triggered by a push to the **`ovhcloud`** branch. The runner builds the container locally and
wires it into a shared `edge-caddy` reverse proxy. The container serves its own COOP/COEP headers
(mandatory for the Qt multi-thread wasm; without SharedArrayBuffer it will not boot).

FreeCAD is **not** compiled on the box (the build is huge). The prebuilt artifacts ride in a
**GitHub Release**; the deploy workflow pulls them into the build context before `docker build`.

The origin address is deliberately not recorded in this repo — Cloudflare proxies the hostname so
the origin stays private. CI reads it from the `ORIGIN_IP` repository variable, and Terraform from
`TF_VAR_origin_ip`.

## Files
| File | Role |
|---|---|
| `.github/workflows/deploy-ovh.yml` | the deploy — self-hosted-runner build + health-check (push to `ovhcloud`) |
| `.github/workflows/dns.yml` | stateless Cloudflare A-record upsert |
| `docker-compose.prod.yml` | the prod container: `freecad` on the external `nostalgia` network, no host ports |
| `deploy/freecad.caddy` | edge vhost drop-in: TLS origin cert + `import sec_headers` + `reverse_proxy freecad:80` |
| `infra/Dockerfile` | `nginx:1.27-alpine` + front-end (git) + artifacts (from Release) |
| `infra/nginx.conf` | serves COOP/COEP on every response; landing page; hard-caches `.wasm/.data/.js` |

## Cut a deploy
```bash
# 1. Build locally -> play-gui/FreeCAD.{js,wasm,data}   (see BUILD-WEH.md for the full lane)
FC_SKIP_CONFIGURE=1 bash build-browser-gui.sh

# 2. Publish the artifacts as a Release BEFORE pushing — CI pulls them by tag.
#    ALL SEVEN, always: CI hard-fails on a missing asset, and gmsh/ccx are separate wasm
#    modules that a FreeCAD-only relink does not rebuild -- re-upload them unchanged.
gh release create build-$(date +%Y%m%d) \
    play-gui/FreeCAD.js play-gui/FreeCAD.wasm play-gui/FreeCAD.data \
    play-gui/gmsh.js play-gui/gmsh.wasm play-gui/ccx.js play-gui/ccx.wasm \
    --title "build $(date +%Y-%m-%d)" --notes "engine build"

# 3. Ship it: push the ovhcloud branch -> the runner deploys + health-checks
git push origin main:ovhcloud
#    (or Actions -> "deploy-ovh (freecad.virtastic.app)" -> Run workflow)
```

## Box prerequisites (already satisfied)
Self-hosted runner (`self-hosted, ovh, virtastic`), the `edge-caddy` container importing its
vhost drop-ins, the external `nostalgia` network, and the origin TLS cert. Cloudflare DNS for
`freecad.virtastic.app` → the box (proxied, Full strict). The workflow drops in the vhost +
compose and restarts the edge.

## Verify
```bash
curl -sI https://freecad.virtastic.app/ | grep -i cross-origin
# COOP=same-origin AND COEP=require-corp, else the app boots to a blank page.
```
