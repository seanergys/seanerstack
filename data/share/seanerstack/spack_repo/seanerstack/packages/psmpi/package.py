# SPDX-License-Identifier: Apache-2.0
import os
import subprocess

from spack_repo.builtin.build_systems.autotools import AutotoolsPackage

from spack.package import *


class Psmpi(AutotoolsPackage):
    """ParaStation is a robust and efficient cluster middleware, consisting of a
    high-performance communication layer (MPI) and a sophisticated management
    layer. This package provides its upper communication layer based on MPICH.
    """

    homepage = "https://par-tec.com"
    git = "https://gitlab.seanergys.fz-juelich.de/software/psmpi.git"
    seanerstack_resource = "seanergys-gitlab"

    maintainers = ["pickartz1", "happ1"]

    license("QPL")

    version("session-spawn-prototype", branch="mr-session-spawn-update")
    version("master", branch="master")
    version("5.14.0-1", tag="5.14.0-1")
    version("5.13.1-1", tag="5.13.1-1")


    depends_on("autoconf", type="build")
    depends_on("automake", type="build")
    depends_on("libtool", type="build")
    depends_on("m4", type="build")

    depends_on("pscom +ucp")

    depends_on("hwloc", when="+hwloc")
    depends_on("hcoll", when="+hcoll")
    depends_on("hydra", when="+hydra")
    depends_on("cuda", when="+cuda")
    depends_on("pmix", when="+pmix")
    depends_on("ucc", when="+ucc")

    variant("allin", default=False, description="Pscom all-in build")
    variant("hwloc", default=False, description="Hwloc")
    variant("hcoll", default=False, description="Hcoll")
    variant("hydra", default=False, description="Hydra")
    variant("pmix", default=True, description="PMIx")
    variant("cuda", default=False, description="Cuda")
    variant("threading", default=True, description="Threading")
    variant("msa", default=False, description="MSA awareness")
    variant("ucc", default=True, description="UCC")

    conflicts("+hydra", when="+pmix")

    confsets = ("none", "default", "gcc", "intel", "icc", "nvhpc", "devel", "debug")
    variant(
        "confset",
        default="default",
        description="Predefined configuration sets",
        values=confsets,
        multi=False,
    )

    filter_compiler_wrappers("mpicc", "mpicxx", "mpif77", "mpif90", "mpifort", relative_root="bin")

    def setup_run_environment(self, env):
        env.set("MPICC", join_path(self.prefix.bin, "mpicc"))
        env.set("MPICXX", join_path(self.prefix.bin, "mpic++"))
        env.set("MPIF77", join_path(self.prefix.bin, "mpif77"))
        env.set("MPIF90", join_path(self.prefix.bin, "mpif90"))

    def setup_dependent_build_environment(self, env, dependent_spec):
        self.setup_run_environment(env)

        env.set("MPICH_CC", spack_cc)
        env.set("MPICH_CXX", spack_cxx)
        env.set("MPICH_F77", spack_f77)
        env.set("MPICH_F90", spack_fc)
        env.set("MPICH_FC", spack_fc)

    def setup_dependent_package(self, module, dependent_spec):
        spec = self.spec
        spec.mpicc = join_path(self.prefix.bin, "mpicc")
        spec.mpicxx = join_path(self.prefix.bin, "mpic++")
        spec.mpifc = join_path(self.prefix.bin, "mpif90")
        spec.mpif77 = join_path(self.prefix.bin, "mpif77")

        spec.mpicxx_shared_libs = [
            join_path(self.prefix.lib, "libmpicxx.{0}".format(dso_suffix)),
            join_path(self.prefix.lib, "libmpi.{0}".format(dso_suffix)),
        ]

    def setup_build_environment(self, env):
        env.unset("F90")
        env.unset("F90FLAGS")

        # https://bugzilla.redhat.com/show_bug.cgi?id=1795817
        if self.spec.satisfies("%gcc@10:"):
            env.set("FFLAGS", "-fallow-argument-mismatch")
        if self.spec.satisfies("%clang@11:"):
            env.set("FFLAGS", "-fallow-argument-mismatch")

    def autoreconf(self, spec, prefix):
        bash = which("bash")
        bash("./autogen.sh")

    @when("@:5.4.11")
    def autoreconf(self, spec, prefix):
        autoreconf = which("autoreconf")
        autoreconf("-ifv")

    def configure_args(self):
        spec = self.spec
        print(spec)
        args = []

        if "+hydra" in spec:
            args.extend(self.enable_or_disable("hydra"))
        if "+hwloc" in spec:
            args.extend(self.with_or_without("hwloc"))
        if "+hcoll" in spec:
            args.extend(self.with_or_without("hcoll"))
        if "+threading" in spec:
            args.extend(self.enable_or_disable("threading"))
        if "+cuda" in spec:
            args.extend(self.with_or_without("cuda"))
        if "+pmix" in spec:
            args.extend(self.with_or_without("pmix"))
        if "+ucc" in spec:
            args.extend(self.with_or_without("ucc"))
        if "+msa" in spec:
            args.extend(self.enable_or_disable("msa-awareness"))
        if "+allin" in spec:
            subprocess.call(["git", "clone", "https://gitlab.seanergys.fz-juelich.de/software/pscom"])
            proj_root = self.stage.source_path
            pscom_src = os.path.join(proj_root, "pscom")
            args.extend(["--with-pscom-allin={0}".format(pscom_src)])
            args.extend(["--with-pscom-builtin={0}".format(",".join(["ucp"]))])
        else:
            args.append("--with-pscom={0}".format(spec["pscom"].prefix))

        if self.spec.satisfies("%intel"):
            args.extend(["--with-confset=intel"])
        else:
            args.extend(["--with-confset={0}".format(self.spec.variants["confset"].value)])

        # Write the VERSION file
        with open(self.stage.source_path + "/VERSION", "w") as f:
            f.write("psmpi-{0}".format(self.version))

        return args

    # TODO: still not installing if tests fail
    @run_after("install")
    @on_package_attributes(run_tests=True)
    def test(self):
        make("check")
