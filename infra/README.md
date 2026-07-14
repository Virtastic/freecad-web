<!-- SPDX-License-Identifier: LGPL-2.1-or-later -->
# freecad-wasm deploy (freecad.virtastic.app)

Mirrors **openmw-wasm / ja2-web**: the live site is deployed by a **self-hosted GitHub Actions
runner that runs ON the OVH VPS**, triggered by a push to the **`ovhcloud`** branch. The runner
builds the container locally and wires it into the shared **`edge-caddy`** reverse proxy on the
**`nostalgia`** docker network. The container serves its own COOP/COEP headers (mandatory for the
Qt multi-thread wasm; without SharedArrayBuffer it will not boot).

FreeCAD is **not** compiled on the box (the build is huge). The prebuilt artifacts
(`FreeCAD.js/.wasm/.data`, ~456 MB, gitignored) ride in a **GitHub Release**; the deploy workflow
pulls them into the build context before `docker build`.

## Files
| File | Role |
|---|---|
| `.github/workflows/deploy-ovh.yml` | **primary** — self-hosted-runner deploy to the box (push to `ovhcloud`) |
| `.github/workflows/deploy-freecad.yml` | secondary — builds a portable image and pushes to GHCR (grab-and-go; not how the box updates) |
| `docker-compose.prod.yml` | the prod container: `freecad` on the external `nostalgia` network, no host ports |
| `deploy/freecad.caddy` | edge vhost drop-in (`/opt/edge/sites/`): TLS origin cert + `import sec_headers` + `reverse_proxy freecad:80` |
| `infra/Dockerfile` | `nginx:1.27-alpine` + front-end (git) + artifacts (from Release) |
| `infra/nginx.conf` | serves COOP/COEP on every response; landing page; hard-caches `.wasm/.data/.js` |
| `infra/docker-compose.yml` | generic Traefik example (portability; not used by the OVH box) |

## Cut a deploy
```bash
# 1. Build locally -> play-gui/FreeCAD.{js,wasm,data}
FC_SKIP_CONFIGURE=1 bash build-browser-gui.sh

# 2. Publish the artifacts as a Release (deploy-ovh pulls the latest by default)
gh release create build-$(date +%Y%m%d) \
    play-gui/FreeCAD.js play-gui/FreeCAD.wasm play-gui/FreeCAD.data \
    --title "build $(date +%Y-%m-%d)" --notes "engine build"

# 3. Ship it: push the ovhcloud branch -> the box's self-hosted runner deploys + health-checks
git push origin <your-branch>:ovhcloud
#    (or Actions -> "deploy-ovh (freecad.virtastic.app)" -> Run workflow)
```

## Box prerequisites (already satisfied — shared with openmw/ja2)
Self-hosted runner (`self-hosted, ovh, virtastic`), the `edge-caddy` container importing
`/opt/edge/sites/*.caddy`, the external `nostalgia` network, and `/opt/edge/certs/virtastic.{crt,key}`.
Cloudflare DNS `freecad.virtastic.app` → the box (proxied, Full strict). No new box setup needed;
the workflow drops in the vhost + compose and restarts the edge.

## Verify
```bash
curl -sI https://freecad.virtastic.app/ | grep -i cross-origin
# COOP=same-origin AND COEP=require-corp, else the app boots to a blank page.
```
