# SPDX-License-Identifier: Apache-2.0
from spack_repo.builtin.build_systems.bundle import BundlePackage

from spack.package import *


class Seanerbus(BundlePackage):
    """The SeanerBUS: its broker and its C++ and Python clients"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software"

    # The packages it brings in follow their main branches.
    version("main")

    depends_on("seanerbroker@main", type="run")
    depends_on("seanerbus-cpp@main", type="run")
    depends_on("seanerbus-python@main", type="run")

    # A test of the broker with its clients would be an end-to-end test, which
    # belongs in seanertest, and each package here has its own.
