# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""A `git` for the browser build, so add-ons that shell out to git keep working.

The History Workbench (eblanshey/HistoryWorkbench) drives version control through
``subprocess.run([shutil.which("git"), ...])`` behind a GitPort protocol. There is no git
binary and no subprocess under emscripten, so ``is_git_executable_available()`` was
False and the workbench installed and then did nothing (launch-day report, 2026-09-21).

This module puts a file named ``git`` on PATH (so ``shutil.which`` finds it) and teaches
``subprocess.run`` / ``subprocess.Popen`` that an argv whose first element is that path is
answered in-process by ``run(argv, cwd, env)`` below, which implements the sixteen
sub-commands the workbench uses on top of dulwich, the pure-Python git. Every
output format the adapter parses (``status --porcelain -z``, ``log --format=...`` with
NUL separators, ``ls-files -z``, ``ls-tree -r -z --name-only``, ``diff-tree
--name-only -z``, ``rev-parse``, ``config --get``, ``show``, ``cat-file -e``) is
reproduced byte for byte; scratchpad/gitshim-check.py diffs each one against real git.

Anything not implemented returns exit 129 with git's own "unknown option" wording,
never a Python traceback: the caller expects a CompletedProcess.

Dulwich itself is installed on demand through fcweb_wheels (pure wheel; its urllib3
requirement is only for network transports we never touch) into the persisted vendor
directory, so it is fetched once per browser profile.
"""

import io
import os
import re
import shlex
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

GIT_BIN_DIR = os.path.expanduser("~/.local/bin")
GIT_PATH = os.path.join(GIT_BIN_DIR, "git")
DULWICH_DIST = "dulwich"


# ----------------------------------------------------------------------------- helpers

class GitError(Exception):
    def __init__(self, message, code=128):
        super().__init__(message)
        self.code = code


def _repo(cwd):
    from dulwich.repo import Repo
    from dulwich.errors import NotGitRepository
    try:
        return Repo.discover(cwd)
    except NotGitRepository:
        raise GitError("fatal: not a git repository (or any of the parent directories): .git")


def _rel(repo, cwd, p):
    """A path argument as the repo-relative POSIX path git would use."""
    root = os.path.realpath(repo.path)
    ap = os.path.realpath(os.path.join(cwd, p))
    r = os.path.relpath(ap, root).replace(os.sep, "/")
    if r.startswith(".."):
        raise GitError("fatal: %s: '%s' is outside repository at '%s'" % (p, p, root))
    return "." if r == "." else r


def _head(repo):
    try:
        return repo.head()
    except KeyError:
        return None


def _tz_str(offset_seconds):
    sign = "+" if offset_seconds >= 0 else "-"
    m = abs(offset_seconds) // 60
    return "%s%02d:%02d" % (sign, m // 60, m % 60)


def _iso(ts, tz_off):
    """%aI: strict ISO 8601, and 'Z' for UTC exactly as git prints it."""
    base = datetime.fromtimestamp(ts, timezone(timedelta(seconds=tz_off))).strftime("%Y-%m-%dT%H:%M:%S")
    return base + ("Z" if tz_off == 0 else _tz_str(tz_off))


def _date_from_env(env, key):
    """GIT_AUTHOR_DATE / GIT_COMMITTER_DATE as (timestamp, tz offset seconds), or None."""
    v = (env or {}).get(key) or os.environ.get(key)
    if not v:
        return None
    try:
        v = v.strip()
        if re.fullmatch(r"@?\d+(?: [+-]\d{4})?", v):
            parts = v.lstrip("@").split()
            tz = parts[1] if len(parts) > 1 else "+0000"
        else:
            d = datetime.fromisoformat(v.replace("Z", "+00:00"))
            off = d.utcoffset() or timedelta(0)
            return int(d.timestamp()), int(off.total_seconds())
        off = (int(tz[1:3]) * 3600 + int(tz[3:5]) * 60) * (1 if tz[0] == "+" else -1)
        return int(parts[0]), off
    except Exception:
        return None


def _resolve(repo, ref):
    """Commit id for HEAD, HEAD~N, a sha or a prefix, a branch; None if unknown."""
    from dulwich.objects import Commit
    ref = ref.encode() if isinstance(ref, str) else ref
    m = re.match(rb"^(.*?)(~(\d*))?(\^\{commit\})?$", ref)
    base, tilde = m.group(1), m.group(3)
    steps = int(tilde) if tilde else (1 if m.group(2) else 0)
    cid = None
    if base in (b"HEAD", b""):
        cid = _head(repo)
    elif base.startswith(b"refs/") or (b"refs/heads/" + base) in repo.refs:
        cid = repo.refs.get(base if base.startswith(b"refs/") else b"refs/heads/" + base)
    else:
        try:
            if len(base) == 40:
                cid = base if base in repo.object_store else None
            elif 4 <= len(base) < 40 and re.fullmatch(rb"[0-9a-f]+", base):
                matches = [o for o in repo.object_store if o.startswith(base)]
                cid = matches[0] if len(matches) == 1 else None
        except Exception:
            cid = None
    if cid is None:
        return None
    for _ in range(steps):
        c = repo[cid]
        if not isinstance(c, Commit) or not c.parents:
            return None
        cid = c.parents[0]
    return cid


def _tree_lookup(repo, tree_id, path):
    from dulwich.object_store import tree_lookup_path
    try:
        return tree_lookup_path(repo.object_store.__getitem__, tree_id, path.encode())
    except KeyError:
        return None


def _show_target(repo, target):
    """':path' -> index blob, '<rev>:path' -> tree blob. Returns bytes or raises."""
    if ":" not in target:
        raise GitError("fatal: invalid object name '%s'." % target)
    rev, path = target.split(":", 1)
    if rev == "":
        idx = repo.open_index()
        key = path.encode()
        if key not in idx:
            raise GitError("fatal: path '%s' does not exist in the index" % path)
        return repo[idx[key].sha].data
    cid = _resolve(repo, rev)
    if cid is None:
        raise GitError("fatal: invalid object name '%s'." % rev)
    ent = _tree_lookup(repo, repo[cid].tree, path)
    if ent is None:
        raise GitError("fatal: path '%s' does not exist in '%s'" % (path, rev))
    return repo[ent[1]].data


def _identity(repo):
    from dulwich.config import StackedConfig
    cfg = repo.get_config_stack()
    try:
        name = cfg.get((b"user",), b"name")
        email = cfg.get((b"user",), b"email")
    except KeyError:
        return None
    return b"%s <%s>" % (name, email)


# ------------------------------------------------------------------------- subcommands

def cmd_init(repo_unused, cwd, args):
    from dulwich.repo import Repo
    target = args[0] if args else cwd
    os.makedirs(target, exist_ok=True)
    if os.path.isdir(os.path.join(target, ".git")):
        return 0, "Reinitialized existing Git repository in %s/.git/\n" % os.path.realpath(target), ""
    Repo.init(target)
    return 0, "Initialized empty Git repository in %s/.git/\n" % os.path.realpath(target), ""


def cmd_rev_parse(repo, cwd, args):
    if args == ["--show-toplevel"]:
        return 0, os.path.realpath(repo.path).replace(os.sep, "/") + "\n", ""
    if args and args[0] == "--verify":
        ref = args[1] if len(args) > 1 else "HEAD"
        cid = _resolve(repo, ref)
        if cid is None:
            return 128, "", "fatal: Needed a single revision\n"
        return 0, cid.decode() + "\n", ""
    if len(args) == 1:
        cid = _resolve(repo, args[0])
        if cid is None:
            return 128, args[0] + "\n", "fatal: ambiguous argument '%s': unknown revision or path not in the working tree.\n" % args[0]
        return 0, cid.decode() + "\n", ""
    return 129, "", "error: unknown option `%s'\n" % " ".join(args)


def _status_entries(repo):
    """Porcelain v1 entries as (XY, path) in git's order, from dulwich's status."""
    from dulwich.porcelain import status
    st = status(repo, untracked_files="all")

    def norm(p):
        return (p.decode() if isinstance(p, bytes) else p).replace(os.sep, "/")

    rows = {}
    for kind, key in (("add", "A"), ("modify", "M"), ("delete", "D")):
        for p in st.staged.get(kind, []):
            rows[norm(p)] = [key, " "]
    for p in st.unstaged:
        p = norm(p)
        idx_char = rows.get(p, [" ", " "])[0]
        full = os.path.join(repo.path, p)
        rows[p] = [idx_char, "D" if not os.path.exists(full) else "M"]
    # A path removed from the index but still on disk is BOTH "D " and "??" in git.
    # And git collapses a directory whose every file is untracked to "?? dir/" (the
    # default --untracked-files=normal); the workbench sees exactly that on desktop.
    tracked_paths = {p.decode() for p in repo.open_index()}
    untracked = set()
    for p in st.untracked:
        p = norm(p)
        top = p
        while "/" in top:
            parent = top.rsplit("/", 1)[0]
            if any(t == parent or t.startswith(parent + "/") for t in tracked_paths):
                break
            top = parent
        untracked.add(top if top == p else top + "/")
    tracked = sorted(rows.items())
    return [(xy[0] + xy[1], p) for p, xy in tracked] + [("??", p) for p in sorted(untracked)]


def cmd_status(repo, cwd, args):
    if "--porcelain" not in args:
        return 129, "", "error: only --porcelain is supported\n"
    z = "-z" in args
    out = []
    for xy, p in _status_entries(repo):
        out.append("%s %s" % (xy, p) + ("\0" if z else "\n"))
    return 0, "".join(out), ""


def cmd_add(repo, cwd, args):
    from dulwich.porcelain import add
    verbose = "-v" in args
    paths = [a for a in args if not a.startswith("-")]
    rels = [_rel(repo, cwd, p) for p in paths]
    abs_paths = [os.path.join(repo.path, r) for r in rels]
    added, ignored = add(repo, paths=abs_paths)
    out = ""
    if verbose:
        out = "".join("add '%s'\n" % (a.decode() if isinstance(a, bytes) else a) for a in added)
    return 0, out, ""


def cmd_restore(repo, cwd, args):
    if "--staged" not in args:
        return 129, "", "error: only --staged is supported\n"
    from dulwich.porcelain import reset
    paths = [a for a in args if not a.startswith("-")]
    head = _head(repo)
    idx = repo.open_index()
    for p in paths:
        r = _rel(repo, cwd, p).encode()
        if head is None:
            if r in idx:
                del idx[r]
            continue
        ent = _tree_lookup(repo, repo[head].tree, r.decode())
        if ent is None:
            if r in idx:
                del idx[r]
        else:
            from dulwich.index import IndexEntry
            mode, sha = ent
            full = os.path.join(repo.path, r.decode())
            st = os.stat(full) if os.path.exists(full) else None
            idx[r] = IndexEntry(
                ctime=(int(st.st_ctime), 0) if st else (0, 0), mtime=(int(st.st_mtime), 0) if st else (0, 0),
                dev=0, ino=0, mode=mode, uid=0, gid=0, size=len(repo[sha].data), sha=sha)
    idx.write()
    return 0, "", ""


def cmd_rm(repo, cwd, args):
    if "--cached" not in args:
        return 129, "", "error: only --cached is supported\n"
    paths = [a for a in args if not a.startswith("-")]
    idx = repo.open_index()
    out = []
    for p in paths:
        r = _rel(repo, cwd, p).encode()
        if r not in idx:
            return 128, "", "fatal: pathspec '%s' did not match any files\n" % p
        del idx[r]
        out.append("rm '%s'\n" % r.decode())
    idx.write()
    return 0, "".join(out), ""


def cmd_ls_files(repo, cwd, args):
    z = "-z" in args
    idx = repo.open_index()
    sep = "\0" if z else "\n"
    return 0, "".join(p.decode() + sep for p in sorted(idx)), ""


def cmd_ls_tree(repo, cwd, args):
    z = "-z" in args
    rec = "-r" in args
    name_only = "--name-only" in args
    pos = [a for a in args if not a.startswith("-")]
    if not pos:
        return 129, "", "usage: git ls-tree <tree-ish>\n"
    cid = _resolve(repo, pos[0])
    if cid is None:
        return 128, "", "fatal: Not a valid object name %s\n" % pos[0]
    tree = repo[repo[cid].tree]
    sep = "\0" if z else "\n"
    out = []

    def walk(t, prefix):
        for name, mode, sha in sorted(t.iteritems(), key=lambda e: e.path):
            path = (prefix + name.decode()) if prefix else name.decode()
            if stat.S_ISDIR(mode) and rec:
                walk(repo[sha], path + "/")
            elif name_only:
                out.append(path + sep)
            else:
                out.append("%06o %s %s\t%s%s" % (mode, "tree" if stat.S_ISDIR(mode) else "blob", sha.decode(), path, sep))
    walk(tree, "")
    return 0, "".join(out), ""


def cmd_log(repo, cwd, args):
    head = _head(repo)
    if head is None:
        return 128, "", "fatal: your current branch 'master' does not have any commits yet\n"
    limit, skip, fmt = None, 0, None
    for a in args:
        if a.startswith("--skip="):
            skip = int(a[7:])
        elif a.startswith("-n"):
            limit = int(a[2:])
        elif a.startswith("--max-count="):
            limit = int(a[12:])
        elif a.startswith("--format=") or a.startswith("--pretty="):
            fmt = a.split("=", 1)[1]
    if fmt is None:
        return 129, "", "error: only --format is supported\n"
    fmt = fmt.replace("%x00", "\0")
    out = []
    n = 0
    for entry in repo.get_walker(include=[head]):
        c = entry.commit
        if skip:
            skip -= 1
            continue
        if limit is not None and n >= limit:
            break
        n += 1
        author = c.author.decode("utf-8", "replace")
        an = author.rsplit(" <", 1)[0]
        line = (fmt.replace("%H", c.id.decode()).replace("%B", c.message.decode("utf-8", "replace"))
                .replace("%an", an).replace("%aI", _iso(c.author_time, c.author_timezone))
                .replace("%s", c.message.decode("utf-8", "replace").split("\n", 1)[0]))
        out.append(line + "\n")
    return 0, "".join(out), ""


def cmd_show(repo, cwd, args):
    pos = [a for a in args if not a.startswith("-")]
    if len(pos) != 1:
        return 129, "", "error: only `git show <rev>:<path>` is supported\n"
    try:
        return 0, _show_target(repo, pos[0]), ""
    except GitError as e:
        return e.code, "", str(e) + "\n"


def cmd_cat_file(repo, cwd, args):
    if args[:1] != ["-e"] or len(args) != 2:
        return 129, "", "error: only `git cat-file -e <object>` is supported\n"
    try:
        _show_target(repo, args[1])
        return 0, "", ""
    except GitError as e:
        return 128, "", str(e) + "\n"


def cmd_commit(repo, cwd, args, env=None):
    from dulwich.porcelain import commit
    msg = None
    it = iter(args)
    for a in it:
        if a == "-m":
            msg = next(it, None)
        elif a.startswith("-m"):
            msg = a[2:]
    if not msg:
        return 129, "", "error: switch `m' requires a value\n"
    ident = _identity(repo)
    if ident is None:
        return 128, "", ("Author identity unknown\n\n*** Please tell me who you are.\n\nRun\n\n"
                         "  git config --global user.email \"you@example.com\"\n"
                         "  git config --global user.name \"Your Name\"\n\nto set your account's default identity.\n")
    head = _head(repo)
    idx = repo.open_index()
    if head is not None and idx.commit(repo.object_store) == repo[head].tree:
        return 1, "nothing to commit, working tree clean\n", ""
    # git cleans the message: trailing whitespace stripped, exactly one newline at the end.
    msg = msg.rstrip() + "\n"
    a_date = _date_from_env(env, "GIT_AUTHOR_DATE")
    c_date = _date_from_env(env, "GIT_COMMITTER_DATE") or a_date
    kw = {}
    if a_date:
        kw["author_timestamp"], kw["author_timezone"] = a_date
    if c_date:
        kw["commit_timestamp"], kw["commit_timezone"] = c_date
    cid = commit(repo, message=msg.encode("utf-8"), author=ident, committer=ident, **kw)
    short = cid.decode()[:7]
    first = msg.split("\n", 1)[0]
    branch = repo.refs.read_ref(b"HEAD")
    bname = branch.replace(b"ref: refs/heads/", b"").decode() if branch and branch.startswith(b"ref: ") else "HEAD"
    root = " (root-commit)" if head is None else ""
    # The summary lines git prints. Only the first line is ever parsed; the rest is
    # what a person sees in the log.
    from dulwich.diff_tree import tree_changes, CHANGE_ADD, CHANGE_DELETE
    parent_tree = repo[head].tree if head is not None else None
    changes = list(tree_changes(repo.object_store, parent_tree, repo[cid].tree))
    lines = ["[%s%s %s] %s" % (bname, root, short, first)]
    if changes:
        lines.append(" %d file%s changed" % (len(changes), "" if len(changes) == 1 else "s"))
    for ch in changes:
        if ch.type == CHANGE_ADD:
            lines.append(" create mode %06o %s" % (ch.new.mode, ch.new.path.decode()))
        elif ch.type == CHANGE_DELETE:
            lines.append(" delete mode %06o %s" % (ch.old.mode, ch.old.path.decode()))
    return 0, "\n".join(lines) + "\n", ""


def _global_config_path(env):
    p = (env or {}).get("GIT_CONFIG_GLOBAL") or os.environ.get("GIT_CONFIG_GLOBAL")
    return p or os.path.expanduser("~/.gitconfig")


def cmd_config(repo, cwd, args, env=None):
    from dulwich.config import ConfigFile
    scope = None
    rest = []
    for a in args:
        if a in ("--global", "--local", "--get"):
            scope = a if a != "--get" else scope
            if a == "--get":
                rest.append(a)
        else:
            rest.append(a)
    get = rest[:1] == ["--get"]
    keys = rest[1:] if get else rest
    if not keys:
        return 129, "", "usage: git config [<options>]\n"
    section, name = keys[0].rsplit(".", 1)
    sec = tuple(s.encode() for s in section.split("."))
    if get:
        try:
            if scope == "--global":
                cf = ConfigFile.from_path(_global_config_path(env))
                v = cf.get(sec, name.encode())
            else:
                v = repo.get_config_stack().get(sec, name.encode())
        except (KeyError, FileNotFoundError):
            return 1, "", ""
        return 0, v.decode("utf-8", "replace") + "\n", ""
    if len(keys) < 2:
        return 129, "", "usage: git config <key> <value>\n"
    value = keys[1]
    if scope == "--global":
        path = _global_config_path(env)
        cf = ConfigFile.from_path(path) if os.path.exists(path) else ConfigFile()
        cf.set(sec, name.encode(), value.encode("utf-8"))
        cf.write_to_path(path)
    else:
        cf = repo.get_config()
        cf.set(sec, name.encode(), value.encode("utf-8"))
        cf.write_to_path()
    return 0, "", ""


def cmd_diff_tree(repo, cwd, args):
    from dulwich.diff_tree import tree_changes
    z = "-z" in args
    pos = [a for a in args if not a.startswith("-")]
    if not pos:
        return 129, "", "usage: git diff-tree <commit>\n"
    cid = _resolve(repo, pos[0])
    if cid is None:
        return 128, "", "fatal: bad object %s\n" % pos[0]
    c = repo[cid]
    parent_tree = repo[c.parents[0]].tree if c.parents else None
    sep = "\0" if z else "\n"
    out = []
    for ch in tree_changes(repo.object_store, parent_tree, c.tree):
        path = (ch.new.path or ch.old.path).decode()
        out.append(path + sep)
    return 0, "".join(out), ""


COMMANDS = {
    "init": cmd_init, "rev-parse": cmd_rev_parse, "status": cmd_status, "add": cmd_add,
    "restore": cmd_restore, "rm": cmd_rm, "ls-files": cmd_ls_files, "ls-tree": cmd_ls_tree,
    "log": cmd_log, "show": cmd_show, "cat-file": cmd_cat_file, "commit": cmd_commit,
    "config": cmd_config, "diff-tree": cmd_diff_tree,
}
NO_REPO = {"init", "--version"}


def run(argv, cwd=None, env=None):
    """argv is [git, subcommand, ...]. Returns (returncode, stdout, stderr); stdout is
    bytes for `show` (the adapter reads raw bytes there) and str elsewhere."""
    cwd = cwd or os.getcwd()
    args = list(argv[1:])
    if not args:
        return 1, "", "usage: git <command> [<args>]\n"
    if args[0] == "--version":
        return 0, "git version 2.47.0.fcweb (dulwich)\n", ""
    sub = args[0]
    fn = COMMANDS.get(sub)
    if fn is None:
        return 1, "", "git: '%s' is not a git command. See 'git --help'.\n" % sub
    try:
        repo = None if sub in NO_REPO else _repo(cwd)
        if sub in ("config", "commit"):
            return fn(repo, cwd, args[1:], env=env)
        return fn(repo, cwd, args[1:])
    except GitError as e:
        return e.code, "", str(e) + "\n"
    except Exception as e:  # never a traceback into the caller
        return 128, "", "fatal: %s: %r\n" % (sub, e)


# ------------------------------------------------------------------- subprocess hook

_orig_run = subprocess.run
_orig_popen = subprocess.Popen
_orig_call = subprocess.call


def _no_such_process(argv):
    """What a spawn of anything that is not our git means here. emscripten raises
    OSError(138, 'emscripten does not support processes'); callers written for a real
    OS handle FileNotFoundError as "that program is not installed" (dulwich's hook
    runner does exactly that, hooks.py: `except FileNotFoundError: # no file. silent
    failure.`), and that is the truthful answer: the program is not installed."""
    name = argv[0] if isinstance(argv, (list, tuple)) and argv else str(argv)
    raise FileNotFoundError(2, "No such file or directory (no processes in the browser)", str(name))


def _call_hook(argv, *a, **kwargs):
    if _is_git(argv):
        return _run_hook(argv, *a, **kwargs).returncode
    _no_such_process(argv)


def _is_git(argv):
    try:
        a0 = argv[0] if isinstance(argv, (list, tuple)) else None
        return isinstance(a0, str) and (a0 == GIT_PATH or os.path.basename(a0) == "git")
    except Exception:
        return False


def _completed(argv, kwargs, code, out, err):
    text = kwargs.get("text") or kwargs.get("universal_newlines") or kwargs.get("encoding") or kwargs.get("errors")
    if text:
        if isinstance(out, bytes):
            out = out.decode(kwargs.get("encoding") or "utf-8", kwargs.get("errors") or "replace")
    else:
        if isinstance(out, str):
            out = out.encode("utf-8")
        if isinstance(err, str):
            err = err.encode("utf-8")
    return subprocess.CompletedProcess(argv, code, out, err)


def _run_hook(argv, *a, **kwargs):
    if not _is_git(argv):
        if sys.platform == "emscripten":
            _no_such_process(argv)
        return _orig_run(argv, *a, **kwargs)
    code, out, err = run(argv, cwd=kwargs.get("cwd"), env=kwargs.get("env"))
    cp = _completed(argv, kwargs, code, out, err)
    if kwargs.get("check") and code != 0:
        raise subprocess.CalledProcessError(code, argv, cp.stdout, cp.stderr)
    return cp


def install():
    """Put `git` on PATH and route subprocess.run for it. Idempotent."""
    if sys.platform != "emscripten":
        return "fcweb_git: not emscripten, left alone"
    os.makedirs(GIT_BIN_DIR, exist_ok=True)
    if not os.path.exists(GIT_PATH):
        with open(GIT_PATH, "w") as f:
            f.write("#!/bin/sh\n# freecad-web: git is answered in-process by fcweb_git.py\n")
        os.chmod(GIT_PATH, 0o755)
    if GIT_BIN_DIR not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = GIT_BIN_DIR + os.pathsep + os.environ.get("PATH", "")
    if subprocess.run is not _run_hook:
        subprocess.run = _run_hook
    if subprocess.Popen is not _FakePopen:
        subprocess.Popen = _FakePopen
    if subprocess.call is not _call_hook:
        subprocess.call = _call_hook
    return "git -> fcweb_git (dulwich) at %s" % GIT_PATH


class _FakePopen:
    """Enough of Popen for check_output/communicate-style callers that name our git.
    Anything else falls through to the real Popen (which raises under emscripten).

    Subscriptable, because the real class is generic and code annotates with
    ``subprocess.Popen[bytes]`` at definition time (dulwich/filters.py:154 does); after
    the swap that subscript must keep working or importing dulwich itself throws.
    Measured in the engine on 2026-09-21: "type '_FakePopen' is not subscriptable".
    """

    def __class_getitem__(cls, item):
        return cls

    def __new__(cls, argv, *a, **kw):
        if not _is_git(argv):
            if sys.platform == "emscripten":
                _no_such_process(argv)
            return _orig_popen(argv, *a, **kw)
        self = object.__new__(cls)
        code, out, err = run(argv, cwd=kw.get("cwd"), env=kw.get("env"))
        cp = _completed(argv, kw, code, out, err)
        self.args, self.returncode = argv, code
        self._out, self._err = cp.stdout, cp.stderr
        self.stdout = io.BytesIO(self._out) if isinstance(self._out, bytes) else io.StringIO(self._out)
        self.stderr = io.BytesIO(self._err) if isinstance(self._err, bytes) else io.StringIO(self._err)
        self.pid = 0
        return self

    def communicate(self, input=None, timeout=None):
        return self._out, self._err

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        pass

    terminate = kill

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def ensure_dulwich(on_done):
    """Import dulwich, fetching its wheel through fcweb_wheels if needed. on_done(ok)."""
    try:
        import dulwich  # noqa: F401
        return on_done(True)
    except ImportError:
        pass
    try:
        import fcweb_wheels
        fcweb_wheels.fetch_and_install(DULWICH_DIST, lambda ok, why: on_done(ok))
    except Exception:
        on_done(False)


if __name__ == "__main__":
    # Desktop self-check: build a repo with dulwich through run(), and where real git is
    # available compare every parsed format against it. scratchpad/gitshim-check.py is
    # the fuller version; this is the smoke that must stay green.
    import tempfile, shutil, json
    d = tempfile.mkdtemp()
    G = ["git"]
    c, o, e = run(G + ["init"], cwd=d); assert c == 0, e
    c, o, e = run(G + ["rev-parse", "--show-toplevel"], cwd=d); assert o.strip() == os.path.realpath(d).replace(os.sep, "/"), o
    c, o, e = run(G + ["rev-parse", "--verify", "HEAD"], cwd=d); assert c == 128
    c, o, e = run(G + ["log", "-n20", "--format=%H%x00%B%x00%an%x00%aI%x00"], cwd=d); assert c == 128 and "any commits yet" in e
    open(os.path.join(d, "a.FCStd"), "wb").write(b"one")
    os.makedirs(os.path.join(d, "sub")); open(os.path.join(d, "sub", "b.FCStd"), "wb").write(b"two")
    c, o, e = run(G + ["status", "--porcelain", "-z"], cwd=d); assert o == "?? a.FCStd\0?? sub/\0", repr(o)
    c, o, e = run(G + ["add", "-v", "--", "a.FCStd", "sub/b.FCStd"], cwd=d); assert c == 0 and "add 'a.FCStd'" in o, (c, o, e)
    c, o, e = run(G + ["status", "--porcelain", "-z"], cwd=d); assert o == "A  a.FCStd\0A  sub/b.FCStd\0", repr(o)
    c, o, e = run(G + ["commit", "-m", "first"], cwd=d); assert c == 128 and "identity" in e.lower(), (c, e)
    c, o, e = run(G + ["config", "--local", "user.name", "Tester"], cwd=d); assert c == 0
    c, o, e = run(G + ["config", "--local", "user.email", "t@example.com"], cwd=d); assert c == 0
    c, o, e = run(G + ["config", "--get", "user.name"], cwd=d); assert o == "Tester\n", o
    c, o, e = run(G + ["commit", "-m", "first\n\nbody line"], cwd=d); assert c == 0 and "(root-commit)" in o, (c, o, e)
    c, o, e = run(G + ["log", "-n20", "--format=%H%x00%B%x00%an%x00%aI%x00"], cwd=d)
    parts = o.strip().split("\0"); assert len(parts[0]) == 40 and parts[1] == "first\n\nbody line\n" and parts[2] == "Tester", parts
    datetime.fromisoformat(parts[3].strip())
    c, o, e = run(G + ["ls-files", "-z"], cwd=d); assert o == "a.FCStd\0sub/b.FCStd\0", repr(o)
    c, o, e = run(G + ["ls-tree", "-r", "-z", "--name-only", "HEAD"], cwd=d); assert o == "a.FCStd\0sub/b.FCStd\0", repr(o)
    c, o, e = run(G + ["show", "HEAD:sub/b.FCStd"], cwd=d); assert o == b"two", o
    c, o, e = run(G + ["show", ":a.FCStd"], cwd=d); assert o == b"one", o
    c, o, e = run(G + ["cat-file", "-e", "HEAD:a.FCStd"], cwd=d); assert c == 0
    c, o, e = run(G + ["cat-file", "-e", "HEAD:nope"], cwd=d); assert c == 128
    c, o, e = run(G + ["diff-tree", "--root", "--no-commit-id", "--name-only", "-z", "-r", "HEAD"], cwd=d); assert o == "a.FCStd\0sub/b.FCStd\0", repr(o)
    open(os.path.join(d, "a.FCStd"), "wb").write(b"one-changed")
    c, o, e = run(G + ["status", "--porcelain", "-z"], cwd=d); assert o == " M a.FCStd\0", repr(o)
    run(G + ["add", "--", "a.FCStd"], cwd=d)
    c, o, e = run(G + ["status", "--porcelain", "-z"], cwd=d); assert o == "M  a.FCStd\0", repr(o)
    c, o, e = run(G + ["restore", "--staged", "--", "a.FCStd"], cwd=d); assert c == 0, e
    c, o, e = run(G + ["status", "--porcelain", "-z"], cwd=d); assert o == " M a.FCStd\0", repr(o)
    run(G + ["add", "--", "a.FCStd"], cwd=d)
    c, o, e = run(G + ["commit", "-m", "second"], cwd=d); assert c == 0 and "(root-commit)" not in o, o
    c, o, e = run(G + ["diff-tree", "--root", "--no-commit-id", "--name-only", "-z", "-r", "HEAD"], cwd=d); assert o == "a.FCStd\0", repr(o)
    c, o, e = run(G + ["rev-parse", "--verify", "HEAD~1^{commit}"], cwd=d); assert c == 0 and len(o.strip()) == 40
    c, o, e = run(G + ["log", "--skip=1", "-n1", "--format=%H%x00%B%x00%an%x00%aI%x00"], cwd=d); assert o.split("\0")[1].startswith("first"), o
    c, o, e = run(G + ["rm", "--cached", "--", "sub/b.FCStd"], cwd=d); assert c == 0 and o == "rm 'sub/b.FCStd'\n", (c, o, e)
    c, o, e = run(G + ["status", "--porcelain", "-z"], cwd=d); assert o == "D  sub/b.FCStd\0?? sub/\0", repr(o)
    c, o, e = run(G + ["frobnicate"], cwd=d); assert c == 1 and "not a git command" in e
    # the subprocess hook shape
    subprocess.run = _run_hook
    cp = subprocess.run([GIT_PATH, "rev-parse", "--show-toplevel"], cwd=d, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
    assert cp.returncode == 0 and cp.stdout.strip().endswith(os.path.basename(d)), cp
    cp = subprocess.run([GIT_PATH, "show", "HEAD:a.FCStd"], cwd=d, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    assert cp.stdout == b"one-changed", cp
    subprocess.run = _orig_run
    # The Popen swap must not break code that subscripts the class (dulwich does).
    subprocess.Popen = _FakePopen
    assert subprocess.Popen[bytes] is _FakePopen
    cp = subprocess.Popen([GIT_PATH, "rev-parse", "--show-toplevel"], cwd=d, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    outb, errb = cp.communicate(); assert cp.returncode == 0 and outb.strip().endswith(os.path.basename(d).encode()), (cp.returncode, outb, errb)
    subprocess.Popen = _orig_popen
    shutil.rmtree(d, ignore_errors=True)
    print("fcweb_git self-check ok")
