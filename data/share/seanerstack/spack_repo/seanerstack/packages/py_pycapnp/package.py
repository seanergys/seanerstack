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

    def test_message_round_trip(self):
        """write a message and read it back, with a schema parsed at run time"""
        with open("point.capnp", "w", encoding="utf-8") as schema:
            schema.write("@0xd5a7c9e3f1b80412;\nstruct Point {\n  x @0 :Int32;\n}\n")
        self.spec["python"].command(
            "-c",
            "import capnp; point = capnp.load('point.capnp').Point; "
            "data = point.new_message(x=7).to_bytes(); "
            "assert point.from_bytes(data).__enter__().x == 7",
        )
