#!/usr/bin/env bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
# Build f2c natively, so a translation question takes a second instead of a CI run.
#
# WHY THIS EXISTS
#
# Every question about "why is routine X stubbed?" was costing a 10-minute build-ccx.yml
# dispatch, and the answers are not guessable: f2c reports "Error on line 221" against ITS
# OWN input -- the rewritten file under build-ccx-weh/f77 -- which only exists on the runner.
# I burned several runs reading line 221 of a locally regenerated copy before realising it
# might not even be the same bytes.
#
# There is a native compiler on any machine that has emsdk: emsdk ships upstream LLVM, so
# emsdk/upstream/bin/clang is a full native clang. No gcc, no make, no MSVC needed.
#
# USAGE
#
#     bash tools/build-f2c-local.sh [emsdk-dir]      # default: $HOME/emsdk, then ./emsdk
#     ./f2c-local/f2c -a -A -NC1000 -dc some.f       # same flags build-ccx-weh.sh uses
#
# Then the loop is: run tools/f77ify.py on a source, run this f2c on the result, read the
# error. Seconds, and against the exact bytes the build would feed it.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

EMSDK="${1:-}"
for cand in "$EMSDK" "$HOME/emsdk" "$root/emsdk"; do
  [ -n "$cand" ] && [ -x "$cand/upstream/bin/clang" ] && { EMSDK="$cand"; break; }
  [ -n "$cand" ] && [ -x "$cand/upstream/bin/clang.exe" ] && { EMSDK="$cand"; break; }
done
if [ -z "${EMSDK:-}" ] || { [ ! -x "$EMSDK/upstream/bin/clang" ] && [ ! -x "$EMSDK/upstream/bin/clang.exe" ]; }; then
  echo "ERROR: no clang found. Pass the emsdk directory:  bash $0 /path/to/emsdk" >&2
  exit 1
fi
CLANG="$EMSDK/upstream/bin/clang"
echo "clang: $CLANG"

out="$root/f2c-local"
mkdir -p "$out"
cd "$out"

if [ ! -e src/main.c ]; then
  echo "fetching f2c source from netlib..."
  curl -fsSL -o src.tgz https://netlib.org/f2c/src.tgz
  mkdir -p src && tar xzf src.tgz -C src --strip-components=1
fi
cd src

# tokdefs.h is generated from `tokens` by the makefile; reproduce that rule.
[ -e tokdefs.h ] || grep -n . < tokens | sed "s/\([^:]*\):\(.*\)/#define \2 \1/" > tokdefs.h

# sysdep.hd is the makefile's feature probe. mkdtemp is absent on Windows and unnecessary
# here, so take the branch the makefile takes when the probe fails.
[ -e sysdep.hd ] || echo '#define NO_MKDTEMP' > sysdep.hd

# The OBJECTS list from makefile.u, minus malloc.c: that is $(MALLOC), empty by default, and
# it calls sbrk() which does not exist outside classic Unix. xsum.c and sysdeptest.c are
# standalone tools, not part of f2c.
SRC="main.c init.c gram.c lex.c proc.c equiv.c data.c format.c expr.c exec.c intr.c io.c
     misc.c error.c mem.c names.c output.c p1output.c pread.c put.c putpcc.c vax.c
     formatdata.c parse_args.c niceprintf.c cds.c sysdep.c version.c"

echo "compiling..."
"$CLANG" -O1 -w -std=gnu89 \
  -Wno-implicit-function-declaration -Wno-return-type -Wno-int-conversion \
  -o ../f2c $SRC

cd ..
echo
ls -la f2c* 2>/dev/null | head -2
echo
echo "ready:  $out/f2c -a -A -NC1000 -dc <file>.f"
