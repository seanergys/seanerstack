# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import subprocess

from seanerstack.validate import validate


def test_static_validation_needs_no_compiler_state(tmp_path):
    repo = tmp_path / "repo"
    package = repo / "packages" / "demo"
    package.mkdir(parents=True)
    (package / "package.py").write_text("class Demo:\n    pass\n", encoding="utf-8")

    envs = tmp_path / "environments"
    env = envs / "demo-dev"
    env.mkdir(parents=True)
    (env / "spack.yaml").write_text("spack:\n  specs:\n    - demo@develop\n", encoding="utf-8")

    findings = validate(repository=repo, environments=envs)
    assert all(finding.level != "error" for finding in findings)
    assert not any(finding.subject == "compiler" for finding in findings)


def test_spack_validation_reaches_spack(tmp_path, monkeypatch):
    # `_validate_with_spack` copies each environment to a temporary directory
    # before concretizing it. A missing `shutil` import made that raise
    # NameError, so `validate --spack` failed before running Spack at all.
    import seanerstack.validate as validate_module

    environments = tmp_path / "environments"
    (environments / "demo-dev").mkdir(parents=True)
    (environments / "demo-dev" / "spack.yaml").write_text(
        "spack:\n  specs:\n  - demo\n", encoding="utf-8"
    )

    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(validate_module.subprocess, "run", fake_run)

    findings = validate_module._validate_with_spack(environments, ["spack"], None)

    assert calls, "Spack was never invoked"
    assert all(finding.level == "ok" for finding in findings), findings


def _git_recipes(tmp_path):
    repo = tmp_path / "repo"
    for name in ("one", "two", "public"):
        package = repo / "packages" / name
        package.mkdir(parents=True)
        resource = '    seanerstack_resource = "gitlab"\n' if name != "public" else ""
        package.joinpath("package.py").write_text(
            f'class {name.title()}:\n    git = "https://git.example.org/{name}.git"\n{resource}', encoding="utf-8"
        )
    return repo


def _gitlab_config(tmp_path):
    from seanerstack.config import Config, Resource
    gitlab = Resource(name="gitlab", kind="git", url="https://git.example.org/", credentials="token")
    return Config(path=tmp_path / "config.toml", resources={"gitlab": gitlab})


def test_git_access_is_tried_once_for_each_resource(tmp_path, monkeypatch):
    import seanerstack.validate as validate_module
    from seanerstack.secrets import SecretStore
    reads = []
    monkeypatch.setattr(validate_module, "read_remote_refs", lambda remote, auth: reads.append((remote, auth.password)))
    secrets = SecretStore(tmp_path / "vault", _data={"credentials": {"token": {"token": "glpat"}}})

    results = validate_module.check_git_access(_gitlab_config(tmp_path), secrets, repository=_git_recipes(tmp_path))

    assert [(name, ok) for name, ok, _ in results] == [("gitlab", True)]
    assert len(reads) == 1 and reads[0][1] == "glpat"


def test_git_access_reports_what_git_said(tmp_path, monkeypatch):
    import seanerstack.validate as validate_module
    from seanerstack.secrets import SecretStore

    def denied(remote, auth):
        raise subprocess.CalledProcessError(128, ["git"], stderr="fatal: Authentication failed\n")

    monkeypatch.setattr(validate_module, "read_remote_refs", denied)
    secrets = SecretStore(tmp_path / "vault", _data={"credentials": {"token": {"token": "wrong"}}})

    results = validate_module.check_git_access(_gitlab_config(tmp_path), secrets, repository=_git_recipes(tmp_path))

    assert results == [("gitlab", False, "fatal: Authentication failed")]


def test_git_access_without_credentials_says_so(tmp_path):
    import seanerstack.validate as validate_module
    from seanerstack.secrets import SecretStore

    results = validate_module.check_git_access(_gitlab_config(tmp_path), SecretStore(None), repository=_git_recipes(tmp_path))

    assert results[0][:2] == ("gitlab", False)
    assert "--secrets-file" in results[0][2]


def test_git_access_leaves_out_resources_the_config_does_not_declare(tmp_path, monkeypatch):
    import seanerstack.validate as validate_module
    from seanerstack.config import Config
    from seanerstack.secrets import SecretStore
    monkeypatch.setattr(validate_module, "read_remote_refs", lambda remote, auth: None)

    results = validate_module.check_git_access(
        Config(path=tmp_path / "config.toml", resources={}), SecretStore(None), repository=_git_recipes(tmp_path)
    )

    assert results == []


def test_git_access_of_every_recipe_names_each_package(tmp_path, monkeypatch):
    import seanerstack.validate as validate_module
    from seanerstack.secrets import SecretStore

    def read(remote, auth):
        if remote.endswith("/two.git"):
            raise subprocess.CalledProcessError(128, ["git"], stderr="remote: The project you were looking for could not be found\n")

    monkeypatch.setattr(validate_module, "read_remote_refs", read)
    secrets = SecretStore(tmp_path / "vault", _data={"credentials": {"token": {"token": "glpat"}}})

    results = validate_module.check_git_access(
        _gitlab_config(tmp_path), secrets, repository=_git_recipes(tmp_path), every_recipe=True
    )

    assert sorted((name, ok) for name, ok, _ in results) == [("one", True), ("two", False)]


def test_validate_access_reports_each_recipe(tmp_path, monkeypatch):
    import seanerstack.validate as validate_module
    from seanerstack.secrets import SecretStore
    monkeypatch.setattr(validate_module, "read_remote_refs", lambda remote, auth: None)
    secrets = SecretStore(tmp_path / "vault", _data={"credentials": {"token": {"token": "glpat"}}})
    environments = tmp_path / "environments"
    environments.mkdir()

    findings = validate_module.validate(
        access=True, repository=_git_recipes(tmp_path), environments=environments,
        config=_gitlab_config(tmp_path), secrets=secrets,
    )

    assert {f.subject for f in findings if f.subject.startswith("access:")} == {"access:one", "access:two"}
