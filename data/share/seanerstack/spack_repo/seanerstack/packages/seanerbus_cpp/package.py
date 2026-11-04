# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
import os

from spack_repo.builtin.build_systems.cmake import CMakePackage

from spack.package import *


class SeanerbusCpp(CMakePackage):
    """The C++ client of the SeanerBUS, and the native module of its Python client"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-cpp"
    git = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-cpp.git"
    seanerstack_resource = "seanergys-gitlab"

    test_requires_compiler = True

    license("MIT")

    version("main", branch="main")

    variant("python", default=True, description="Build the native module of the Python client")

    depends_on("c", type="build")
    depends_on("cxx", type="build")
    depends_on("cmake@3.11:", type="build")
    depends_on("pkgconfig", type="build")
    depends_on("capnproto")
    # Upstream takes fmt and the message schemas as submodules.
    depends_on("fmt@12:")
    depends_on("seanerbus-msg", type="build")

    with when("+python"):
        extends("python")
        depends_on("py-nanobind", type="build")

    @run_before("cmake")
    def link_dependencies(self):
        with working_dir(self.stage.source_path):
            # Git leaves the path of a submodule as an empty directory.
            for path in ("schemas", join_path("lib", "fmt")):
                if os.path.isdir(path):
                    os.rmdir(path)
            os.symlink(self.spec["seanerbus-msg"].package.schemas, "schemas")
            # CMake adds lib/fmt as a subdirectory, which here finds the fmt of Spack.
            mkdirp(join_path("lib", "fmt"))
            with open(join_path("lib", "fmt", "CMakeLists.txt"), "w", encoding="utf-8") as cmake:
                cmake.write("find_package(fmt CONFIG REQUIRED GLOBAL)\n")

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

    def test_link_a_program(self):
        """compile a C program against the installed client, and run it"""
        with open("entity.c", "w", encoding="utf-8") as source:
            source.write(
                "#include <seanerbus/c/seanerbus.h>\n"
                "int main(void) {\n"
                "    seanerbus_entity_t* entity = NULL;\n"
                "    uint64_t upper = 0, lower = 0;\n"
                "    if (seanerbus_entity_create_from_u64(1, 2, &entity, NULL) != SEANERBUS_STATUS_OK) return 1;\n"
                "    if (seanerbus_entity_get_parts(entity, &upper, &lower, NULL) != SEANERBUS_STATUS_OK) return 2;\n"
                "    seanerbus_entity_destroy(entity);\n"
                "    return upper == 1 && lower == 2 ? 0 : 3;\n"
                "}\n"
            )
        libraries = find_libraries(["libseanerbus_c", "libseanerbus"], self.prefix, shared=False, recursive=True)
        libraries += find_libraries(["libcapnp", "libkj"], self.spec["capnproto"].prefix, recursive=True)
        which(self.spec["c"].package.cc, required=True)(
            "entity.c", "-o", "entity", f"-I{self.prefix.include}", *libraries.ld_flags.split(),
            *(f"-Wl,-rpath,{path}" for path in libraries.directories), "-lstdc++",
        )
        which("./entity", required=True)()

    def test_python_module(self):
        """import the native module of the Python client"""
        if "+python" not in self.spec:
            raise SkipTest("seanerbus-cpp was built without +python")
        self.spec["python"].command(
            "-c",
            "import seanerbus_cpp_py as bus; "
            "entity = bus.Entity('15a1a4c6-e83b-4699-bbdb-448b26edf1cc'); "
            "assert bus.Message(entity, 1, b'x').payload_type_as_int() == 1",
        )
