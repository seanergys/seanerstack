# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

import os
from spack_repo.builtin.build_systems.makefile import MakefilePackage
from spack.package import *

class AccessDaemon(MakefilePackage):
    """Linux daemon that exposes hardware metrics and actuators through SeanerBUS."""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/access-daemon"
    git = "https://gitlab.seanergys.fz-juelich.de/software/access-daemon.git"
    seanerstack_resource = "seanergys-gitlab"

    # Access Daemon compiles EAR sources. They come from the ear-sources
    # package, not from the repository's external/ear submodule.
    version("main", branch="main")

    depends_on("c", type="build")
    depends_on("ear-sources", type="build")
    depends_on("seanerbus-cpp")
    depends_on("uuid")

    # The recursive Makefiles build objects and their consumers in sequence.
    parallel = False

    _bindings = ("libseanerbus_c", "libseanerbus")

    @property
    def make_args(self):
        bus = self.spec["seanerbus-cpp"]
        libs = find_libraries(self._bindings, bus.prefix, recursive=True)
        extra_libs = ""
        if not libs:
            libs = find_libraries(self._bindings, bus.prefix, shared=False, recursive=True)
            # Static bindings need their transitive libraries on the link line.
            capnp = find_libraries(
                ["libcapnp", "libkj"], bus["capnproto"].prefix, recursive=True
            )
            if len(capnp) != 2:
                raise InstallError("Cap'n Proto libraries libcapnp and libkj are required")
            extra_libs = f" {capnp.ld_flags} -lstdc++ -pthread"
        if len(libs) != len(self._bindings):
            raise InstallError("seanerbus-cpp must provide libseanerbus_c and libseanerbus")

        return [
            f"CC={spack_cc}",
            f"PWD={self.stage.source_path}",
            f"PREFIX={self.prefix}",
            f"EAR_SRCDIR={self.spec['ear-sources'].prefix.src}",
            f"SEABUS_PREFIX={bus.prefix}",
            f"SEABUS_LDFLAGS={libs.ld_flags}{extra_libs} -luuid",
        ]

    def patch(self):
        ear = self.spec["ear-sources"].prefix.src
        # Some stubs are symlinks into the submodule: point them at the same
        # files of the ear-sources package.
        submodule = os.path.abspath(join_path("external", "ear", "src"))
        for root, _, files in os.walk(join_path("external", "stubs")):
            for name in files:
                link = join_path(root, name)
                if not os.path.islink(link):
                    continue
                target = os.path.normpath(join_path(os.path.abspath(root), os.readlink(link)))
                if os.path.commonpath([target, submodule]) != submodule:
                    continue
                os.unlink(link)
                symlink(join_path(ear, os.path.relpath(target, submodule)), link)

    @property
    def build_targets(self):
        # A develop checkout may contain outputs built with different flags.
        return ["-B", *self.make_args]

    @property
    def install_targets(self):
        return ["install", *self.make_args]

    @run_after("install")
    def fix_seanerbus_links(self):
        # The Makefiles assume shared bindings in lib, but Spack may install
        # them elsewhere or provide static archives.
        bus = self.spec["seanerbus-cpp"].prefix
        shared = find_libraries(self._bindings, bus, recursive=True)
        for name in self._bindings:
            link = join_path(self.prefix.lib.accessd, f"{name}.so")
            if os.path.islink(link):
                os.unlink(link)
        for library in shared:
            symlink(library, join_path(self.prefix.lib.accessd, os.path.basename(library)))

    def setup_run_environment(self, env):
        env.prepend_path("PATH", self.prefix.sbin)
