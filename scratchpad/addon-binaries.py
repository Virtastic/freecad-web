# SPDX-License-Identifier: LGPL-2.1-or-later
"""Which add-ons in the FreeCAD catalogue shell out, and to what?

Under emscripten there is no subprocess. fcweb_git answers `git`; fcweb_wheels answers
`pip`; OpenSCAD is a documented gap. This script reads every add-on's .py files from
GitHub (the catalogue's .gitmodules) and reports the binaries named in
subprocess.* / os.system / shutil.which calls, so the list of what still needs a shim is
measured rather than guessed. Read-only; needs a GH token in GH_TOKEN for rate limits.

    python scratchpad/addon-binaries.py            # full catalogue, ~10 min
    python scratchpad/addon-binaries.py --limit 20 # first 20
Writes scratchpad/_addon-binaries.json and prints a summary table.
"""
import base64, json, os, re, sys, time, urllib.request, urllib.parse

TOKEN = os.environ.get("GH_TOKEN") or os.popen("gh auth token 2>nul").read().strip()
H = {"User-Agent": "freecad-web addon-binaries", "Accept": "application/vnd.github+json"}
if TOKEN:
    H["Authorization"] = "Bearer " + TOKEN
LIMIT = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None

def get(url, raw=False):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=60) as r:
                return r.read() if raw else json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                time.sleep(10 * (attempt + 1)); continue
            if e.code == 404:
                return None
            raise
    return None

mods = get("https://raw.githubusercontent.com/FreeCAD/FreeCAD-addons/master/.gitmodules", raw=True).decode()
repos = re.findall(r"url = (https://github.com/[^/\s]+/[^/\s]+?)(?:\.git)?\s", mods)
if LIMIT:
    repos = repos[:LIMIT]

CALL = re.compile(r"(subprocess\.(?:run|call|check_output|check_call|Popen)|os\.system|os\.popen|shutil\.which)\s*\(\s*(\[?)\s*([^\n,\]]*)")
STR = re.compile(r"""["']([A-Za-z0-9_.+-]+)["']""")
out = os.path.join(os.path.dirname(__file__), "_addon-binaries.json")
report = json.load(open(out)) if os.path.exists(out) else {}
for i, url in enumerate(repos):
    owner_repo = url.split("github.com/")[1]
    if owner_repo in report and "error" not in report[owner_repo]:
        continue
    tree = get("https://api.github.com/repos/%s/git/trees/HEAD?recursive=1" % owner_repo)
    if not tree or "tree" not in tree:
        report[owner_repo] = {"error": "no tree"}; continue
    pys = [t["path"] for t in tree["tree"] if t["path"].endswith(".py") and "test" not in t["path"].lower()]
    hits = {}
    for path in pys:
        blob = get("https://raw.githubusercontent.com/%s/HEAD/%s" % (owner_repo, urllib.parse.quote(path)), raw=True)
        if not blob:
            continue
        src = blob.decode("utf-8", "replace")
        for m in CALL.finditer(src):
            first = m.group(3)
            names = STR.findall(first)
            name = names[0] if names else (first.strip()[:40] or "?")
            hits.setdefault(name, set()).add(path)
    report[owner_repo] = {k: sorted(v) for k, v in hits.items()}
    json.dump(report, open(out, "w"), indent=1, sort_keys=True)
    print("%3d/%d %-45s %s" % (i + 1, len(repos), owner_repo, ", ".join(sorted(hits)) if hits else "-"), flush=True)

by_bin = {}
for repo, hits in report.items():
    for b in hits:
        if b != "error":
            by_bin.setdefault(b, []).append(repo)
print("\nbinaries named, by how many add-ons:")
for b, rs in sorted(by_bin.items(), key=lambda kv: -len(kv[1])):
    print("  %-30s %2d  %s" % (b, len(rs), ", ".join(rs[:4]) + (" ..." if len(rs) > 4 else "")))
print("\nwritten", out)
