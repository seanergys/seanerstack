# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
from spack_repo.builtin.build_systems.cmake import CMakePackage

from spack.package import *


class SeanerbusCpp(CMakePackage):
    """The C++ client of the SeanerBUS, and the native module of its Python client"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-cpp"
    git = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-cpp.git"
    seanerstack_resource = "seanergys-gitlab"

    # fmt and the message schemas are submodules, and CMake needs both.
    submodules = True

    license("MIT")

    version("main", branch="main")

    variant("python", default=True, description="Build the native module of the Python client")

    depends_on("c", type="build")
    depends_on("cxx", type="build")
    depends_on("cmake@3.11:", type="build")
    depends_on("pkgconfig", type="build")
    depends_on("capnproto")

    with when("+python"):
        extends("python")
        depends_on("py-nanobind", type="build")

    def cmake_args(self):
        return [self.define_from_variant("REQUIRE_PYTHON", "python")]

    @run_after("install", when="+python")
    def install_python_module(self):
        # Upstream leaves these two steps to scikit-build: CMake installs the module
        # below the prefix, and only the wheel holds its __init__.py.
        module = join_path(self.prefix, self.spec["python"].package.platlib, "seanerbus_cpp_py")
        mkdirp(join_path(module, ".."))
        rename(join_path(self.prefix, "seanerbus_cpp_py"), module)
        install("src/seanerbus_cpp_py/__init__.py", module)
