# SPDX-License-Identifier: Apache-2.0
import os

from spack_repo.builtin.build_systems.generic import Package

from spack.package import *


class SeanerbusMsg(Package):
    """The Cap'n Proto schemas of the SeanerBUS messages"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-msg"
    git = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-msg.git"
    seanerstack_resource = "seanergys-gitlab"

    version("main", branch="main")

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
