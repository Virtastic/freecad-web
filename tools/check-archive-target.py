# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Every wasm object in the given archives/objects must be built for the expected target.

    python tools/check-archive-target.py [--expect wasm64|wasm32] [--prune] PATH...

PATH is a .a archive, a .o object, or a directory (searched recursively for both).

Why this exists: a cache is named, not inspected. The deps cache key said wasm64 and one of
its archives was not:

    wasm-ld: error: deps/wasm/lib/libyaml-cpp.a(graphbuilder.cpp.o):
             wasm32 object file can't be linked in wasm64 mode

-- discovered at the END of link-freecad run 33950974628, after the whole of FreeCAD had
compiled, because every dependency lane skips a step whose archive already exists and
nothing ever asked which target that archive was built for. wasm-ld reports one such
object and stops, so a run finds one straggler at a time.

The tell is in the object itself. The `target_features` custom section lists the features
the object was compiled with, and an object compiled with -m64 carries `+memory64`; one
compiled for wasm32 does not (verified against emsdk 6.0.9 output for both). That is what
wasm-ld goes by, so it is what this checks.

--prune deletes every archive/object that fails (so the lane that owns it rebuilds it) and
still exits non-zero, so a lane can prune before its build steps and gate after them.
"""
import argparse
import io
import os
import sys


def leb_u(b, i):
    result = shift = 0
    while True:
        x = b[i]
        i += 1
        result |= (x & 0x7f) << shift
        shift += 7
        if not x & 0x80:
            return result, i


def ar_members(data):
    """(name, bytes) for every member of a GNU/BSD ar archive; wasm members only."""
    if not data.startswith(b'!<arch>\n'):
        return []
    i = 8
    longnames = b''
    out = []
    while i + 60 <= len(data):
        hdr = data[i:i + 60]
        name = hdr[:16].decode('latin-1').rstrip()
        size = int(hdr[48:58].decode().strip() or '0')
        body = data[i + 60:i + 60 + size]
        i += 60 + size + (size & 1)
        if name == '//':
            longnames = body
            continue
        if name in ('/', '/SYM64/') or name.startswith('__.SYMDEF'):
            continue
        if name.startswith('/') and name[1:].isdigit():          # GNU long name
            off = int(name[1:])
            name = longnames[off:longnames.index(b'\n', off)].decode('latin-1').rstrip('/')
        elif name.startswith('#1/'):                              # BSD long name
            n = int(name[3:])
            name = body[:n].decode('latin-1').rstrip('\0')
            body = body[n:]
        else:
            name = name.rstrip('/')
        if body[:4] == b'\0asm':
            out.append((name, body))
    return out


def features(obj):
    """The target_features of one wasm object, or None if it carries no such section."""
    i = 8
    while i < len(obj):
        sid = obj[i]
        i += 1
        size, i = leb_u(obj, i)
        body = obj[i:i + size]
        i += size
        if sid != 0:
            continue
        n, j = leb_u(body, 0)
        if body[j:j + n] != b'target_features':
            continue
        j += n
        count, j = leb_u(body, j)
        feats = []
        for _ in range(count):
            prefix = chr(body[j])
            j += 1
            ln, j = leb_u(body, j)
            feats.append(prefix + body[j:j + ln].decode('utf-8', 'replace'))
            j += ln
        return feats
    return None


def target_of(obj):
    f = features(obj)
    if f is None:
        return 'unknown'
    return 'wasm64' if '+memory64' in f else 'wasm32'


def walk(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for f in files:
                    if f.endswith(('.a', '.o')):
                        yield os.path.join(root, f)
        else:
            yield p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--expect', default='wasm64', choices=['wasm64', 'wasm32'])
    ap.add_argument('--prune', action='store_true', help='delete every file that fails')
    ap.add_argument('paths', nargs='+')
    a = ap.parse_args()

    bad = []
    files = 0
    objects = 0
    for path in walk(a.paths):
        try:
            data = io.open(path, 'rb').read()
        except OSError as e:
            print('  ??  %s: %s' % (path, e))
            continue
        if data[:4] == b'\0asm':
            members = [(os.path.basename(path), data)]
        else:
            members = ar_members(data)
            if not members:
                continue                       # not an archive of wasm objects (host tool, empty)
        files += 1
        wrong = []
        for name, obj in members:
            objects += 1
            t = target_of(obj)
            if t != a.expect:
                wrong.append((name, t))
        if wrong:
            bad.append(path)
            print('  BAD %s: %d of %d object(s) are not %s, e.g. %s (%s)'
                  % (path, len(wrong), len(members), a.expect, wrong[0][0], wrong[0][1]))
            if a.prune:
                os.unlink(path)
                print('      pruned -- the lane that owns it will rebuild it')
    print('%d file(s), %d wasm object(s) checked for %s: %d wrong'
          % (files, objects, a.expect, len(bad)))
    if bad:
        print('::error::%d archive(s)/object(s) are not %s: %s'
              % (len(bad), a.expect, ' '.join(os.path.basename(b) for b in bad[:12])), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
