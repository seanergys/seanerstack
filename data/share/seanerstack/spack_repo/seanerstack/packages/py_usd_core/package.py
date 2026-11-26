# SPDX-License-Identifier: Apache-2.0
from spack.package import depends_on, requires, version
from spack_repo.builtin.build_systems.python import PythonPackage


class PyUsdCore(PythonPackage):
    """OpenUSD Python bindings for reading and writing USD scenes."""

    homepage = "https://openusd.org/"
    version(
        "26.11",
        sha256="c412fa1d2a5dd0c7bc65484ffe34add8f3fc7b03510867e7e019bcaf06b76177",
        url=(
            "https://files.pythonhosted.org/packages/68/37/"
            "01c0d76d58fc95e24d786e8399cffe352eb147e8d41dea49a923fca9c961/"
            "usd_core-26.11-cp312-none-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl"
        ),
    )

    # The wheel is built for CPython 3.12 on glibc-based Linux x86-64.
    requires("platform=linux target=x86_64:")
    depends_on("python@3.12", type=("build", "run"))

    import_modules = ["pxr.Usd"]
