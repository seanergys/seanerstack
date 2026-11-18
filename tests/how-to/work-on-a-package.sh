#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
#
# The procedure of docs/how-to/work-on-a-package.md, run from start to end.
#
# The page shows the marked sections of this file, so what it tells a reader
# to type is what the `how-to:work-on-a-package` job runs. It needs a state
# that `seanerstack init` and `seanerstack toolchain bootstrap` have set up,
# the state's spack on PATH, and Git access to the SEANERGYS GitLab. The
# checkout goes below DIRECTORY, by default a new temporary directory.
#
#   tests/how-to/work-on-a-package.sh [DIRECTORY]
set -eo pipefail

SOURCES="${1:-$(mktemp -d)}"

# --8<-- [start:checkout]
git clone --recurse-submodules https://gitlab.seanergys.fz-juelich.de/software/priorisea.git "$SOURCES/priorisea"
cd "$SOURCES/priorisea"
# --8<-- [end:checkout]

# --8<-- [start:activate]
eval "$(spack env activate --sh "$(seanerstack paths env --package priorisea)")"
# --8<-- [end:activate]

# --8<-- [start:develop]
spack develop --path "$PWD" priorisea@main
# --8<-- [end:develop]

# --8<-- [start:install]
spack concretize -f
spack install
# --8<-- [end:install]

# --8<-- [start:check]
spack find --format '{name}{@version} {variants.dev_path}' priorisea
priorisea --help
# --8<-- [end:check]

# The installed priorisea is the one built from the checkout.
spack find --format '{variants.dev_path}' priorisea | grep -qx "dev_path=$PWD"

# --8<-- [start:deactivate]
eval "$(spack env deactivate --sh)"
# --8<-- [end:deactivate]

echo "work-on-a-package: priorisea is installed from $PWD"
