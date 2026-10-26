#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
#
# Run the end-to-end tests against the wheel of this checkout.
#
# Builds the wheel (or takes one with --wheel FILE), installs it into a fresh
# virtual environment together with pytest, and runs e2e/ with that
# environment's pytest, so the tests see the installed package and its
# installed share/seanerstack data, not the source tree. Remaining arguments
# are passed to pytest. See e2e/conftest.py for the environment variables.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

WHEEL=""
if [[ "${1:-}" == --wheel ]]; then
    WHEEL="$(realpath "${2:?--wheel requires FILE}")"
    shift 2
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/seanerstack-e2e.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

if [[ -z "$WHEEL" ]]; then
    # --no-sources builds the wheel as it is published.
    uv build --wheel --no-sources --out-dir "$WORK/dist" "$REPO"
    WHEEL="$(echo "$WORK"/dist/seanerstack-*.whl)"
fi
echo "==> testing $WHEEL"

uv venv --quiet "$WORK/venv"
uv pip install --quiet --python "$WORK/venv/bin/python" "$WHEEL" "pytest>=8"

# The environment's own pytest rather than `python -m pytest`, which would put
# the working directory on sys.path.
cd "$REPO"
"$WORK/venv/bin/pytest" -p no:cacheprovider "$HERE" "$@"
