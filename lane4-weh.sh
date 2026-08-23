#!/bin/bash
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
set -e
cd "$(dirname "$0")"
rm -rf build-matplotlib
bash configure-matplotlib.sh
bash configure-kiwisolver-weh.sh
echo "LANE4-ALL-DONE"
