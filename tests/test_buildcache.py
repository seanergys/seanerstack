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
    monkeypatch.setattr(buildcache.shutil, "which", lambda name: "/usr/bin/spack")

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(buildcache.subprocess, "run", fake_run)
    buildcache.configure_buildcaches(config, scope="user")

    add = next(args for args in calls if args[:3] == ["spack", "mirror", "add"])
    assert "--type" in add and "binary" in add
    assert "--autopush" in add
    assert "--unsigned" in add
    assert "--s3-endpoint-url" in add
    assert "SEANSTACK_RESOURCE_CACHE_ACCESS_KEY_ID" in add
    assert "SEANSTACK_RESOURCE_CACHE_SECRET_ACCESS_KEY" in add
    assert "s3://builds" in add
