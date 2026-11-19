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


def test_buildcache_check_reads_a_cache_without_an_index_as_empty(monkeypatch, tmp_path: Path):
    # What Spack says of a registry repository that nothing was pushed to yet.
    not_found = (
        "==> Error: FetchIndexError: Could not fetch manifest from https://registry.example.org/v2/cache/manifests/index.spack, "
        "due to: GET https://registry.example.org/v2/cache/manifests/index.spack returned 404: Not Found"
    )
    refused = not_found.replace("404: Not Found", "401: Unauthorized")
    answers = iter([not_found, refused])
    monkeypatch.setattr(
        buildcache.subprocess, "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 1, stdout="", stderr=next(answers)),
    )
    env = {"SEANERSTACK_RESOURCE_REGISTRY_USERNAME": "u", "SEANERSTACK_RESOURCE_REGISTRY_PASSWORD": "p"}

    (empty,) = buildcache.check_buildcaches(_registry_config(tmp_path), SecretStore(None), command=["spack"], base_env=env)
    (closed,) = buildcache.check_buildcaches(_registry_config(tmp_path), SecretStore(None), command=["spack"], base_env=env)

    assert empty == ("registry", True, buildcache.EMPTY_CACHE_MESSAGE)
    assert empty[2].startswith("empty: the cache has no index yet")
    # A request that the registry refuses is still a failure.
    assert closed[1] is False and "401" in closed[2]


def test_buildcache_check_reports_missing_credentials_as_a_failed_cache(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(buildcache.subprocess, "run", lambda args, **kwargs: calls.append(args))

    results = buildcache.check_buildcaches(_registry_config(tmp_path), SecretStore(None), command=["spack"], base_env={})

    assert results == [("registry", False, "resource requires credentials; provide --secrets-file FILE")]
    assert calls == []


def test_update_index_of_an_oci_cache_leaves_out_what_spack_cannot_read(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(buildcache.subprocess, "run", lambda args, **kwargs: calls.append(args))
    (registry,) = _registry_config(tmp_path).resources.values()

    buildcache.update_index(registry, command=["spack"], env={})

    assert calls == [["spack", "python", str(buildcache.UPDATE_INDEX_SCRIPT), "registry"]]
    assert buildcache.UPDATE_INDEX_SCRIPT.is_file()


def test_update_index_of_another_cache_is_spacks_own(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(buildcache.subprocess, "run", lambda args, **kwargs: calls.append(args))
    (cache,) = _s3_config(tmp_path).resources.values()

    buildcache.update_index(cache, command=["spack"], env={})

    assert calls == [["spack", "buildcache", "update-index", "cache"]]


def test_a_build_cache_that_refuses_the_request_is_an_error_that_names_it(monkeypatch):
    calls = []
    answer = subprocess.CompletedProcess([], 1, "registry: oci://registry.example.org/registry refuses the request: HTTP Error 401\n", "")
    monkeypatch.setattr(buildcache.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs["env"])) or answer)

    with pytest.raises(RuntimeError, match="registry: oci://registry.example.org/registry refuses the request: HTTP Error 401"):
        buildcache.require_cache_access(["spack"], {"A": "1"})
    assert calls == [(["spack", "python", str(buildcache.CACHE_ACCESS_SCRIPT)], {"A": "1"})]


def test_build_caches_that_answer_pass_the_access_check(monkeypatch):
    monkeypatch.setattr(buildcache.subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""))

    buildcache.require_cache_access(["spack"], {})


def _with_bootstrap_cache(tmp_path: Path) -> Config:
    from seanerstack.config import Toolchain
    config = _registry_config(tmp_path)
    bootstrap = Resource(
        name="bootstrap", kind="spack-buildcache", url="oci://registry.example.org/group/project/buildcache-bootstrap",
        credentials="gitlab", signed=False,
    )
    toolchain = Toolchain(compiler="gcc@15", packages=(), cache="registry", target="x86_64_v3", platforms={}, bootstrap_cache="bootstrap")
    return Config(path=config.path, resources={**config.resources, "bootstrap": bootstrap}, toolchain=toolchain)


def test_the_stack_never_reads_the_bootstrap_cache(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(buildcache.subprocess, "run", lambda args, **kwargs: calls.append(args) or subprocess.CompletedProcess(args, 0, "", ""))
    config = _with_bootstrap_cache(tmp_path)

    assert [resource.name for resource in buildcache.buildcaches(config)] == ["registry"]
    assert buildcache.bootstrap_buildcache(config).name == "bootstrap"
    buildcache.configure_buildcaches(config, command=["spack"])
    assert not any("bootstrap" in args for args in calls)


def test_no_bootstrap_cache_is_none_and_another_kind_is_refused(tmp_path: Path):
    from dataclasses import replace
    config = _with_bootstrap_cache(tmp_path)
    assert buildcache.bootstrap_buildcache(replace(config, toolchain=replace(config.toolchain, bootstrap_cache=None))) is None
    assert buildcache.bootstrap_buildcache(_registry_config(tmp_path)) is None
    git = Resource(name="bootstrap", kind="git", url="https://gitlab.example.org/")
    with pytest.raises(ValueError, match="not a spack-buildcache"):
        buildcache.bootstrap_buildcache(replace(config, resources={**config.resources, "bootstrap": git}))


def test_the_environment_has_the_credentials_of_the_bootstrap_cache(tmp_path: Path):
    # The bootstrap instance takes its environment from the actual one.
    secrets = SecretStore(Path("vault"), _data={"credentials": {"gitlab": {"token": "glpat"}}})
    env = buildcache.buildcache_environment(_with_bootstrap_cache(tmp_path), secrets, {})
    assert env["SEANERSTACK_RESOURCE_BOOTSTRAP_PASSWORD"] == "glpat"
    assert env["SEANERSTACK_RESOURCE_REGISTRY_PASSWORD"] == "glpat"


def test_one_build_cache_is_configured_in_the_instance_given(monkeypatch, tmp_path: Path):
    calls = []
    monkeypatch.setattr(buildcache.subprocess, "run", lambda args, **kwargs: calls.append(args) or subprocess.CompletedProcess(args, 0, "", ""))
    resource = buildcache.bootstrap_buildcache(_with_bootstrap_cache(tmp_path))

    buildcache.configure_buildcache(resource, command=["spack", "-C", "/state/bootstrap/config"])

    assert calls[0] == ["spack", "-C", "/state/bootstrap/config", "mirror", "remove", "--scope", "user", "bootstrap"]
    assert calls[1][-2:] == ["bootstrap", "oci://registry.example.org/group/project/buildcache-bootstrap"]


def test_a_config_without_the_bootstrap_cache_it_names_has_none(tmp_path: Path):
    # The [toolchain] of the shipped config.toml names it, and a config.toml of other resources does not define it.
    from dataclasses import replace
    config = _with_bootstrap_cache(tmp_path)
    without = replace(config, resources={name: value for name, value in config.resources.items() if name != "bootstrap"})
    assert buildcache.bootstrap_buildcache(without) is None
    assert [resource.name for resource in buildcache.buildcaches(without)] == ["registry"]
