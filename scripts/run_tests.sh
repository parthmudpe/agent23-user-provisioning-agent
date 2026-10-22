#!/usr/bin/env bash
# Unit tests (no root, no API key, no system changes).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tests -t . -v
