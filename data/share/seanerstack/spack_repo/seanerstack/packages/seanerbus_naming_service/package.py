# SPDX-License-Identifier: Apache-2.0
import os
import socket

from spack_repo.builtin.build_systems.cargo import CargoPackage

from spack.package import *


class SeanerbusNamingService(CargoPackage):
    """The naming server of the SeanerBUS, which resolves names to entities"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-naming-service"
    git = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-naming-service.git"
    seanerstack_resource = "seanergys-gitlab"

    license("MIT")

    # There are no releases yet.
    version("main", branch="main")

    # The sources call Vec::push_mut, which is stable since Rust 1.95.
    depends_on("rust@1.95:", type="build")
    # rustc links every binary by calling cc, and Spack gives the build a
    # compiler only for a language the package itself depends on.
    depends_on("c", type="build")
    # The build scripts of the msg and internal_schemas crates run the capnp compiler.
    depends_on("capnproto", type="build")
    # Cargo.toml has path dependencies on deps/client, deps/msg and
    # deps/internal/internal_schemas, which upstream takes from seanerbus-rs as a submodule.
    depends_on("seanerbus-rs", type="build")

    @run_before("build")
    def link_dependencies(self):
        with working_dir(self.stage.source_path):
            # Git leaves the path of a submodule as an empty directory.
            if os.path.isdir("deps"):
                os.rmdir("deps")
            os.symlink(self.spec["seanerbus-rs"].package.sources, "deps")

    def test_server_reads_its_services(self):
        """start the server with one service in services.json and nothing to connect to"""
        # The server reads services.json from its working directory before it connects to the broker.
        with open("services.json", "w", encoding="utf-8") as services:
            services.write('[{"entity": "57499619-8305-44b8-ae52-c75b93d20ff9", "name": {"sensor": "freq"}}]')
        with socket.socket() as free:
            free.bind(("127.0.0.1", 0))
            port = free.getsockname()[1]
        server = which(join_path(self.prefix.bin, "naming_server"), required=True)
        output = server(f"127.0.0.1:{port}", output=str, error=str, fail_on_error=False)
        assert server.returncode != 0, f"the server ran without a broker: {output}"
        # A services.json it cannot read would stop it before the connection.
        assert "ConnectionRefused" in output, output
