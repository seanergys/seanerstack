# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
from spack_repo.builtin.build_systems.cargo import CargoPackage

from spack.package import *


class Demobus(CargoPackage):
    """The demonstrator SeanerBUS req/res and pub/sub broker"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/demobus"
    url = "https://gitlab.seanergys.fz-juelich.de/software/demobus/-/archive/v0.2.1/demobus-v0.2.1.tar.gz"
    git = "https://gitlab.seanergys.fz-juelich.de/software/demobus.git"
    seanstack_resource = "seanergys-gitlab"

    # Only the git-fetched versions can carry the `deps` submodule, which holds
    # the path dependencies Cargo.toml declares. GitLab builds /-/archive/
    # tarballs with `git archive`, which writes deps/ as an empty directory, so
    # the sha256 releases below cannot build until those dependencies live in
    # the repository itself. Upstream CI sets GIT_SUBMODULE_STRATEGY=recursive.
    submodules = True

    license("MIT")

    # Development follows the upstream default branch.
    version("develop", branch="main")

    # Released versions are synchronized from upstream Git tags by `seanstack sync`,
    # which resolves each tag to its /-/archive/ tarball and records its sha256.
    version("0.2.1", sha256="3a5ce024c78f85ebdc9ca05bdbc6d3a445e782404173d4b9f04037f072cf2580")
    version("0.2", sha256="6e89c484e39542c3766197199bdc250f61b5db5a7c31d14c263f08bafe163762")
