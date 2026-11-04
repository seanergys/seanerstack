# Copyright Spack Project Developers. See COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)
import socket
import subprocess
import time

from spack_repo.builtin.build_systems.cargo import CargoPackage

from spack.package import *


class Seanerbus(CargoPackage):
    """The demonstrator SeanerBUS req/res and pub/sub broker"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/demobus"
    url = "https://gitlab.seanergys.fz-juelich.de/software/demobus/-/archive/v0.2.1/demobus-v0.2.1.tar.gz"
    git = "https://gitlab.seanergys.fz-juelich.de/software/demobus.git"
    seanerstack_resource = "seanergys-gitlab"

    # Cargo.toml declares path dependencies on deps/internal/internal_schemas
    # and deps/internal/async, both inside the `deps` submodule, and Spack
    # clones submodules only when asked. Without this the build fails on the
    # unresolved path dependencies.
    #
    # This governs whether submodules are fetched, not how they are reached:
    # upstream .gitmodules pins `deps` to an absolute git@ URL, which a parent
    # cloned over HTTPS does not override.
    submodules = True

    license("MIT")

    # The build script of internal_schemas runs the capnp compiler.
    depends_on("capnproto", type="build")

    # Development follows the upstream default branch.
    version("main", branch="main")

    # There are no releases yet, so `seanerstack package update` only checks that
    # the branch exists. GitLab writes its /-/archive/ tarballs with `git archive`,
    # which leaves a submodule path empty, so a release has to come from Git too.

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
