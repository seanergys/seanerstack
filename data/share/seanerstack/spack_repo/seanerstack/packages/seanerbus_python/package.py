# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
from spack_repo.builtin.build_systems.generic import Package

from spack.package import *


class SeanerbusPython(Package):
    """The Python client of the SeanerBUS"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-py"
    git = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-py.git"
    seanerstack_resource = "seanergys-gitlab"

    # The message schemas are a submodule, and the package loads them at run time.
    submodules = True

    license("MIT")

    version("main", branch="main")

    extends("python")
    depends_on("python@3.11:", type=("build", "run"))
    depends_on("py-pycapnp", type=("build", "run"))
    depends_on("seanerbus-cpp+python", type=("build", "run"))

    def install(self, spec, prefix):
        # Plain Python and its schemas. pyproject.toml only names a build with uv,
        # and takes seanerbus_cpp_py from Git, which Spack does here.
        install_tree("src/seanerbus", join_path(prefix, spec["python"].package.platlib, "seanerbus"))
