# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
#
# freecad-web one-command install for Windows. Docker Desktop is the only thing you need.
#
#   .\setup.ps1              pull the prebuilt image (fast), falling back to a local build
#   .\setup.ps1 -Build       always build locally from the release artifacts (~445 MB)
#   .\setup.ps1 -Port 9000   serve on a different port
#
# Written for Windows PowerShell 5.1, which is what ships in the box: no ternary, no
# null-coalescing, no '&&'. Two 5.1 traps are load-bearing below and are commented where
# they bite -- -UseBasicParsing on every web call, and -Method Head on the asset probes.

[CmdletBinding()]
param(
    [switch] $Build,
    [switch] $Pull,
    [int]    $Port    = $(if ($env:FCWEB_PORT) { $env:FCWEB_PORT } else { 8080 }),
    [string] $Tag     = $(if ($env:FCWEB_RELEASE) { $env:FCWEB_RELEASE } else { 'v1.0.0' }),
    [string] $Repo    = $(if ($env:FCWEB_REPO) { $env:FCWEB_REPO } else { 'Virtastic/freecad-web' }),
    [string] $Image   = $(if ($env:FCWEB_IMAGE) { $env:FCWEB_IMAGE } else { 'ghcr.io/virtastic/freecad-web:1.0.0' })
)

# NOT 'Stop': under Stop, PowerShell 5.1 turns anything a native .exe writes to stderr
# into a terminating error, even when the command succeeded. `docker pull` against a
# package that is not public yet writes to stderr and returns non-zero -- precisely the
# case this script recovers from by building locally, and under 'Stop' it died instead.
# Every native call below checks $LASTEXITCODE explicitly; cmdlets whose failure must be
# caught carry -ErrorAction Stop at the call site.
$ErrorActionPreference = 'Continue'

# Must be captured at script scope: inside a function $MyInvocation describes the
# function, so .MyCommand.Path is null there and Join-Path throws.
$ScriptDir = $PSScriptRoot
if (-not $ScriptDir) { $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$DockerUrl = 'https://docs.docker.com/get-started/get-docker/'
$Assets = @('FreeCAD.js','FreeCAD.wasm','FreeCAD.data','gmsh.js','gmsh.wasm','ccx.js','ccx.wasm')

function Step($m) { Write-Host ''; Write-Host "==> $m" -ForegroundColor Cyan }
function Say($m)  { Write-Host $m }
function Warn($m) { Write-Host "WARNING: $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host ''; Write-Host "FATAL: $m" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------------------------------
# 1. Docker preflight. Runs before anything is downloaded.
# ---------------------------------------------------------------------------------------
function Invoke-Preflight {
    Step 'Checking Docker'

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Die @"
Docker is not installed (no 'docker' on PATH).
       freecad-web runs entirely inside a container -- Docker is all you need.
       Install Docker Desktop: $DockerUrl
"@
    }

    # 'docker info', not 'docker --version': the CLI answers --version by itself, so it
    # succeeds while Docker Desktop is not running. Only info is a real daemon round trip.
    $info = & docker info --format '{{.ServerVersion}}|{{.OSType}}|{{.DockerRootDir}}' 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $info) {
        Die @"
Docker is installed but the daemon is not reachable.
       Start Docker Desktop, wait until it says 'Engine running', then re-run this script.
"@
    }

    $parts   = ([string]$info).Split('|')
    $version = $parts[0]
    $ostype  = $parts[1]

    if ($version -match '^\d+') {
        $major = [int]($version.Split('.')[0])
        if ($major -lt 20) {
            Die "Docker engine 20.10 or newer is required (found $version).`n       Upgrade: https://docs.docker.com/engine/install/"
        }
    } else {
        Warn "unrecognised Docker version string '$version' -- continuing anyway."
    }

    & docker compose version --short 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
            Die @"
You have the legacy 'docker-compose' (v1). This needs Compose V2, invoked as
       'docker compose' -- a space, not a hyphen. Compose v1 is end-of-life.
       Install: https://docs.docker.com/compose/install/
"@
        }
        Die "The Docker Compose V2 plugin is missing ('docker compose' not recognised).`n       Install: https://docs.docker.com/compose/install/"
    }

    if ($ostype -ne 'linux') {
        Die @"
Docker Desktop is running in Windows container mode; this image is Linux-based.
       Right-click the Docker whale in the system tray -> 'Switch to Linux containers...',
       wait for the engine to restart, then re-run this script.
"@
    }

    # Warning only. DockerRootDir points inside the WSL2 VM and does not exist on the
    # host, so this measures the drive holding the distro's vhdx -- a proxy, not the
    # truth. A false FATAL would block a capable machine; a false pass costs a build that
    # fails with this number already on screen.
    $freeGiB = $null
    try {
        $drive = (Get-Item $env:LOCALAPPDATA).PSDrive
        $freeGiB = [math]::Floor($drive.Free / 1GB)
    } catch { }
    if ($null -ne $freeGiB -and $freeGiB -lt 10) {
        Warn @"
only $freeGiB GiB free on $($drive.Name):.
         The image is ~1.1 GB and a local build needs roughly 5 GiB of working space.
         If you hit 'no space left on device', try: docker system prune -a
"@
    }

    $compose = & docker compose version --short
    Say "  Docker $version, compose $compose, $ostype containers$(if ($freeGiB) { ", $freeGiB GiB free" })"
}

