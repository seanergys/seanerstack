# SPDX-License-Identifier: Apache-2.0
import os

from spack_repo.builtin.build_systems.generic import Package
from spack_repo.seanerstack.packages.seanerbus_msg.package import SeanerbusMsg

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

    @property
    def sources(self):
        """The directory that holds the crates."""
        return join_path(self.prefix, "share", "seanerbus-rs")

    @run_before("install")
    def fetch_schemas(self):
        # The msg crate covers the messages of the schemas at the commit of its
        # submodule msg/schemas, and seanerbus-msg@main may already have more.
        # The submodule URL is an SSH one, so the schemas come from the HTTPS URL
        # of seanerbus-msg instead, which the Git credentials of the state cover.
        git = which("git", required=True)
        with working_dir(self.stage.source_path):
            commit = git("rev-parse", "HEAD:msg/schemas", output=str).strip()
        # Git leaves the path of a submodule as an empty directory.
        with working_dir(join_path(self.stage.source_path, "msg", "schemas"), create=True):
            git("init", "--quiet")
            git("fetch", "--quiet", "--depth", "1", SeanerbusMsg.git, commit)
            git("checkout", "--quiet", "FETCH_HEAD")

    def install(self, spec, prefix):
        install_tree(".", self.sources, ignore=lambda path: ".git" in path.split(os.sep))

    def test_crates_are_complete(self):
        """check that the crates that others build are there, and the schemas compile"""
        for crate in ("internal/internal_schemas", "internal/async", "msg"):
            assert os.path.isfile(join_path(self.sources, crate, "Cargo.toml")), f"{crate} is missing"
        capnp = which(join_path(self.spec["capnproto"].prefix.bin, "capnp"), required=True)
        capnp("compile", "-o-", join_path(self.sources, "msg", "schemas", "msg.capnp"), output=os.devnull)
