# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
from spack_repo.builtin.build_systems.python import PythonPackage

from spack.package import *


class PyPycapnp(PythonPackage):
    """Python bindings for the Cap'n Proto serialization library"""

    homepage = "https://capnproto.github.io/pycapnp/"
    pypi = "pycapnp/pycapnp-2.2.4.tar.gz"

    license("BSD-2-Clause")

    version("2.2.4", sha256="a598bd3952de76a803a53b845c8c300828338b949946d49f8af716328cda0a1a")

    depends_on("c", type="build")
    depends_on("cxx", type="build")
    depends_on("py-setuptools", type="build")
    depends_on("py-cython", type="build")
    depends_on("py-pkgconfig", type="build")
    depends_on("pkgconfig", type="build")
    depends_on("capnproto")
