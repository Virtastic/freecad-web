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
import glob
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

def workflow_problems():
    """The same rule for workflow `run:` blocks, which are shell scripts wearing a hat.

    Scripts were only half the surface. Forty-one workflow steps sourced emsdk directly,
    and five of them built real artifacts: the freetype and ICU ports, yaml-cpp, and
    FreeCAD's own Configure. The freetype one is what actually broke the first wasm64
    build-deps run -- it pre-built the port for wasm32, so OCCT then triggered an
    on-demand wasm64 build of the same port and died on an emscripten flag bug 15 seconds
    in. yaml-cpp is the quieter case: it built, produced one archive, and passed the
    archive-count gate, which counts files and cannot see a target.

    The emsdk-install steps are exempt: they run `. ./emsdk_env.sh` from INSIDE the emsdk
    directory purely to confirm the SDK landed, and build nothing.
    """
    try:
        import yaml
    except ImportError:
        return []
    problems = []
    for path in sorted(glob.glob('.github/workflows/*.yml')):
        doc = yaml.safe_load(io.open(path, encoding='utf-8').read())
        for job in (doc.get('jobs') or {}).values():
            for step in (job.get('steps') or []):
                run = step.get('run') or ''
                if not run or 'toolchain/env.sh' in run:
                    continue
                if 'emsdk/emsdk_env.sh' in run:
                    problems.append((path, 'step %r sources emsdk directly'
                                     % (step.get('name') or '?')))
                    continue
                used = tools_used(run)
                if used and 'emsdk_env.sh' not in run:
                    problems.append((path, 'step %r runs %s without the pinned toolchain'
                                     % (step.get('name') or '?', ', '.join(sorted(used)))))
    return problems


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

    problems += workflow_problems()

    if problems:
        for path, why in problems:
            print('%s: %s' % (path, why), file=sys.stderr)
        print('', file=sys.stderr)
        print('%d place(s) can reach emcc without the pinned toolchain. Each would build '
              'for wasm32 with no diagnostic.' % len(problems), file=sys.stderr)
        return 1
    print('every emscripten-invoking script and workflow step sources toolchain/env.sh')
    return 0


if __name__ == '__main__':
    sys.exit(main())
