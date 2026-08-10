#!/bin/bash
set -e
cd "$(dirname "$0")"
bash configure-matplotlib-weh.sh
bash configure-kiwisolver-weh.sh
echo "LANE4B-ALL-DONE"
