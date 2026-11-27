# SPDX-License-Identifier: Apache-2.0
import os

from spack_repo.builtin.build_systems.generic import Package

from spack.package import *


class SeanerbusRs(Package):
    """The Rust crates of the SeanerBUS, as sources for the packages that build them"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-rs"
    git = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-rs.git"
    seanerstack_resource = "seanergys-gitlab"

    license("MIT")

    version("main", branch="main")

    # Whoever builds the crates compiles the schemas with capnp.
    depends_on("capnproto", type=("build", "run"))
    # The msg crate covers the messages of the schemas at the commit of its
    # submodule msg/schemas, which upstream takes from seanerbus-msg, and
    # seanerbus-msg@main may already have more. A build dependency only, so
    # seanerbus-cpp and seanerbus-python can take another commit of it.
    depends_on("seanerbus-msg@e74755c", type="build")

    @property
    def sources(self):
        """The directory that holds the crates."""
        return join_path(self.prefix, "share", "seanerbus-rs")

    def install(self, spec, prefix):
        install_tree(".", self.sources, ignore=lambda path: ".git" in path.split(os.sep))
        schemas = join_path(self.sources, "msg", "schemas")
        # Git leaves the path of a submodule as an empty directory.
        if os.path.isdir(schemas):
            os.rmdir(schemas)
        install_tree(spec["seanerbus-msg"].package.schemas, schemas)

    def test_crates_are_complete(self):
        """check that the crates that others build are there, and the schemas compile"""
        for crate in ("internal/internal_schemas", "internal/async", "msg"):
            assert os.path.isfile(join_path(self.sources, crate, "Cargo.toml")), f"{crate} is missing"
        capnp = which(join_path(self.spec["capnproto"].prefix.bin, "capnp"), required=True)
        capnp("compile", "-o-", join_path(self.sources, "msg", "schemas", "msg.capnp"), output=os.devnull)
