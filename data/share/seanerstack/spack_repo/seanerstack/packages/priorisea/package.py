# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
import os

from spack_repo.builtin.build_systems.cmake import CMakePackage

from spack.package import *


class Priorisea(CMakePackage):
    """Job priority manager for SEANERGYS."""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/priorisea"
    git = "https://gitlab.seanergys.fz-juelich.de/software/priorisea.git"
    seanerstack_resource = "seanergys-gitlab"

    test_requires_compiler = True

    license("LGPL-3.0-only")

    version("main", branch="main", submodules=True)

    # Variant to enable building and running the tests
    variant("test", default=False, description="Enable Priorisea testing capabilities")

    depends_on("c", type="build")
    depends_on("cxx", type="build")
    depends_on("cmake@3.22:", type="build")
    depends_on("pkgconfig", type="build")
    depends_on("capnproto")
    depends_on("jansson")
    depends_on("sqlite")
    depends_on("seanerbus-cpp")
    depends_on("flux-core@0.81.0:")
    depends_on("cli11")
    depends_on("catch2@2.13.10", when="+test", type="build")
    #depends_on("seanerbroker", when="+test", type=("build", "run"))

    def cmake_args(self):
        return [self.define_from_variant("BUILD_TESTING", "test")]

    def test_priorisea_help(self):
        """run the priorisea CLI and print its help"""
        which(self.prefix.bin.priorisea, required=True)("--help", output=str, error=str)

    def test_plugin_installed(self):
        """the flux jobtap plugin is installed into flux's job-manager plugin dir"""
        plugin = join_path(self.prefix.lib, "flux", "job-manager", "plugins", "sea_priority.so")
        assert os.path.isfile(plugin), f"the sea_priority plugin was not installed at {plugin}"