# ---------------------------------------------------------------------------------------
# 2. Source tree: use the checkout this script sits in, else fetch the tag tarball (~3.4 MB).
# ---------------------------------------------------------------------------------------
function Resolve-Tree {
    $here = $ScriptDir
    if ($here -and (Test-Path (Join-Path $here 'infra\Dockerfile')) -and
        (Test-Path (Join-Path $here 'docker-compose.yml'))) {
        Step "Using the checkout at $here"
        return $here
    }

    $tree = Join-Path (Get-Location) "freecad-web-$Tag"
    if (Test-Path (Join-Path $tree 'infra\Dockerfile')) {
        Step "Using the previously downloaded source at $tree"
        return $tree
    }
    Step "Fetching the freecad-web $Tag source (~3.4 MB)"
    $zip = Join-Path $env:TEMP "freecad-web-$Tag.zip"
    Get-Remote "https://github.com/$Repo/archive/refs/tags/$Tag.zip" $zip
    $stage = Join-Path $env:TEMP "fcweb-extract-$PID"
    if (Test-Path $stage) { Remove-Item -Recurse -Force $stage }
    Expand-Archive -Path $zip -DestinationPath $stage -Force -ErrorAction Stop
    # The GitHub archive wraps everything in a single top-level directory whose name
    # depends on how the tag is spelled; take whatever it is rather than guessing.
    $inner = Get-ChildItem $stage -Directory | Select-Object -First 1
    if (-not $inner) { Die "the downloaded archive was empty" }
    if (Test-Path $tree) { Remove-Item -Recurse -Force $tree }
    Move-Item $inner.FullName $tree -ErrorAction Stop
    Remove-Item -Recurse -Force $stage, $zip -ErrorAction SilentlyContinue
    if (-not (Test-Path (Join-Path $tree 'infra\Dockerfile'))) {
        Die "the downloaded archive is missing infra/Dockerfile"
    }
    return $tree
}

# curl.exe ships with Windows 10 1803+ and streams to disk; Invoke-WebRequest buffers the
# whole response in memory, which is not survivable for a 237 MB file on 5.1.
function Get-Remote($url, $dest) {
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        & curl.exe -fL --retry 3 -C - -# -o $dest $url
        if ($LASTEXITCODE -ne 0) { throw "download failed: $url" }
    } else {
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing -ErrorAction Stop
    }
}

# ---------------------------------------------------------------------------------------
# 3. Engine artifacts for a local build.
# ---------------------------------------------------------------------------------------
function Get-Assets($tree) {
    Step 'Downloading the engine artifacts (~445 MB) -- this is the slow part'
    $dir = Join-Path $tree 'play-gui'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    foreach ($name in $Assets) {
        $out = Join-Path $dir $name
        $url = "https://github.com/$Repo/releases/download/$Tag/$name"

        # "Exists and is non-empty" is not "is the whole file". A download interrupted at
        # 90% leaves something that passes a naive check and produces an image broken in a
        # way nothing downstream notices. Ask the server for the real size and compare;
        # curl's -C - then resumes the remainder rather than starting over.
        if ((Test-Path $out) -and ((Get-Item $out).Length -gt 0)) {
            $want = $null
            try {
                $head = Invoke-WebRequest -Uri $url -Method Head -UseBasicParsing -TimeoutSec 30 -ErrorAction Stop
                $want = [int64](Get-Header $head 'Content-Length')
            } catch { }
            if (-not $want) { Say "  have    $name (could not confirm size)"; continue }
            $have = (Get-Item $out).Length
            if ($have -eq $want) { Say "  have    $name"; continue }
            Say "  resume  $name ($have of $want bytes)"
        } else {
            Say "  fetch   $name"
        }
        try {
            Get-Remote $url $out
        } catch {
            # Private-repo fallback; also how a maintainer tests before the repo is public.
            if (Get-Command gh -ErrorAction SilentlyContinue) {
                Say '  (public download failed; retrying via authenticated gh)'
                & gh release download $Tag -R $Repo -p $name -D $dir --clobber
                if ($LASTEXITCODE -ne 0) { Die "could not download $name" }
            } else {
                Remove-Item $out -ErrorAction SilentlyContinue
                Die "could not download $name.`n       If the release is not public yet, install the GitHub CLI and run 'gh auth login'."
            }
        }
    }
}

