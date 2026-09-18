# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
from spack_repo.builtin.build_systems.cargo import CargoPackage

from spack.package import *


class Demobus(CargoPackage):
    """The demonstrator SeanerBUS req/res and pub/sub broker"""
    git = "git@gitlab.seanergys.fz-juelich.de:software/demobus.git"

    license("MIT")

    version("0.2.1", tag="v0.2.1")
    version("0.2", tag="v0.2")
