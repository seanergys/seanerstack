# SPDX-License-Identifier: Apache-2.0
"""The Spack that Seanerstack uses, and the recipes it loads: the one place to change them.

Every hash, and with it whether a binary of the project build cache matches,
depends on both, so every session, CI job and toolchain build takes them from
here. Change them together: the builtin repository commit has to be one that
the Spack version supports. After a change, the toolchain is rebuilt for every
platform, because no hash stays the same.
"""

# A commit of the develop branch of SPACK_GIT, and the version it reports.
# Seanerstack installs it into each state directory and refuses any other.
#
# Not a release: Spack 1.2.2 hangs when it concretizes with a gcc that Spack
# built with a newer gcc, such as gcc 15 built by the gcc 16 of Fedora 44.
# The fixes, spack/spack#53338 and #53339, were merged on 2026-11-11 and are
# in no release yet. Many commits report the same development version, so
# the commit is what identifies this Spack.
SPACK_COMMIT = "7188f9d6e0f345d023d1f947401eeaaf5ced9f5f"
SPACK_VERSION = "1.3.0.dev0"
SPACK_GIT = "https://github.com/spack/spack.git"

# spack-packages v2026.10.0, package API v2.2, which Spack 1.2 supports.
BUILTIN_REPO_COMMIT = "91cfb5b973c311f742cd31061fe224d40f1fd830"
# Spack declares this in its own defaults; the private scope has to repeat it
# because it replaces those defaults rather than merging with them.
BUILTIN_REPO_GIT = "https://github.com/spack/spack-packages.git"