# ---------------------------------------------------------------------------------------
# 4. Start. --wait blocks on the image's own HEALTHCHECK, so there is no polling loop here.
# ---------------------------------------------------------------------------------------
function Start-Stack($tree, $extra) {
    Push-Location $tree
    $env:FCWEB_PORT = "$Port"
    $env:FCWEB_IMAGE = $Image
    & docker compose up -d --wait --wait-timeout 240 $extra
    $rc = $LASTEXITCODE
    if ($rc -ne 0) {
        Say ''
        Say 'The container did not come up healthy. Last 40 log lines:'
        & docker compose logs --tail 40
        Pop-Location
        Die 'startup failed.'
    }
    Pop-Location
}

# ---------------------------------------------------------------------------------------
# 5. Verify. COOP/COEP are not cosmetic: without cross-origin isolation SharedArrayBuffer
#    is unavailable and the engine never boots, which looks just like a broken install.
# ---------------------------------------------------------------------------------------
function Get-Header($response, $name) {
    $v = $response.Headers[$name]
    if ($v -is [array]) { return $v[0] }
    return $v
}

function Test-Deployment {
    Step 'Verifying'
    $base = "http://localhost:$Port"
    $ok = $true

    # -UseBasicParsing is mandatory on 5.1: without it this goes through the IE parsing
    # engine and throws outright on a machine where IE was never initialised.
    try {
        $r = Invoke-WebRequest -Uri "$base/" -UseBasicParsing -TimeoutSec 30 -ErrorAction Stop
    } catch {
        Die "no HTTP response from $base/ -- $($_.Exception.Message)"
    }

    if ($r.StatusCode -ne 200) { $ok = $false; Say "  FAIL  / returned $($r.StatusCode)" }
    if ((Get-Header $r 'Cross-Origin-Opener-Policy') -ne 'same-origin') {
        $ok = $false; Say '  FAIL  COOP header missing -- the engine cannot start without cross-origin isolation'
    }
    if ((Get-Header $r 'Cross-Origin-Embedder-Policy') -ne 'require-corp') {
        $ok = $false; Say '  FAIL  COEP header missing -- the engine cannot start without cross-origin isolation'
    }
    if ($r.Content -notmatch 'freecad') { $ok = $false; Say '  FAIL  / did not serve freecad-gui.html' }

    foreach ($a in @('FreeCAD.js','FreeCAD.wasm','FreeCAD.data','legal.html','LICENSE')) {
        # HEAD, not GET: FreeCAD.data is 237 MB and Invoke-WebRequest buffers the body.
        try {
            $h = Invoke-WebRequest -Uri "$base/$a" -Method Head -UseBasicParsing -TimeoutSec 60 -ErrorAction Stop
            if ($h.StatusCode -ne 200) { $ok = $false; Say "  FAIL  $a returned $($h.StatusCode)" }
        } catch {
            $ok = $false; Say "  FAIL  $a is not being served"
        }
    }

    if (-not $ok) { Die 'the server is up but is not serving correctly (see failures above).' }
    Say '  200 OK, COOP + COEP present, engine assets served'
}

# ---------------------------------------------------------------------------------------

Invoke-Preflight
$tree = Resolve-Tree
$builtLocally = $false

if ($Build) {
    Get-Assets $tree
    Step 'Building the image locally (a few minutes -- it compresses 340 MB of engine data)'
    Start-Stack $tree '--build'
    $builtLocally = $true
} else {
    Step "Pulling $Image"
    & docker pull $Image
    if ($LASTEXITCODE -eq 0) {
        Start-Stack $tree '--no-build'
    } elseif ($Pull) {
        Die "could not pull $Image and -Pull was requested."
    } else {
        Warn "could not pull $Image -- falling back to building it locally.`n         (If the package is not public yet, this is expected.)"
        Get-Assets $tree
        Step 'Building the image locally (a few minutes)'
        Start-Stack $tree '--build'
        $builtLocally = $true
    }
}

Test-Deployment

Write-Host ''
Write-Host "  freecad-web is running:   http://localhost:$Port/" -ForegroundColor Green
Write-Host ''
Write-Host '  Open it in Chrome or Edge 137+ (it needs JSPI, SharedArrayBuffer and WebGL2).'
Write-Host "  Use localhost, not this machine's LAN IP -- the engine only starts on a secure context."
Write-Host ''
Write-Host "  Stop it:     cd $tree; docker compose down"
Write-Host "  Start again: cd $tree; docker compose up -d"
if ($builtLocally) { Write-Host "  Built locally from release $Tag." }
exit 0
