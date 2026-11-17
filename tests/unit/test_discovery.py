# SPDX-License-Identifier: Apache-2.0
import json
from pathlib import Path
import subprocess

import seanerstack.discovery as discovery
import seanerstack.isolation as isolation


def _state(tmp_path: Path):
    return isolation.prepare_isolation(tmp_path / "state", tmp_path / "spack")


def test_registered_compilers_are_read_from_the_state(tmp_path: Path):
    x = _state(tmp_path)
    (x.config / "packages.yaml").write_text(
        "packages:\n"
        "  gcc:\n"
        "    externals:\n"
        "    - spec: gcc@16.2.1 languages:='c,c++,fortran'\n"
        "      prefix: /usr\n"
        "      extra_attributes: {compilers: {c: /usr/bin/gcc}}\n"
        "    - spec: gcc@14.3.1 languages:='c,c++'\n"
        "      prefix: /opt/rh/gcc-toolset-14/root/usr\n"
        "      extra_attributes: {compilers: {c: /opt/rh/gcc-toolset-14/root/usr/bin/gcc}}\n"
        "  glibc:\n"
        "    externals:\n"
        "    - spec: glibc@2.43\n"
        "      prefix: /usr\n",
        encoding="utf-8",
    )

    assert discovery.registered_compilers(x) == [
        discovery.Found("gcc@14.3.1", "/opt/rh/gcc-toolset-14/root/usr"),
        discovery.Found("gcc@16.2.1", "/usr"),
    ]


def test_matching_takes_a_name_and_the_start_of_a_version():
    found = [discovery.Found("gcc@16.2.1", "/usr"), discovery.Found("gcc@161.0", "/x"), discovery.Found("llvm@19.1.7", "/usr")]
    assert discovery.matching(found, "gcc@16") == [found[0]]
    assert discovery.matching(found, "gcc@=16.2.1") == [found[0]]
    assert discovery.matching(found, "gcc") == found[:2]
    assert discovery.matching(found, "clang") == []


def test_detection_registers_nothing_and_reads_the_script_output(monkeypatch, tmp_path: Path):
    toolset = tmp_path / "toolset"
    (toolset / "bin").mkdir(parents=True)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        out = "==> some message\n" + json.dumps({"rust": [{"spec": "rust@1.91.0 +dev", "prefix": "/usr"}]}) + "\n"
        return subprocess.CompletedProcess(args, 0, out, "")

    monkeypatch.setattr(discovery.subprocess, "run", fake_run)

    found = discovery.detect_packages(["spack"], {}, ["rust", "capnproto"], [toolset])

    assert found == {"rust": [discovery.Found("rust@1.91.0", "/usr")]}
    assert calls == [["spack", "python", str(discovery.DETECT_SCRIPT), "rust", "capnproto", f"--path={toolset / 'bin'}"]]
    assert "external" not in calls[0]


def test_compilers_off_path_are_searched_below_their_prefix(monkeypatch, tmp_path: Path):
    toolset = tmp_path / "toolset"
    (toolset / "bin").mkdir(parents=True)
    calls = []
    monkeypatch.setattr(discovery.subprocess, "run", lambda args, **kwargs: calls.append(args))

    discovery.find_compilers(["spack"], {}, [toolset])

    assert calls == [["spack", "compiler", "find"], ["spack", "compiler", "find", str(toolset / "bin")]]


def test_what_init_detected_is_kept_in_the_state(tmp_path: Path):
    x = _state(tmp_path)
    detected = {"rust": [discovery.Found("rust@1.91.0", "/usr")]}
    discovery.save_detected(x, detected)
    assert discovery.load_detected(x) == detected
    assert discovery.load_detected(_state(tmp_path / "other")) == {}
