# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import subprocess

import seanstack.buildcache as buildcache
from seanstack.config import Config, Resource


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
