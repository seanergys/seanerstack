#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
#
# The tutorial docs/tutorials/getting-started.md, run from start to end.
#
# The page shows the marked sections of this file, so what it tells a reader
# to type is what the `tutorial:install-the-stack` job runs. Run it in the
# directory that holds secrets.toml, with the vault password on standard
# input when there is no terminal to ask on, and with Git access to the
# SEANERGYS GitLab.
#
# A seanerstack that is already on PATH is used as it is, which is how the job
# tests the checkout and not the published release. As root, as in a
# container, nothing needs sudo.
#
#   tests/tutorials/install-the-stack.sh < vault-password
set -eo pipefail

if ! command -v sudo >/dev/null; then
    sudo() { "$@"; }
fi
# A container sets no USER.
export USER="${USER:-$(id -un)}"

install_seanerstack() {
# --8<-- [start:install]
pipx install --python python3.12 --include-deps seanerstack
# --8<-- [end:install]
}
command -v seanerstack >/dev/null || install_seanerstack

# --8<-- [start:state]
export SEANERSTACK_STATE_DIR=/opt/seanergys/state
sudo mkdir -p "$SEANERSTACK_STATE_DIR"
sudo chown "$USER" "$SEANERSTACK_STATE_DIR"
seanerstack --secrets-file secrets.toml init
# --8<-- [end:state]

# --8<-- [start:activate]
eval "$(seanerstack activate)"
# --8<-- [end:activate]

# --8<-- [start:toolchain]
seanerstack toolchain bootstrap
# --8<-- [end:toolchain]

# --8<-- [start:stack]
spack install seanergys-meta
# --8<-- [end:stack]

# --8<-- [start:find]
spack find
# --8<-- [end:find]

# The stack is installed, by the Spack of the state.
[ "$(command -v spack)" = "$SEANERSTACK_STATE_DIR/spack/bin/spack" ]
spack find seanergys-meta

echo "install-the-stack: seanergys-meta is installed in $SEANERSTACK_STATE_DIR"
