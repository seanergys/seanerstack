# SPDX-License-Identifier: Apache-2.0
from spack_repo.builtin.build_systems.cmake import CMakePackage

from spack.package import *


class JobsDatabaseDaemon(CMakePackage):
    """The SeanerBUS consumer that records the Flux job lifecycle events in PostgreSQL"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/jobs-database-daemon"
    git = "https://gitlab.seanergys.fz-juelich.de/software/jobs-database-daemon.git"
    seanerstack_resource = "seanergys-gitlab"

    license("Apache-2.0")

    # Upstream takes seanerbus-cpp as a submodule, which Git leaves out here; the
    # recipe uses the seanerbus-cpp of Spack instead.
    version("main", branch="main")

    depends_on("c", type="build")
    depends_on("cxx", type="build")
    depends_on("cmake@3.20:", type="build")
    depends_on("capnproto")
    depends_on("fmt@12:")
    depends_on("postgresql")
    depends_on("seanerbus-cpp")

    @run_before("cmake")
    def link_dependencies(self):
        with working_dir(self.stage.source_path):
            # Upstream adds this directory as a subdirectory, which here finds the
            # installed client.
            mkdirp(join_path("lib", "seanerbus-cpp"))
            with open(join_path("lib", "seanerbus-cpp", "CMakeLists.txt"), "w", encoding="utf-8") as cmake:
                cmake.write("find_package(Seanerbus CONFIG REQUIRED GLOBAL)\n")

    def cmake_args(self):
        return [self.define("SEANERBUS_CPP_DIR", join_path(self.stage.source_path, "lib", "seanerbus-cpp"))]

    def test_binary_exists(self):
        """the daemon is installed"""
        which(self.prefix.bin.join("jobs-database-daemon"), required=True)
