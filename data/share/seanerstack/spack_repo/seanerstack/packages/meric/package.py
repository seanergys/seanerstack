# SPDX-License-Identifier: Apache-2.0
from spack_repo.builtin.build_systems.waf import WafPackage

from spack.package import *

class Meric(WafPackage):
    """MERIC runtime system for parallel applications energy consumption measurement, dynamic behavior detection, and dynamic power-management knobs tuning according to the READEX approach."""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/meric"
    git = "https://gitlab.seanergys.fz-juelich.de/software/meric.git"
    seanerstack_resource = "seanergys-gitlab"

    license("BSD-3-Clause")

    version("seanergys", branch="seanergys")

    depends_on("cxx", type="build")
    depends_on("pkgconfig", type="build")
    depends_on("capnproto")
    depends_on("seanerbus-cpp")
