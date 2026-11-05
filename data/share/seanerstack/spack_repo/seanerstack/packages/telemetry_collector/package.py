# SPDX-License-Identifier: Apache-2.0
import subprocess
import time

from spack_repo.builtin.build_systems.cmake import CMakePackage

from spack.package import *


class TelemetryCollector(CMakePackage):
    """The SEANERGYS Telemetry Collector, and its plugins"""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/telemetry-collector"
    git = "https://gitlab.seanergys.fz-juelich.de/software/telemetry-collector.git"
    seanerstack_resource = "seanergys-gitlab"

    # There are no releases yet.
    version("main", branch="main")

    depends_on("cxx", type="build")
    depends_on("cmake@3.13:", type="build")
    depends_on("pkgconfig", type="build")

    depends_on("seanerbus-cpp")
    depends_on("capnproto")
    depends_on("uuid")
    depends_on("fmt@12:")
    depends_on("spdlog@1.16:")
    depends_on("yaml-cpp@0.8")
    depends_on("net-snmp@5.9.4:")

    def patch(self):
        # The plugins still name the broker by the scheme that seanerbus-cpp dropped
        # when it renamed DemoBUS to SeanerBroker.
        filter_file("demobus://", "seanerbroker://", *find("plugins", "*.cpp"), string=True, backup=False)

    def cmake_args(self):
        return [
            # Otherwise CMake clones what it does not find from GitHub during the build.
            self.define("USE_SYSTEM_DEPENDENCIES", True),
            # Upstream names no provider for spdlog, so it would never find this one.
            self.define("DEPENDENCY_PROVIDER_spdlog", "spdlog"),
        ]

    def test_usage(self):
        """run the collector without a configuration"""
        collector = which(join_path(self.prefix.bin, "telemetry_collector"), required=True)
        assert "usage:" in collector(output=str, error=str, fail_on_error=False)

    def test_plugins_load(self):
        """load each plugin, which stops at its missing configuration before it connects"""
        for plugin in ("ad", "mock", "snmp", "sysfs", "tester"):
            libraries = find(self.prefix, f"{plugin}.so")
            assert libraries, f"{plugin}.so is not installed"
            with open(f"{plugin}.yaml", "w", encoding="utf-8") as config:
                config.write(
                    "seanerbus:\n  url: 127.0.0.1:1\nplugins:\n"
                    f"  - path: {libraries[0]}\n    config: {plugin}-missing.yaml\n"
                    f"    uuid: e94e6e91-a83d-4e04-a147-aab3860d0cd0\n    name: {plugin}\n"
                )
            with open(f"{plugin}.log", "w+", encoding="utf-8") as log:
                # The collector keeps running after a plugin failed to load.
                collector = subprocess.Popen(
                    [self.prefix.bin.telemetry_collector, f"{plugin}.yaml"], stdout=log, stderr=subprocess.STDOUT
                )
                try:
                    for _ in range(100):
                        log.seek(0)
                        output = log.read()
                        if "Failed to load config file" in output:
                            break
                        assert collector.poll() is None, f"the collector exited: {output}"
                        time.sleep(0.1)
                    else:
                        raise AssertionError(f"{plugin} did not load: {output}")
                finally:
                    collector.kill()
                    collector.wait()
