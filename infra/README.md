<!-- SPDX-License-Identifier: LGPL-2.1-or-later -->
# freecad-wasm deploy (freecad.virtastic.app)

Same pattern as `openmw-wasm`: **local build → GitHub Release (artifacts) → GitHub Actions
builds a container → GHCR → the shared box auto-pulls (Watchtower) and Traefik routes the
domain to it.** The container serves its own COOP/COEP headers (mandatory for the Qt
multi-thread wasm; without SharedArrayBuffer it will not boot).

## One release cut (per engine rebuild)

```bash
# 1. Build locally (produces play-gui/FreeCAD.{js,wasm,data})
FC_SKIP_CONFIGURE=1 bash build-browser-gui.sh

# 2. Publish the big artifacts as a Release (they're gitignored — CI pulls them from here)
gh release create build-$(date +%Y%m%d) \
    play-gui/FreeCAD.js play-gui/FreeCAD.wasm play-gui/FreeCAD.data \
    --title "build $(date +%Y-%m-%d)" --notes "engine build"
```

Publishing the release triggers `.github/workflows/deploy-freecad.yml`, which downloads the
artifacts, builds `infra/Dockerfile`, and pushes `ghcr.io/virtastic/freecad-wasm:latest`
(+ a `sha-` tag). You can also run it manually: **Actions → build-freecad-image → Run workflow**.

## Shared box (one-time, manual — you run this; not touched by CI)

The box already runs Traefik on an external `proxy` network (see
`openmw-wasm/infra/SHARED-BOX-SETUP.md`). Add the freecad service:

```bash
# on ORIGIN-IP-REDACTED
mkdir -p ~/stacks/freecad && cd ~/stacks/freecad
curl -fsSLO https://raw.githubusercontent.com/Virtastic/freecad-wasm/main/infra/docker-compose.yml
docker compose pull && docker compose up -d
```

Point Cloudflare `freecad.virtastic.app` → the box IP (proxied), TLS **Full (strict)**.

## Verify

```bash
curl -sI https://freecad.virtastic.app/ | grep -i cross-origin
# must show COOP=same-origin AND COEP=require-corp, or the app boots to a blank page.
```

## What's in git vs. shipped in the Release
- **git**: `play-gui/freecad-gui.html`, `play-gui/qtloader.js`, all of `infra/`
- **Release artifacts** (gitignored, ~456 MB): `FreeCAD.js`, `FreeCAD.wasm`, `FreeCAD.data`
- **never shipped**: `FreeCAD.wasm.debug` (281 MB, debug symbols only)
