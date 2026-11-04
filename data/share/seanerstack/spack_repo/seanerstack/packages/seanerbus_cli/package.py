# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
from spack_repo.builtin.build_systems.generic import Package

from spack.package import *


class SeanerbusCli(Package):
    """The command-line client of the SeanerBUS"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-cli"
    git = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-cli.git"
    seanerstack_resource = "seanergys-gitlab"

    license("MIT")

    version("main", branch="main")

    extends("python")
    depends_on("python@3.11:", type=("build", "run"))
    depends_on("seanerbus-python", type=("build", "run"))

    def install(self, spec, prefix):
        # pyproject.toml names a build with uv and takes the Python client from Git,
        # which Spack does here. The sources are plain Python.
        install_tree("src/seanerbus_cli", join_path(prefix, spec["python"].package.platlib, "seanerbus_cli"))
        mkdirp(prefix.bin)
        script = join_path(prefix.bin, "seanerbus")
        with open(script, "w", encoding="utf-8") as launcher:
            launcher.write(f"#!{spec['python'].command.path}\nfrom seanerbus_cli import main\n\nmain()\n")
        set_executable(script)

    def test_command_line(self):
        """run the command and list its subcommands"""
        seanerbus = which(join_path(self.prefix.bin, "seanerbus"), required=True)
        assert "subscribe" in seanerbus("--help", output=str)
