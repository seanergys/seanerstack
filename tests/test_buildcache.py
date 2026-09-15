# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import subprocess

import pytest

import seanstack.buildcache as buildcache
from seanstack.config import Config, Resource


def _s3_config(tmp_path: Path) -> Config:
    return Config(
        path=tmp_path / "config.toml",
        resources={"cache": Resource(name="cache", kind="spack-buildcache", url="s3://builds")},
    )


def test_buildcache_configures_binary_s3_mirror_with_variable_credentials(monkeypatch, tmp_path: Path):
    config = Config(
        path=tmp_path / "config.toml",
        resources={
            "cache": Resource(
                name="cache",
                kind="spack-buildcache",
                url="s3://builds",
                endpoint_url="https://s3.example.org",
                credentials="objectstore",
                autopush=True,
                signed=False,
            )
        },
    )
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(buildcache.subprocess, "run", fake_run)
    command = ["/opt/spack/bin/spack", "-C", "/state/spack/config"]
    buildcache.configure_buildcaches(config, command=command, env={"SPACK_DISABLE_LOCAL_CONFIG": "true"})

    add = next(args for args in calls if "mirror" in args and "add" in args)
    assert add[:3] == command[:3]
    assert "--type" in add and "binary" in add
    assert "--autopush" in add
    assert "--unsigned" in add
    assert "--s3-endpoint-url" in add
    assert "SEANSTACK_RESOURCE_CACHE_ACCESS_KEY_ID" in add
    assert "SEANSTACK_RESOURCE_CACHE_SECRET_ACCESS_KEY" in add
    assert "s3://builds" in add


def test_buildcache_configure_replaces_the_mirror_in_the_writable_scope(monkeypatch, tmp_path: Path):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(buildcache.subprocess, "run", fake_run)
    buildcache.configure_buildcaches(_s3_config(tmp_path), command=["spack"])

    assert calls[0] == ["spack", "mirror", "remove", "--scope", "user", "cache"]
    assert calls[1][:5] == ["spack", "mirror", "add", "--scope", "user"]


def test_buildcache_configure_reports_what_spack_said(monkeypatch, tmp_path: Path):
    def fake_run(args, **kwargs):
        failed = "add" in args
        return subprocess.CompletedProcess(args, 1 if failed else 0, "", "Error: something Spack said" if failed else "")

    monkeypatch.setattr(buildcache.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="something Spack said"):
        buildcache.configure_buildcaches(_s3_config(tmp_path), command=["spack"])
