# SPDX-License-Identifier: Apache-2.0
import os

from spack_repo.builtin.build_systems.cmake import CMakePackage

from spack.package import *


class SeanerbusHta(CMakePackage):
    """The SeanerBUS HTA time series database, a SeanerBUS client that stores metrics with hta"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/hta-database-daemon"
    git = "https://gitlab.seanergys.fz-juelich.de/software/hta-database-daemon.git"
    seanerstack_resource = "seanergys-gitlab"

    license("MIT")

    # Of the submodules only lib/hta, on GitHub, is fetched. lib/cpp is the
    # seanerbus-cpp package, which this recipe takes from Spack instead.
    version("main", branch="main", submodules=lambda pkg: ["lib/hta"])

    depends_on("c", type="build")
    depends_on("cxx", type="build")
    depends_on("cmake@3.11:", type="build")
    depends_on("pkgconfig", type="build")
    depends_on("capnproto")
    depends_on("fmt@12:")
    depends_on("seanerbus-cpp")

    @run_before("cmake")
    def link_dependencies(self):
        with working_dir(self.stage.source_path):
            # Git leaves the path of a submodule as an empty directory. CMake adds
            # lib/cpp as a subdirectory, which here finds the installed client.
            mkdirp(join_path("lib", "cpp"))
            with open(join_path("lib", "cpp", "CMakeLists.txt"), "w", encoding="utf-8") as cmake:
                cmake.write("find_package(Seanerbus CONFIG REQUIRED GLOBAL)\n")

    def test_binary_exists(self):
        """the database binary is installed"""
        assert os.path.exists(self.prefix.bin.join("hta-database-daemon"))
