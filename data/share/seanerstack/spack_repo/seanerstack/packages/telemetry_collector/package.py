# SPDX-License-Identifier: Apache-2.0
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from spack_repo.builtin.build_systems.cmake import CMakeBuilder as BaseCMakeBuilder
from spack_repo.builtin.build_systems.cmake import CMakePackage

from spack.package import *


class TelemetryCollector(CMakePackage):
    """The SEANERGYS Telemetry Collector, and its plugins."""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/telemetry-collector"
    git = "https://gitlab.seanergys.fz-juelich.de/software/telemetry-collector.git"
    seanerstack_resource = "seanergys-gitlab"

    version("main", branch="main")

    variant("ad", default=True, description="Build the AD plugin")
    variant("mock", default=True, description="Build the Mock plugin")
    variant("sysfs", default=True, description="Build the Sysfs plugin")
    variant("tester", default=True, description="Build the Tester plugin")
    variant("snmp", default=False, description="Build the SNMP plugin")

    depends_on("cxx", type="build")
    depends_on("cmake@3.21:", type="build")
    depends_on("pkgconfig", type="build")
    depends_on("googletest", type="test")
    depends_on("python@3.6:", type="test")

    depends_on("seanerbus-cpp")
    depends_on("capnproto")
    depends_on("uuid")
    depends_on("fmt@12:")
    depends_on("spdlog@1.16:")
    depends_on("yaml-cpp@0.8")
    depends_on("net-snmp@5.9.4:", when="+snmp")

    @property
    def selected_plugins(self):
        return [
            plugin for plugin in ("ad", "mock", "snmp", "sysfs", "tester")
            if f"+{plugin}" in self.spec
        ]

    def test_usage(self):
        """Check the usage message and exit status without a configuration."""
        result = subprocess.run(
            [self.prefix.bin.telemetry_collector],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            timeout=10,
        )
        assert result.returncode == 1 and "usage:" in result.stdout, result.stdout

    def test_plugins_load(self):
        """Check that each installed plugin loads and reports a missing configuration."""
        for plugin in self.selected_plugins:
            self._check_plugin(plugin, "Failed to load config file")

    def test_mock_lifecycle(self):
        """Check that mock runs and unloads cleanly without external services."""
        if "~mock" in self.spec:
            return
        uuid = "e94e6e91-a83d-4e04-a147-aab3860d0cd0"
        output = self._check_plugin("mock", f"mock ({uuid})", {"name": "mock"})
        assert "Stopping plugin:" in output and "Unloading plugin:" in output, output

    def _check_plugin(self, plugin, expected_message, settings=None):
        libraries = find(self.prefix, f"{plugin}.so")
        assert libraries, f"{plugin}.so is not installed"

        directory = Path(tempfile.mkdtemp(prefix=f"{plugin}-", dir=os.getcwd()))
        plugin_config = directory / "plugin.yaml"
        collector_config = directory / "telemetry_collector.yaml"
        log_path = directory / "collector.log"
        if settings is not None:
            plugin_config.write_text(json.dumps(settings), encoding="utf-8")
        collector_config.write_text(
            json.dumps(
                {
                    "seanerbus": {"url": "seanerbroker://127.0.0.1:1"},
                    "plugin_status_interval_ms": 100 if settings is not None else 0,
                    "plugins": [
                        {
                            "path": libraries[0],
                            "config": str(plugin_config),
                            "uuid": "e94e6e91-a83d-4e04-a147-aab3860d0cd0",
                            "name": plugin,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with log_path.open("w", encoding="utf-8") as log:
            collector = subprocess.Popen(
                [self.prefix.bin.telemetry_collector, str(collector_config)],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 10
                while expected_message not in log_path.read_text(encoding="utf-8"):
                    if collector.poll() is not None or time.monotonic() >= deadline:
                        raise AssertionError(f"{plugin}: expected {expected_message!r}\n"
                                             f"{log_path.read_text(encoding='utf-8')}")
                    time.sleep(0.05)
                if settings is not None:
                    collector.terminate()
                    assert collector.wait(timeout=5) == 0, log_path.read_text(encoding="utf-8")
            finally:
                if collector.poll() is None:
                    collector.kill()
                    collector.wait(timeout=5)

        return log_path.read_text(encoding="utf-8")


class CMakeBuilder(BaseCMakeBuilder):
    _service_inputs = (
        "TC_PLUGIN_TEST_BROKER",
        "TC_PLUGIN_TEST_NAMING",
        "TC_PLUGIN_TEST_NAMING_CONFIG",
    )

    def _plugin_test_inputs(self):
        if not self.pkg.run_tests or not {"mock", "snmp", "sysfs", "tester"}.intersection(
            self.pkg.selected_plugins
        ):
            return {}
        inputs = {name: os.environ.get(name) for name in self._service_inputs}
        if not any(inputs.values()):
            return {}
        for name, value in inputs.items():
            if not value or not Path(value).is_absolute() or not Path(value).is_file():
                raise InstallError(f"Set {name} to an existing absolute file path")
        return inputs

    def cmake_args(self):
        # For service-backed tests, pass all three fixture paths to spack install
        # --test=root --dirty. With +snmp, put snmpd and snmpget on PATH.
        inputs = self._plugin_test_inputs()
        return [
            self.define("USE_SYSTEM_DEPENDENCIES", True),
            self.define("DEPENDENCY_PROVIDER_spdlog", "spdlog"),
            self.define("SELECTED_PLUGINS", self.pkg.selected_plugins),
            self.define("BUILD_TESTING", self.pkg.run_tests),
            self.define("TC_BUILD_PLUGIN_MANAGER_TESTS", self.pkg.run_tests),
            self.define("TC_BUILD_PLUGIN_CONFIGURATION_TESTS", self.pkg.run_tests),
            self.define("TC_BUILD_PLUGIN_TESTS", bool(inputs)),
            *(self.define_path(name, path) for name, path in inputs.items()),
        ]

    def check(self):
        for target in ("run_plugin_manager_tests", "run_plugin_configuration_tests"):
            self.pkg.module.cmake("--build", self.build_directory, "--target", target)

    @run_after("install")
    def check_installed_plugins(self):
        if not self.pkg.run_tests:
            return

        cmake = self.pkg.module.cmake
        service_tests = bool(self._plugin_test_inputs())
        if service_tests:
            cmake("--build", self.build_directory, "--target", "run_plugin_tests")
        cmake(
            self.define_path("REPORT_ROOT", Path(self.build_directory) / "test-artifacts"),
            self.define("REQUIRE_ALL_REPORTS", service_tests),
            "-P",
            str(Path(self.pkg.stage.source_path) / "tests/reporting/write_report_index.cmake"),
        )

    @property
    def archive_files(self):
        artifacts = Path(self.build_directory) / "test-artifacts"
        return super().archive_files + [
            str(artifacts / pattern)
            for pattern in (
                "report.md",
                "*/*.md",
                "*/*.xml",
                "*/*.log",
                "*/*/*.log",
                "*/*/*/*.log",
                "plugin-tests/*/*/*.yaml",
            )
        ]
