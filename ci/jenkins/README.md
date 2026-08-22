# freecad-web test pipeline (Jenkins → build server → test app server)

## Jenkins job (live)

**FreeCAD-Web-Test** on the builder's Jenkins (`http://192.168.1.130:8080`) is a *Pipeline script
from SCM* job: every build clones latest `main` from `github.com/Virtastic/freecad-web.git`
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
- The public URL (`freecad.dev.virtastic.app`) additionally needs DNS + the ingress route; until then
  the smoke stage checks the container directly on `192.168.1.131:8084`.
