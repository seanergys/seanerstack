# SPDX-License-Identifier: Apache-2.0
import os

from spack_repo.builtin.build_systems.generic import Package

from spack.package import *


class EarSources(Package):
    """The sources of EAR, the Energy Aware Runtime, as SEANERGYS mirrors them.

    Access Daemon compiles parts of EAR into itself, so this package installs
    the source tree into prefix.src and builds nothing. The name ear is left
    for a build of EAR, which depends on Access Daemon.
    """

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/ear"
    git = "https://gitlab.seanergys.fz-juelich.de/software/ear.git"
    seanerstack_resource = "seanergys-gitlab"

    license("EPL-2.0")

    version("seanergys_mirror", branch="seanergys_mirror")

    def install(self, spec, prefix):
        install_tree("src", prefix.src)

    def test_sources_installed(self):
        """the sources that Access Daemon compiles are installed"""
        for name in ("common/system/file.c", "common/system/file.h", "metrics/common/msr.h"):
            path = join_path(self.prefix.src, name)
            assert os.path.isfile(path), f"{name} was not installed at {path}"
