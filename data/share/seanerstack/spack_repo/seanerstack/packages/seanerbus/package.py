# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
from spack_repo.builtin.build_systems.cargo import CargoPackage

from spack.package import *


class Seanerbus(CargoPackage):
    """The demonstrator SeanerBUS req/res and pub/sub broker"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/demobus"
    url = "https://gitlab.seanergys.fz-juelich.de/software/demobus/-/archive/v0.2.1/demobus-v0.2.1.tar.gz"
    git = "https://gitlab.seanergys.fz-juelich.de/software/demobus.git"
    seanerstack_resource = "seanergys-gitlab"

    # Cargo.toml declares path dependencies on deps/internal/internal_schemas
    # and deps/internal/async, both inside the `deps` submodule, and Spack
    # clones submodules only when asked. Without this the build fails on the
    # unresolved path dependencies.
    #
    # This governs whether submodules are fetched, not how they are reached:
    # upstream .gitmodules pins `deps` to an absolute git@ URL, which a parent
    # cloned over HTTPS does not override.
    submodules = True

    license("MIT")

    # The build script of internal_schemas runs the capnp compiler.
    depends_on("capnproto", type="build")

    # Development follows the upstream default branch.
    version("main", branch="main")

    # Released versions are synchronized from upstream Git tags by `seanerstack sync`,
    # which resolves each tag to its /-/archive/ tarball and records its sha256.
    # They cannot be built yet: GitLab writes /-/archive/ tarballs with
    # `git archive`, which emits a submodule path as an empty directory, so only
    # the Git-fetched version above carries those dependencies.
    version("0.2.1", sha256="3a5ce024c78f85ebdc9ca05bdbc6d3a445e782404173d4b9f04037f072cf2580")
    version("0.2", sha256="6e89c484e39542c3766197199bdc250f61b5db5a7c31d14c263f08bafe163762")
