# SPDX-License-Identifier: Apache-2.0
import os

from spack_repo.builtin.build_systems.generic import Package

from spack.package import *


class SeanerbusMsg(Package):
    """The Cap'n Proto schemas of the SeanerBUS messages"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-msg"
    git = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-msg.git"
    seanerstack_resource = "seanergys-gitlab"

    # The packages that build from the schemas take them as a build dependency,
    # so Spack may install a commit of them for each package that needs another:
    # see max_dupes in the concretizer settings that toolchain bootstrap writes.
    tags = ["build-tools"]

    version("main", branch="main")
    # The commit of the submodule msg/schemas of seanerbus-rs.
    version("e74755c", commit="e74755ce1c4d564f3f7bdb67556ba9c32109f097")

    # Whoever uses the schemas compiles them with capnp.
    depends_on("capnproto", type=("build", "run"))

    @property
    def schemas(self):
        """The directory that holds the schemas."""
        return join_path(self.prefix, "share", "seanerbus-msg")

    def install(self, spec, prefix):
        mkdirp(self.schemas)
        install("msg.capnp", self.schemas)

    def test_schemas_compile(self):
        """compile the installed schemas with capnp"""
        capnp = which(join_path(self.spec["capnproto"].prefix.bin, "capnp"), required=True)
        capnp("compile", "-o-", join_path(self.schemas, "msg.capnp"), output=os.devnull)
