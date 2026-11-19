# SPDX-License-Identifier: Apache-2.0
import os
from pathlib import Path
import subprocess

import seanerstack.buildcache as buildcache
import seanerstack.cli as cli
from seanerstack.config import Config, Resource
from seanerstack.secrets import SecretStore


def _caches(tmp_path: Path) -> Config:
    return Config(
        path=tmp_path / "config.toml",
        resources={
            name: Resource(name=name, kind="spack-buildcache", url=f"oci://registry.example.org/{name}", credentials=credentials, signed=False)
            for name, credentials in (("registry", "gitlab"), ("other", "missing"))
        },
    )


def test_explain_runs_the_hash_comparison_in_the_session(monkeypatch):
    calls = []
    monkeypatch.setattr(
        buildcache.subprocess, "run",
        lambda args, **kwargs: calls.append((args, kwargs["env"])) or subprocess.CompletedProcess(args, 1),
    )

    assert buildcache.explain("gcc@15.3.0", command=["spack"], env={"A": "1"}) == 1
    assert calls == [(["spack", "python", buildcache.HASHDIFF_SCRIPT, "gcc@15.3.0"], {"A": "1"})]
    assert os.path.isfile(buildcache.HASHDIFF_SCRIPT)


def test_explain_reads_every_cache_it_has_credentials_for(tmp_path: Path):
    secrets = SecretStore(tmp_path / "vault", _data={"credentials": {"gitlab": {"token": "glpat"}}})

    env = buildcache.buildcache_environment(_caches(tmp_path), secrets, {"KEEP": "1"})

    assert env["SEANERSTACK_RESOURCE_REGISTRY_PASSWORD"] == "glpat"
    assert env["KEEP"] == "1"
    assert not any(name.startswith("SEANERSTACK_RESOURCE_OTHER") for name in env)


def test_buildcache_explain_takes_the_whole_spec(monkeypatch, tmp_path: Path):
    seen = []
    monkeypatch.setattr(cli, "load_config", lambda path: Config(path=tmp_path / "config.toml", resources={}))
    monkeypatch.setattr(cli, "_spack_runtime", lambda args: (None, None, ["spack"], {}))
    monkeypatch.setattr(buildcache, "explain", lambda spec, **kwargs: seen.append(spec) or 0)
    args = cli.build_parser().parse_args(["--config-file", str(tmp_path / "config.toml"), "buildcache", "explain", "zlib", "+pic"])

    assert cli._run_buildcache(args) == 0
    assert seen == ["zlib +pic"]


class _Spec:
    """A stand-in for a concrete Spack spec, as far as the comparison reads one."""

    def __init__(self, hash, os="rocky10", target="x86_64_v3"):
        self.name, self.version, self.hash = "gcc", "15.3.0", hash
        self.architecture = type("Arch", (), {"os": os, "target": target})

    def dag_hash(self, length=None):
        return self.hash[:length]

    def format(self, text):
        return text.replace("{name}", self.name).replace("{@version}", f"@{self.version}").replace("{/hash}", f"/{self.hash}").replace(
            "{arch}", f"linux-{self.architecture.os}-{self.architecture.target}"
        )

    def to_node_dict(self):
        return {"name": self.name, "arch": {"platform_os": self.architecture.os, "target": self.architecture.target}}

    def edges_to_dependencies(self):
        return []


def _hashdiff(monkeypatch, cached):
    """The comparison script with a stand-in for Spack whose caches hold `cached`."""
    import importlib.util
    import sys
    import types

    spack = types.ModuleType("spack")
    spack.spack_version = "1.2.2"
    for name in ("binary_distribution", "concretize", "config", "spec"):
        module = types.ModuleType(f"spack.{name}")
        setattr(spack, name, module)
        monkeypatch.setitem(sys.modules, f"spack.{name}", module)
    monkeypatch.setitem(sys.modules, "spack", spack)
    spack.concretize.concretize_one = lambda text: _Spec("local")
    spack.config.CONFIG = object()
    spack.binary_distribution.update_cache_and_get_specs = lambda *, config: cached
    spec = importlib.util.spec_from_file_location("hashdiff_script", buildcache.HASHDIFF_SCRIPT)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    return script


CACHED = [
    _Spec("local"), _Spec("zen3", target="zen3"), _Spec("deb1", os="debian13"), _Spec("deb2", os="debian13"), _Spec("arch", os="arch"),
]


def test_explain_compares_with_the_cached_specs_of_this_operating_system(monkeypatch, capsys):
    assert _hashdiff(monkeypatch, CACHED).main(["gcc@15"]) == 0

    out = capsys.readouterr().out
    assert "cached: 5 of gcc@15.3.0, 2 for rocky10" in out
    assert "not compared: arch-x86_64_v3 (1), debian13-x86_64_v3 (2); --all compares them too" in out
    assert "identical: the cache should be used" in out
    assert "/zen3" in out and "/deb1" not in out and "/arch" not in out


def test_explain_narrows_to_this_target_or_widens_to_every_platform(monkeypatch, capsys):
    script = _hashdiff(monkeypatch, CACHED)

    assert script.main(["--match=target", "gcc@15"]) == 0
    out = capsys.readouterr().out
    assert "1 for rocky10 and x86_64_v3" in out and "/zen3" not in out
    assert "rocky10-zen3 (1)" in out

    assert script.main(["--match=all", "gcc@15"]) == 0
    out = capsys.readouterr().out
    assert "5 for any platform" in out and "not compared" not in out
    assert all(f"/{name}" in out for name in ("zen3", "deb1", "deb2", "arch"))


def test_explain_fails_when_the_caches_hold_the_spec_only_for_other_platforms(monkeypatch, capsys):
    script = _hashdiff(monkeypatch, [_Spec("deb1", os="debian13")])

    assert script.main(["gcc@15"]) == 1
    out = capsys.readouterr().out
    assert "cached: 1 of gcc@15.3.0, 0 for rocky10" in out and "debian13-x86_64_v3 (1)" in out
    assert script.main(["--match=nothing", "gcc@15"]) == 2


def test_explain_passes_the_selection_to_the_comparison(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(buildcache.subprocess, "run", lambda args, **kwargs: calls.append(args) or subprocess.CompletedProcess(args, 0))

    buildcache.explain("gcc@15", command=["spack"], env={}, match="target")
    buildcache.explain("gcc@15", command=["spack"], env={}, match="all")

    assert [call[3:] for call in calls] == [["--match=target", "gcc@15"], ["--match=all", "gcc@15"]]
    parser = cli.build_parser()
    assert parser.parse_args(["buildcache", "explain", "gcc@15"]).match == "os"
    assert parser.parse_args(["buildcache", "explain", "--match-target", "gcc@15"]).match == "target"
    assert parser.parse_args(["buildcache", "explain", "--all", "gcc@15"]).match == "all"
