# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import subprocess

import pytest

from seanerstack.auth import spack_resource_environment
import seanerstack.buildcache as buildcache
from seanerstack.config import Config, Resource
from seanerstack.secrets import SecretStore


def _s3_config(tmp_path: Path) -> Config:
    return Config(
        path=tmp_path / "config.toml",
        resources={"cache": Resource(name="cache", kind="spack-buildcache", url="s3://builds")},
    )


def _registry_config(tmp_path: Path) -> Config:
    return Config(
        path=tmp_path / "config.toml",
        resources={
            "registry": Resource(
                name="registry",
                kind="spack-buildcache",
                url="oci://registry.example.org/group/project/buildcache",
                credentials="gitlab",
                signed=False,
            )
        },
    )


def _filesystem_config(tmp_path: Path) -> Config:
    return Config(
        path=tmp_path / "config.toml",
        resources={
            "local": Resource(
                name="local",
                kind="spack-buildcache",
                url=(tmp_path / "buildcache").as_uri(),
                autopush=True,
                signed=False,
            )
        },
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
    assert "SEANERSTACK_RESOURCE_CACHE_ACCESS_KEY_ID" in add
    assert "SEANERSTACK_RESOURCE_CACHE_SECRET_ACCESS_KEY" in add
    assert "s3://builds" in add


def test_buildcache_configures_oci_mirror_with_variable_credentials(monkeypatch, tmp_path: Path):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(buildcache.subprocess, "run", fake_run)
    buildcache.configure_buildcaches(_registry_config(tmp_path), command=["spack"])

    add = next(args for args in calls if "mirror" in args and "add" in args)
    assert "--unsigned" in add
    assert add[add.index("--oci-username-variable") + 1] == "SEANERSTACK_RESOURCE_REGISTRY_USERNAME"
    assert add[add.index("--oci-password-variable") + 1] == "SEANERSTACK_RESOURCE_REGISTRY_PASSWORD"
    assert not any(arg.startswith("--s3") for arg in add)
    assert add[-2:] == ["registry", "oci://registry.example.org/group/project/buildcache"]


def test_oci_credentials_use_the_gitlab_token_as_registry_password():
    resource = _registry_config(Path("unused")).resource("registry")
    secrets = SecretStore(Path("vault"), _data={"credentials": {"gitlab": {"token": "glpat"}}})

    assert spack_resource_environment(resource, secrets) == {
        "SEANERSTACK_RESOURCE_REGISTRY_USERNAME": "oauth2",
        "SEANERSTACK_RESOURCE_REGISTRY_PASSWORD": "glpat",
    }


def test_buildcache_check_uses_session_credentials_without_opening_the_vault(monkeypatch, tmp_path: Path):
    environments = []

    def fake_run(args, **kwargs):
        environments.append(kwargs["env"])
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(buildcache.subprocess, "run", fake_run)
    session = {
        "SEANERSTACK_RESOURCE_REGISTRY_USERNAME": "user",
        "SEANERSTACK_RESOURCE_REGISTRY_PASSWORD": "token",
    }
    # A store without a file raises as soon as anything reads it.
    results = buildcache.check_buildcaches(
        _registry_config(tmp_path), SecretStore(None), command=["spack"], base_env=session
    )

    assert results == [("registry", True, "")]
    assert environments[0]["SEANERSTACK_RESOURCE_REGISTRY_PASSWORD"] == "token"


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


def test_buildcache_configures_filesystem_mirror_without_credentials(monkeypatch, tmp_path: Path):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(buildcache.subprocess, "run", fake_run)
    buildcache.configure_buildcaches(_filesystem_config(tmp_path), command=["spack"])

    add = next(args for args in calls if "mirror" in args and "add" in args)
    assert add[:7] == ["spack", "mirror", "add", "--scope", "user", "--type", "binary"]
    assert "--autopush" in add
    assert "--unsigned" in add
    assert not any(arg.startswith(("--s3", "--oci")) for arg in add)
    assert add[-2:] == ["local", f"file://{tmp_path}/buildcache"]


def test_buildcache_check_of_filesystem_cache_does_not_open_the_vault(monkeypatch, tmp_path: Path):
    environments = []

    def fake_run(args, **kwargs):
        environments.append(kwargs["env"])
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(buildcache.subprocess, "run", fake_run)
    # A store without a file raises as soon as anything reads it.
    results = buildcache.check_buildcaches(
        _filesystem_config(tmp_path), SecretStore(None), command=["spack"], base_env={}
    )

    assert results == [("local", True, "")]
    assert not any(name.startswith("SEANERSTACK_RESOURCE_") for name in environments[0])


def test_buildcache_check_fails_on_an_index_that_a_newer_spack_wrote(monkeypatch, tmp_path: Path):
    warning = (
        "==> Warning: you need a newer Spack version to read the buildcache index for the following v2 mirror: "
        "'oci://registry.example.org/cache'. The expected DB version is '8', but '9' was found.\n"
    )
    monkeypatch.setattr(buildcache.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "", warning))

    ((name, ok, message),) = buildcache.check_buildcaches(_s3_config(tmp_path), SecretStore(None), command=["spack"], base_env={})

    assert (name, ok) == ("cache", False)
    assert "update-index" in message


def test_buildcache_check_reports_missing_credentials_as_a_failed_cache(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(buildcache.subprocess, "run", lambda args, **kwargs: calls.append(args))

    results = buildcache.check_buildcaches(_registry_config(tmp_path), SecretStore(None), command=["spack"], base_env={})

    assert results == [("registry", False, "resource requires credentials; provide --secrets-file FILE")]
    assert calls == []
