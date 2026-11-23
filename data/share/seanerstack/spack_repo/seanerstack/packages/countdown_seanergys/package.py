from spack.package import *
from spack_repo.builtin.build_systems.cmake import CMakePackage


class CountdownSeanergys(CMakePackage):
    """COUNTDOWN with the SEANERGYS Access Daemon backend"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/countdown"
    git = "https://gitlab.seanergys.fz-juelich.de/software/countdown.git"
    seanerstack_resource = "seanergys-gitlab"

    license("BSD-3-Clause")

    version("main", branch="main")

    variant("cuda", default=False, description="Enable CUDA monitoring on NVIDIA GPUs")

    depends_on("c", type="build")
    depends_on("cmake@3.13:", type="build")
    depends_on("mpi")
    depends_on("hwloc")
    depends_on("cuda", when="+cuda")
    depends_on("libfort+shared")

    def cmake_args(self):
        return [
            self.define_from_variant("CNTD_ENABLE_CUDA", "cuda"),
            self.define("CNTD_ENABLE_TESTS", self.run_tests),
        ]
