# SPDX-License-Identifier: Apache-2.0

from spack_repo.builtin.build_systems.cmake import CMakePackage

from spack.package import *


class Pscom(CMakePackage):
    """ParaStation is a robust and efficient cluster middleware, consisting of a
    high-performance communication layer (MPI) and a sophisticated management
    layer. This package provides its low-level communication layer pscom.
    """

    homepage = "https://par-tec.com"
    git = "https://gitlab.seanergys.fz-juelich.de/software/pscom.git"
    seanerstack_resource = "seanergys-gitlab"

    maintainers = ["pickartz1", "happ1"]

    license("QPL")

    version("6.1.1-1", tag="6.1.1-1")
    version("6.0.1-1", tag="6.0.1-1")

    variant(
        "build_type",
        default="RelWithDebInfo",
        description="Specify CMake build type",
        values=("Release", "RelWithDebInfo", "MinSizeRel", "Debug"),
    )
    variant("cuda", default=False, description="Compile with CUDA support")
    variant("openib", default=False, description="Compile with native IB Verbs support")
    variant("ucp", default=True, description="Compile with UCX support")
    variant("psm2", default=False, description="Compile with PSM2 support")
    variant("portals4", default=False, description="Compile with Portals4 support")
    variant("utest", default=False, description="Enable unit tests")
    variant("rrcomm", default=False, description="Compile with RRComm Precon support")

    depends_on("cmake@3.10.0:", type="build")
    depends_on("rrcomm", when="+rrcomm")
    depends_on("cmocka", when="+utest")
    depends_on("cuda", when="+cuda")
    depends_on("opa-psm2", when="+psm2")
    depends_on("rdma-core", when="+openib")
    depends_on("ucx", when="+ucp")


    # We need to explicitly create a VERSION file to obtain the correct version
    # information during the CMake phase.
    def cmake(self, spec, prefix):
        # Write the VERSION file
        with open(self.root_cmakelists_dir + "/VERSION", "w") as f:
            f.write("pscom-{0}".format(self.version))

        # Run CMake as usual
        super(Pscom, self).cmake(spec, prefix)

    def cmake_args(self):
        variant_bool = lambda feature: "ON" if feature in self.spec else "OFF"

        args = [
            "-DCUDA_ENABLED={0}".format(variant_bool('+cuda')),
            "-DRRCOMM_PRECON_ENABLED={0}".format(variant_bool('+rrcomm')),
            "-DOPENIB_ENABLED={0}".format(variant_bool('+openib')),
            "-DUCP_ENABLED={0}".format(variant_bool('+ucp')),
            "-DPSM2_ENABLED={0}".format(variant_bool('+psm2')),
            "-DPORTALS4_ENABLED={0}".format(variant_bool('+portals4')),
            "-DUTEST_ENABLED={0}".format(variant_bool('+utest')),
        ]

        return args
