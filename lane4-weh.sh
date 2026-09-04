#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
set -e
cd "$(dirname "$0")"
rm -rf build-matplotlib
# configure-matplotlib-weh.sh, not configure-matplotlib.sh: only the -weh one carries the
# PIL import guards matplotlib needs (colors.py, animation.py and image.py import Pillow at
# module scope, before it is importable on some paths). build-python-deps.yml has always
# run the -weh script; this lane ran the other one, so anyone following the manual sequence
# in BUILD-WEH.md got a matplotlib the CI build would never produce.
bash configure-matplotlib-weh.sh
bash configure-kiwisolver-weh.sh
echo "LANE4-ALL-DONE"
