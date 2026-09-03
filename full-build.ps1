# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
#
# Clone freecad-web and build the deployable container from that clone, end to end.
# Takes roughly 10-15 minutes, almost all of it downloading ~445 MB of engine artifacts
# and compressing them into the image. You need git and Docker Desktop; nothing else.
#
#   .\full-build.ps1                     clone into .\freecad-web and build
#   .\full-build.ps1 -Port 9000          ... on a different port
#   .\full-build.ps1 -Dir C:\opt\fcweb   ... into a different directory
#
# WHAT THIS IS NOT: it does not compile the WebAssembly engine from source. That is a
# separate ~7-9 hour job needing ~100 GB of disk and 16+ GB of RAM, spread across five CI
# lanes (Qt, OCCT, VTK, CPython, PySide, FreeCAD itself), and it is documented in
# BUILD-WEH.md rather than scripted -- three pieces of it are not yet automated at all.
# This script builds the container that ships the already-compiled engine.

[CmdletBinding()]
param(
    [string] $Dir  = '',
    # What to check out, which is not always what to download.
    [string] $Ref  = '',
    [string] $Tag  = $(if ($env:FCWEB_RELEASE) { $env:FCWEB_RELEASE } else { 'v1.0.0' }),
    [string] $Repo = $(if ($env:FCWEB_REPO) { $env:FCWEB_REPO } else { 'Virtastic/freecad-web' }),
    [int]    $Port = $(if ($env:FCWEB_PORT) { $env:FCWEB_PORT } else { 8080 })
)

# NOT 'Stop': PowerShell 5.1 promotes anything a native .exe writes to stderr into a
# terminating error. `git clone` writes its progress to stderr on a SUCCESSFUL clone,
# so 'Stop' fails the script precisely when the clone worked. Exit codes are checked
# explicitly below instead.
$ErrorActionPreference = 'Continue'
function Die($m) { Write-Host ''; Write-Host "FATAL: $m" -ForegroundColor Red; exit 1 }

if (-not $Dir) { $Dir = Join-Path (Get-Location) 'freecad-web' }
if (-not $Ref) { $Ref = $Tag }

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Die @"
git is not installed.
       Install it from https://git-scm.com/downloads, or use setup.ps1 instead --
       it needs only Docker and downloads a source archive rather than cloning.
"@
}

if (Test-Path (Join-Path $Dir '.git')) {
    Write-Host ''; Write-Host "==> Reusing the existing clone at $Dir" -ForegroundColor Cyan
    & git -C $Dir fetch --depth 1 origin $Ref 2>$null
    & git -C $Dir checkout -q FETCH_HEAD
    if ($LASTEXITCODE -ne 0) { & git -C $Dir checkout -q $Ref }
    if ($LASTEXITCODE -ne 0) { Die "could not check out $Ref in $Dir" }
} else {
    Write-Host ''; Write-Host "==> Cloning $Repo at $Ref into $Dir" -ForegroundColor Cyan
    & git clone --depth 1 --branch $Ref "https://github.com/$Repo.git" $Dir
    if ($LASTEXITCODE -ne 0) { Die "clone failed. Check that $Ref exists and that you have network access." }
}

if (-not (Test-Path (Join-Path $Dir 'setup.ps1'))) {
    Die "$Ref does not contain setup.ps1. Use -Ref with a newer branch or tag."
}

# -Build, not the default pull: the point of this script is to build from the clone.
& (Join-Path $Dir 'setup.ps1') -Build -Tag $Tag -Port $Port
exit $LASTEXITCODE
