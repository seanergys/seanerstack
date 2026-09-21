# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
from spack_repo.builtin.build_systems.cargo import CargoPackage

from spack.package import *


class Demobus(CargoPackage):
    """The demonstrator SeanerBUS req/res and pub/sub broker"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/demobus"
    git = "git@gitlab.seanergys.fz-juelich.de:software/demobus.git"

    # Cargo.toml carries path dependencies on deps/internal/internal_schemas
    # and deps/internal/async, which live in the `deps` submodule. Spack does
    # not clone submodules unless asked, and without them the build fails on
    # the unresolved path dependencies rather than on a missing checkout.
    submodules = True

    license("MIT")

    # Development follows the upstream default branch.
    version("develop", branch="main")

    # Released versions are synchronized from upstream Git tags by `seanstack sync`.
    version("0.2.1", tag="v0.2.1", commit="c2ae842f0ff5ef81802964eb4f4f62b4e4c121b6")
    version("0.2", tag="v0.2", commit="9847ba8eede5d5c319f0fa7f1754c0ffcf5925c8")
