<!-- SPDX-License-Identifier: LGPL-2.1-or-later -->
<!-- Copyright (c) Virtastic -->

# Running freecad-web yourself

FreeCAD compiled to WebAssembly, served by nginx in a container. Docker is the only
requirement — no Python, no Node, no build tools, no compiler.

If you just want to use it and not host it, the hosted instance is
<https://freecad.virtastic.app> and needs nothing at all.

---

## Install

```bash
curl -fsSLO https://github.com/Virtastic/freecad-web/releases/download/v1.0.0/setup.sh
sh setup.sh
```

```powershell
# Windows PowerShell
irm https://github.com/Virtastic/freecad-web/releases/download/v1.0.0/setup.ps1 -OutFile setup.ps1
.\setup.ps1
```

Then open **<http://localhost:8080/>**.

The script does five things, in order, and stops at the first that fails: checks your
Docker, gets the image, starts the container, waits for it to report healthy, and then
verifies the running site actually serves correctly. It does not tell you it worked until
it has checked.

### Three ways in

| | What it does | Time |
|---|---|---|
| `sh setup.sh` | Pulls the prebuilt image from GHCR. If that is unavailable it falls back to building locally, and says so. | ~3 min |
| `sh setup.sh --build` | Downloads the seven engine artifacts (~445 MB) from the release and builds the image on your machine. | ~15 min |
| `sh full-build.sh` | Clones the repository at the release tag, then does the `--build` path from that clone. | ~15 min |

All three produce the same running container. Use `--build` if you want to build what you
can read, or if you are on an arm64 machine and would rather have a native image than an
emulated one.

None of these compiles the WebAssembly engine from source. That is a separate ~7–9 hour
job needing ~100 GB of disk and 16+ GB of RAM, and it is documented in
[BUILD-WEH.md](BUILD-WEH.md).

### Options

| Flag | Environment variable | Default |
|---|---|---|
| `--port 9000` | `FCWEB_PORT` | `8080` |
| `--tag v1.0.0` | `FCWEB_RELEASE` | `v1.0.0` |
| `--build` / `--pull` | — | pull, with fallback to build |

---

## Requirements

- **Docker Engine 20.10+** with the Compose V2 plugin (`docker compose`, a space rather
  than a hyphen). Docker Desktop on Windows and macOS includes both.
- **~5 GiB free** in Docker's storage for a local build; the finished image is ~1.1 GB.
- **Chrome or Edge 137+.** Firefox and Safari lack JSPI and are refused at the boot screen
  having downloaded nothing. This is a browser limitation, not an installation problem.

### Use `localhost`, not the machine's LAN IP

The engine needs `SharedArrayBuffer`, which needs cross-origin isolation, which needs a
secure context. Plain HTTP is a secure context **only on loopback**. So
<http://localhost:8080/> and <http://127.0.0.1:8080/> work, and `http://192.168.x.x:8080/`
loads the page and then never boots the engine.

To serve it to other machines, put it behind a reverse proxy with real TLS. Pass the
`Cross-Origin-Opener-Policy` and `Cross-Origin-Embedder-Policy` headers through unchanged
and do not add your own — duplicates break isolation just as effectively as absence.

---

## Troubleshooting

**"Docker is not installed"** — install it from
<https://docs.docker.com/get-started/get-docker/>. Docker Desktop for Windows/macOS,
Docker Engine plus the compose plugin for Linux.

**"Docker is installed but the daemon is not reachable"** — the command-line tool exists
but nothing is listening. On Windows/macOS, start Docker Desktop and wait for "Engine
running". On Linux, `sudo systemctl start docker`; if it says permission denied, run
`sudo usermod -aG docker "$USER"` and then log out and back in.

**"Docker is in Windows container mode"** — right-click the Docker whale in the system
tray, choose *Switch to Linux containers…*, wait for the engine to restart, re-run.

**"You have the legacy docker-compose (v1)"** — Compose v1 is end-of-life. Install the V2
plugin: <https://docs.docker.com/compose/install/>.

**The pull fails and it builds instead** — expected if the package has not been made
public yet. The local build produces the same thing; it just takes longer.

**Port 8080 is already in use** — `sh setup.sh --port 9000`.

**The page loads but the engine never reaches Ready** — almost always either a
non-loopback URL (see above) or an unsupported browser. Check the browser console for a
`crossOriginIsolated` warning.

**The Addon Manager cannot reach anything** — `infra/nginx.conf` proxies a fixed allowlist
of upstreams through `1.1.1.1` and `8.8.8.8`. On a network that blocks those resolvers the
Addon Manager will not work; the application itself is unaffected.

---

## Managing it

```bash
cd <the directory setup.sh reported>

docker compose down            # stop
docker compose up -d           # start again
docker compose logs -f         # follow the logs
docker compose ps              # is it healthy?
```

### Updating

Re-run the installer with the newer tag:

```bash
sh setup.sh --tag v1.1.0
```

### Uninstalling

```bash
docker compose down
docker image rm ghcr.io/virtastic/freecad-web:1.0.0
```

Nothing is written outside Docker. There is no volume to clean up, no service installed
and no file dropped in a system directory.

Your **documents are not in the container** — they live in your browser's storage, so
removing the container does not delete them, and neither does re-running the installer.
Export anything you care about through *File → Export* first if you are clearing browser
data.

---

## License

LGPL-2.1-or-later, matching FreeCAD. The running application serves its full attribution
at `/legal.html`, linked from the boot screen. Gmsh and CalculiX ship as separate GPL
WebAssembly modules rather than being linked in.
