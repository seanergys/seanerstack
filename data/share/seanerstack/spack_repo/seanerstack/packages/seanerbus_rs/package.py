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

    # The msg crate takes its schemas from seanerbus-msg, as a submodule upstream.
    depends_on("seanerbus-msg", type=("build", "run"))

    @property
    def sources(self):
        """The directory that holds the crates."""
        return join_path(self.prefix, "share", "seanerbus-rs")

    def install(self, spec, prefix):
        install_tree(".", self.sources, ignore=lambda path: path == ".git" or path.startswith(".git/"))
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
