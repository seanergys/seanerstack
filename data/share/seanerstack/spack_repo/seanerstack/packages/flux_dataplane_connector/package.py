# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
import os

from spack_repo.builtin.build_systems.cmake import CMakePackage

from spack.package import *


class FluxDataplaneConnector(CMakePackage):
    """Job priority manager for SEANERGYS."""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/flux-dataplane-connector"
    git = "https://gitlab.seanergys.fz-juelich.de/software/flux-dataplane-connector.git"
    seanerstack_resource = "seanergys-gitlab"

    root_cmakelists_dir = "job-manager-plugins"

    license("LGPL-3.0-only")

    version("main", branch="main")
    
    variant("pic", default=True, description="Build position-independent code")

    depends_on("c", type="build")
    depends_on("cxx", type="build")
    depends_on("cmake@3.22:", type="build")
    depends_on("pkgconfig", type="build")
    depends_on("capnproto")
    depends_on("jansson")
    depends_on("seanerbus-cpp")
    depends_on("flux-core@0.81.0:")
    
    def cmake_args(self):
        args = []
        if self.spec.satisfies("+pic"):
            args.append(self.define("CMAKE_POSITION_INDEPENDENT_CODE", True))
        return args
