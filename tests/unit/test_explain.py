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
