# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Every script that runs an emscripten tool must source toolchain/env.sh.

    python tools/check-toolchain-env.py

toolchain/env.sh is the single place that pins the SDK and sets EMCC_CFLAGS=-m64, which is
what makes the build target wasm64. emcc appends EMCC_CFLAGS to every invocation, including
the probe compiles autotools and meson run during configure -- so a script that sources
emsdk/emsdk_env.sh directly gets a working emcc that quietly targets wasm32.

That is not hypothetical. When the wasm64 conversion started, FIFTEEN scripts did exactly
this: the whole CalculiX/gmsh solver stack (build-ccx-weh.sh, build-ccx-module-weh.sh,
build-gmsh-weh.sh, build-libf2c-weh.sh, build-spooles-weh.sh, build-arpack-weh.sh,
configure-gmsh-weh.sh) and most of the Python extension stack (configure-numpy.sh,
configure-matplotlib-weh.sh, configure-pillow.sh, configure-ctypes.sh, configure-pivy-weh.sh,
configure-kiwisolver*.sh). Each would have produced a wasm32 .a that the final link either
rejects after hours, or -- worse -- that reports its own size and symbol counts as healthy.

The failure has no symptom at the point it happens, which is why it is a gate and not a
convention.
"""
import io
import subprocess
import sys

TOOLS = {
    'emcc', 'em++', 'emcmake', 'emconfigure', 'emmake', 'emar', 'emranlib',
    'embuilder', 'emstrip', 'emnm',
}
# Shell characters that can butt up against a command name.
SEPARATORS = '"\'`;|&()<>{}='


def tools_used(text):
    """Names of emscripten tools invoked anywhere in the script."""
    found = set()
    for raw in text.split(chr(10)):
        line = raw.split('#', 1)[0]
        for sep in SEPARATORS:
            line = line.replace(sep, ' ')
        for token in line.split():
            name = token.rsplit('/', 1)[-1]      # strip any path prefix
            if name in TOOLS:
                found.add(name)
    return found


def clobbers_emcc_cflags(text):
    """The first EMCC_CFLAGS assignment that discards whatever was already there.

    Sourcing toolchain/env.sh is necessary but not sufficient: a later plain assignment
    silently drops -m64. build-cpython-mt.sh did exactly this -- so the threaded CPython
    that actually ships would have been the one wasm32 archive in a wasm64 link.
    """
    for raw in text.split(chr(10)):
        line = raw.split(chr(35), 1)[0].strip()
        if line.startswith('export '):
            line = line[len('export '):].strip()
        for var in ('EMCC_CFLAGS', 'EMCC_CXXFLAGS'):
            if line.startswith(var + '=') and var not in line[len(var) + 1:]:
                return raw.strip()
    return None

def main():
    listed = subprocess.check_output(['git', 'ls-files', '*.sh']).decode()
    problems = []
    for path in listed.split(chr(10)):
        if not path or path == 'toolchain/env.sh':
            continue
        try:
            text = io.open(path, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        if 'toolchain/env.sh' in text:
            clobber = clobbers_emcc_cflags(text)
            if clobber:
                problems.append((path, 'assigns EMCC_CFLAGS without keeping the existing value (%s) -- this drops the -m64 from toolchain/env.sh' % clobber))
            continue
        if 'emsdk_env.sh' in text:
            problems.append((path, 'sources emsdk directly instead of toolchain/env.sh'))
            continue
        used = tools_used(text)
        if used:
            problems.append((path, 'runs %s without sourcing toolchain/env.sh'
                                   % ', '.join(sorted(used))))

    if problems:
        for path, why in problems:
            print('%s: %s' % (path, why), file=sys.stderr)
        print('', file=sys.stderr)
        print('%d script(s) can reach emcc without the pinned toolchain. Each would build '
              'for wasm32 with no diagnostic.' % len(problems), file=sys.stderr)
        return 1
    print('every emscripten-invoking script sources toolchain/env.sh')
    return 0


if __name__ == '__main__':
    sys.exit(main())
