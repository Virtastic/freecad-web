# SPDX-License-Identifier: LGPL-2.1-or-later
"""Does fcweb_git answer the History Workbench's git commands exactly as real git does?

Builds the same repository twice -- once with real git, once through fcweb_git.run --
and diffs stdout/returncode of every command the workbench's GitPort adapter issues
(eblanshey/HistoryWorkbench, git_port_adapter.py, read 2026-09-21). Commit ids differ
(different clocks); everything else must be identical.

    PYTHONPATH=<dir with dulwich> python scratchpad/gitshim-check.py
"""
import os, re, shutil, subprocess, sys, tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "play-gui", "am"))
import fcweb_git  # noqa: E402

REAL = shutil.which("git")
if not REAL:
    raise SystemExit("real git not on PATH; nothing to compare against")

ENV = dict(os.environ, GIT_AUTHOR_DATE="2026-09-21T12:00:00+0000", GIT_COMMITTER_DATE="2026-09-21T12:00:00+0000",
           GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull, HOME=tempfile.gettempdir())


def real(args, cwd, binary=False):
    cp = subprocess.run([REAL, "-c", "core.autocrlf=false", "-c", "core.quotepath=off", "-c", "init.defaultBranch=master", *args],
                        cwd=cwd, capture_output=True, env=ENV)
    out = cp.stdout if binary else cp.stdout.decode("utf-8", "replace")
    return cp.returncode, out


def shim(args, cwd, binary=False):
    code, out, err = fcweb_git.run(["git", *args], cwd=cwd, env=ENV)
    if binary and isinstance(out, str):
        out = out.encode()
    if not binary and isinstance(out, bytes):
        out = out.decode("utf-8", "replace")
    return code, out


SHA = re.compile(r"\b[0-9a-f]{40}\b")
SHORT = re.compile(r"\[master(?: \(root-commit\))? [0-9a-f]{7}\]")
fails = 0


def check(name, args, binary=False, mask_sha=False, code_only=False, first_line=False):
    global fails
    r = real(args, dr, binary)
    s = shim(args, ds, binary)
    ro, so = r[1], s[1]
    if mask_sha and not binary:
        ro, so = SHA.sub("<sha>", ro), SHA.sub("<sha>", so)
        ro, so = SHORT.sub("[master <short>]", ro), SHORT.sub("[master <short>]", so)
    if ro and not binary:
        ro = ro.replace(os.path.realpath(dr).replace(os.sep, "/"), "<root>")
        so = so.replace(os.path.realpath(ds).replace(os.sep, "/"), "<root>")
    if first_line and not binary:
        ro, so = ro.split("\n", 1)[0], so.split("\n", 1)[0]
    ok = r[0] == s[0] and (code_only or ro == so)
    print(("  ok   " if ok else "  FAIL ") + name)
    if not ok:
        fails += 1
        print("       real: rc=%s %r" % (r[0], ro if not binary else ro[:40]))
        print("       shim: rc=%s %r" % (s[0], so if not binary else so[:40]))


def write(root, rel, data):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)


dr, ds = tempfile.mkdtemp(prefix="gitreal-"), tempfile.mkdtemp(prefix="gitshim-")
LOG = ["log", "-n20", "--format=%H%x00%B%x00%an%x00%aI%x00"]
try:
    check("init", ["init"], code_only=True)
    check("rev-parse --show-toplevel", ["rev-parse", "--show-toplevel"])
    check("rev-parse --verify HEAD (empty)", ["rev-parse", "--verify", "HEAD"], code_only=True)
    check("log (empty repo) rc", LOG, code_only=True)
    for root in (dr, ds):
        write(root, "a.FCStd", b"one")
        write(root, "sub/b.FCStd", b"two")
        write(root, "notes.txt", b"n")
    check("status untracked", ["status", "--porcelain", "-z"])
    check("add -v", ["add", "-v", "--", "a.FCStd", "sub/b.FCStd"])
    check("status staged", ["status", "--porcelain", "-z"])
    check("commit without identity rc", ["commit", "-m", "x"], code_only=True)
    for args in (["config", "--local", "user.name", "Tester"], ["config", "--local", "user.email", "t@example.com"]):
        check(" ".join(args), args)
    check("config --get user.name", ["config", "--get", "user.name"])
    check("config --get missing", ["config", "--get", "user.nothing"])
    check("commit first (first line)", ["commit", "-m", "first\n\nbody line  "], mask_sha=True, first_line=True)
    check("log", LOG, mask_sha=True)
    check("ls-files -z", ["ls-files", "-z"])
    check("ls-tree", ["ls-tree", "-r", "-z", "--name-only", "HEAD"])
    check("show HEAD:path", ["show", "HEAD:sub/b.FCStd"], binary=True)
    check("show :path", ["show", ":a.FCStd"], binary=True)
    check("show missing rc", ["show", "HEAD:nope"], code_only=True)
    check("cat-file -e present", ["cat-file", "-e", "HEAD:a.FCStd"])
    check("cat-file -e missing", ["cat-file", "-e", "HEAD:nope"], code_only=True)
    check("diff-tree root", ["diff-tree", "--root", "--no-commit-id", "--name-only", "-z", "-r", "HEAD"])
    for root in (dr, ds):
        write(root, "a.FCStd", b"one-changed")
        write(root, "c.FCStd", b"three")
    check("status modified+untracked", ["status", "--porcelain", "-z"])
    check("add modified", ["add", "--", "a.FCStd", "c.FCStd"])
    check("status staged M+A", ["status", "--porcelain", "-z"])
    check("restore --staged", ["restore", "--staged", "--", "a.FCStd"])
    check("status after restore", ["status", "--porcelain", "-z"])
    check("add again", ["add", "--", "a.FCStd"])
    check("commit second (first line)", ["commit", "-m", "second"], mask_sha=True, first_line=True)
    check("diff-tree second", ["diff-tree", "--root", "--no-commit-id", "--name-only", "-z", "-r", "HEAD"])
    check("rev-parse HEAD~1^{commit} rc", ["rev-parse", "--verify", "HEAD~1^{commit}"], code_only=True)
    check("log --skip", ["log", "--skip=1", "-n1", "--format=%H%x00%B%x00%an%x00%aI%x00"], mask_sha=True)
    check("rm --cached", ["rm", "--cached", "--", "sub/b.FCStd"])
    check("status after rm --cached", ["status", "--porcelain", "-z"])
    check("ls-files after rm", ["ls-files", "-z"])
    for root in (dr, ds):
        os.remove(os.path.join(root, "c.FCStd"))
    check("status deleted in worktree", ["status", "--porcelain", "-z"])
    check("unknown command rc", ["frobnicate"], code_only=True)
finally:
    shutil.rmtree(dr, ignore_errors=True)
    shutil.rmtree(ds, ignore_errors=True)

print("\n%d FAILED" % fails if fails else "\nall identical to real git")
sys.exit(1 if fails else 0)
