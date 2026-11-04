# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
import os
import socket
import subprocess
import time

from spack_repo.builtin.build_systems.cargo import CargoPackage

from spack.package import *


class Seanerbus(CargoPackage):
    """The demonstrator SeanerBUS req/res and pub/sub broker"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/demobus"
    git = "https://gitlab.seanergys.fz-juelich.de/software/demobus.git"
    seanerstack_resource = "seanergys-gitlab"

    license("MIT")

    # The build script of internal_schemas runs the capnp compiler.
    depends_on("capnproto", type="build")
    # Cargo.toml has path dependencies on deps/internal/internal_schemas and
    # deps/internal/async, which upstream takes from seanerbus-rs as a submodule.
    depends_on("seanerbus-rs", type="build")

    # Development follows the upstream default branch.
    version("main", branch="main")

    # There are no releases yet, so `seanerstack package update` only checks that
    # the branch exists. GitLab writes its /-/archive/ tarballs with `git archive`,
    # which leaves a submodule path empty, so a release has to come from Git too.

    @run_before("build")
    def link_dependencies(self):
        with working_dir(self.stage.source_path):
            # Git leaves the path of a submodule as an empty directory.
            if os.path.isdir("deps"):
                os.rmdir("deps")
            os.symlink(self.spec["seanerbus-rs"].package.sources, "deps")

    def test_broker_accepts_a_connection(self):
        """start the broker and connect to it"""
        with socket.socket() as free:
            free.bind(("127.0.0.1", 0))
            port = free.getsockname()[1]
        # Upstream renamed the binary from demobus to seanerbroker on 2026-11-03.
        broker = subprocess.Popen([self.prefix.bin.seanerbroker, f"127.0.0.1:{port}"])
        try:
            for _ in range(100):
                assert broker.poll() is None, "the broker exited"
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=1).close()
                    return
                except OSError:
                    time.sleep(0.1)
            raise AssertionError(f"nothing accepts connections on port {port}")
        finally:
            broker.terminate()
            broker.wait()
