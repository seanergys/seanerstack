# SPDX-License-Identifier: Apache-2.0
from spack_repo.builtin.build_systems.bundle import BundlePackage

from spack.package import *


class SeanergysMeta(BundlePackage):
    """Meta package to install Seanergys software stack on different platforms"""

    # This is a version of the package recipe, not of an upstream source tree.
    version("2026.08")


