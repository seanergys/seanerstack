from spack.package import *
from spack_repo.builtin.build_systems.cmake import CMakePackage


class CountdownSeanergys(CMakePackage):
    """COUNTDOWN with the SEANERGYS Access Daemon backend"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/countdown"
    git = "https://gitlab.seanergys.fz-juelich.de/software/countdown.git"
    seanerstack_resource = "seanergys-gitlab"

    license("BSD-3-Clause")

    version("main", branch="main")
    version("2.0.0", tag="v2.0.0", commit="b6a5257418278e20feb60fc776f4455ae0dcd6cb")

    variant("access_daemon", default=False, description="Enable the Access Daemon backend")
    variant("cuda", default=False, description="Enable CUDA monitoring on NVIDIA GPUs")

    depends_on("access-daemon", when="+access_daemon")
    depends_on("c", type="build")
    depends_on("cmake@3.13:", type="build")
    depends_on("cuda", when="+cuda")
    depends_on("hwloc")
    depends_on("libfort+shared")
    depends_on("mpi")
    depends_on("seanerbus-cpp", when="+access_daemon")

    def cmake_args(self):
        args = [
            self.define_from_variant("CNTD_ENABLE_ACCESS_DAEMON", "access_daemon"),
            self.define_from_variant("CNTD_ENABLE_CUDA", "cuda"),
            self.define("CNTD_ENABLE_TESTS", self.run_tests),
        ]
        if "+access_daemon" in self.spec:
            args.extend(
                [
                    self.define("EASYBUS_PREFIX", self.spec["access-daemon"].prefix),
                    self.define("SEANERBUS_PREFIX", self.spec["seanerbus-cpp"].prefix),
                ]
            )
        return args

    def test_shared_library_dependencies(self):
        """Check that the loader can find the MPI interposer's shared dependencies."""
        ldd = which("ldd", required=True)
        ldd.add_default_env("LC_ALL", "C")
        output = ldd(join_path(self.prefix.lib, "libcntd.so"), output=str)
        assert "not found" not in output, output
