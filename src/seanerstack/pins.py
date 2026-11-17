# SPDX-License-Identifier: Apache-2.0
"""The Spack that Seanerstack uses, and the recipes it loads: the one place to change them.

Every hash, and with it whether a binary of the project build cache matches,
depends on both, so every session, CI job and toolchain build takes them from
here. Change them together: the builtin repository commit has to be one that
the Spack version supports. After a change, the toolchain is rebuilt for every
platform, because no hash stays the same.
"""

# A tag of SPACK_GIT. Seanerstack installs it into each state directory and
# refuses any other version.
SPACK_VERSION = "v1.2.2"
SPACK_GIT = "https://github.com/spack/spack.git"

# spack-packages v2026.10.0, package API v2.2, which Spack 1.2 supports.
BUILTIN_REPO_COMMIT = "91cfb5b973c311f742cd31061fe224d40f1fd830"
# Spack declares this in its own defaults; the private scope has to repeat it
# because it replaces those defaults rather than merging with them.
BUILTIN_REPO_GIT = "https://github.com/spack/spack-packages.git"
