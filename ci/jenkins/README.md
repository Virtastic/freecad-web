# freecad-web test pipeline (Jenkins → build server → test app server)

## Jenkins job (live)

**FreeCAD-Web-Test** on the builder's Jenkins (`http://192.168.1.130:8080`) is a *Pipeline script
from SCM* job: every build clones latest **`dev`** from `github.com/Virtastic/freecad-web.git`
(credential `github-virtastic`) and runs this repo's `Jenkinsfile` — Fetch release artifacts → GL-patch
+ build image → Deploy to `testapp@192.168.1.131:8084` → Smoke. Click **Build Now**; no manual sync.

## Why this differs from the game ports

freecad-web does **not** compile in CI. The WASM toolchain build (boost + cpython + gmsh + calculix +
FreeCAD itself) is a multi-hour, multi-gigabyte job that runs out-of-band and publishes
`FreeCAD.js/.wasm/.data` (+ `gmsh`, `ccx`) as assets on a **GitHub Release**. The pipeline fetches the
latest release's artifacts, applies the GL patch table (`tools/patch-freecad-js.py` — normally a
no-op because the release asset is already patched), and packages them with `infra/Dockerfile`
(nginx + the site + the COOP/COEP contract). This mirrors `.github/workflows/deploy-ovh.yml`, the
production path — never touched here.

## Servers / ports

| Role         | host                      | what it is                                   |
|--------------|---------------------------|----------------------------------------------|
| Build server | `192.168.1.130`           | Jenkins (Docker container) + Docker.         |
| Test app srv | `testapp@192.168.1.131`   | Runs `freecad-test` (nginx) on `:8084`.      |

Ports across the set: ja2 = 8081, jk2 = 8082, jka = 8083, **freecad = 8084**.

## Flow (manual, from a laptop)

```bash
GH_TOKEN=<read-token> ci/jenkins/fetch-artifacts.sh     # download latest release artifacts -> play-gui/
ci/jenkins/build-image.sh                               # GL-patch + docker build freecad:test
ci/jenkins/deploy-test.sh                               # docker save | ssh test docker load; run :8084
ci/jenkins/smoke-test.sh http://192.168.1.131:8084      # (or https://freecad.dev.virtastic.app)
```

## Notes

- The Jenkins container needs `python3` (the fetch's JSON parse + the GL patch). Installed there once;
  if the container is ever recreated, `apt-get install -y python3` inside it again — or bake it into
  the Jenkins image.
- The image is large (~785 MB — the engine and the 341 MB preload FS are baked in). `deploy-test.sh`
  ships it over the LAN with `docker save | ssh docker load`.
- `freecad.dev.virtastic.app` is **live** (DEV-ORIGIN-IP-REDACTED, openresty, COOP/COEP set) and is what the
  smoke stage checks. It falls back to `192.168.1.131:8084` only if the public origin is unreachable.
- The job tracked `*/main` until 2026-08-26 and now tracks `*/dev`. `main` had been stale for weeks,
  so the job was rebuilding and redeploying code hundreds of commits behind. Changing the branch is
  a `config.xml` edit plus a container restart; the previous config is kept as
  `config.xml.bak-<timestamp>` beside it.
- **The smoke test now looks inside the payload**, not just at the wrapper. On 2026-08-26 both this
  origin and production were serving a build whose preload held the Python standard library and
  nothing else -- numpy, matplotlib, PIL and ifcopenshell all absent, FEM and the Addon Manager and
  Draft all dead -- while every header, MIME type and asset returned exactly what this file used to
  check for. The `payload carries its Python packages` line is what catches that.
