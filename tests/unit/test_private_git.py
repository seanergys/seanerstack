# SPDX-License-Identifier: Apache-2.0
import base64
from email.message import Message
import os
from pathlib import Path
import subprocess
import urllib.error

import pytest

import seanerstack.auth as auth
from seanerstack.auth import GitAuth, git_environment, parse_git_version
import seanerstack.sync as sync
from seanerstack.config import Config, Resource
from seanerstack.secrets import SecretStore


@pytest.fixture(autouse=True)
def supported_git(monkeypatch):
    # The unit tests do not need Git installed.
    monkeypatch.setattr(auth, "git_version", lambda: (2, 43))


def test_private_repo_uses_named_resource_credentials_without_argv_secret(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    package = repo / "packages" / "demo"
    package.mkdir(parents=True)
    (package / "package.py").write_text(
        '''class Demo:\n    git = "https://gitlab.example.org/group/demo.git"\n    seanerstack_resource = "gitlab"\n    version("1.0", tag="v1.0")\n''',
        encoding="utf-8",
    )
    config = Config(
        path=tmp_path / "config.toml",
        resources={
            "gitlab": Resource(
                name="gitlab",
                kind="git",
                url="https://gitlab.example.org/",
                credentials="gitlab-user",
            )
        },
    )
    secrets = SecretStore(None)
    monkeypatch.setattr(
        secrets,
        "credentials",
        lambda name: {"username": "oauth2", "token": "super-secret-token"},
    )
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            args,
            0,
            "abc refs/tags/v1.0\nabc refs/heads/main\n",
            "",
        )

    monkeypatch.setattr(sync.subprocess, "run", fake_run)
    sync.sync_package("demo", repository=repo, check=True, config=config, secrets=secrets)

    assert "super-secret-token" not in " ".join(seen["args"])
    assert seen["env"]["SEANERSTACK_GIT_PASSWORD"] == "super-secret-token"
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"
    # Sent with the first request, scoped to the resource URL.
    index = int(seen["env"]["GIT_CONFIG_COUNT"]) - 1
    assert seen["env"][f"GIT_CONFIG_KEY_{index}"] == "http.https://gitlab.example.org/.extraHeader"
    expected = base64.b64encode(b"oauth2:super-secret-token").decode("ascii")
    assert seen["env"][f"GIT_CONFIG_VALUE_{index}"] == f"Authorization: Basic {expected}"
    assert expected not in " ".join(seen["args"])


def test_git_credentials_keep_existing_environment_configuration(monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "safe.directory")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "*")

    with git_environment(GitAuth(username="oauth2", password="token", url="https://gitlab.example.org/")) as env:
        assert env["GIT_CONFIG_COUNT"] == "2"
        assert (env["GIT_CONFIG_KEY_0"], env["GIT_CONFIG_VALUE_0"]) == ("safe.directory", "*")
        assert env["GIT_CONFIG_KEY_1"] == "http.https://gitlab.example.org/.extraHeader"


def test_private_archive_download_sends_token_only_as_unredirected_header(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    package = repo / "packages" / "demo"
    package.mkdir(parents=True)
    (package / "package.py").write_text(
        "class Demo:\n"
        '    url = "https://gitlab.example.org/group/demo/-/archive/v1.0/demo-v1.0.tar.gz"\n'
        '    git = "https://gitlab.example.org/group/demo.git"\n'
        '    seanerstack_resource = "gitlab"\n'
        '    version("1.0", sha256="aaa")\n',
        encoding="utf-8",
    )
    config = Config(
        path=tmp_path / "config.toml",
        resources={
            "gitlab": Resource(name="gitlab", kind="git", url="https://gitlab.example.org/", credentials="gitlab-user")
        },
    )
    secrets = SecretStore(None)
    monkeypatch.setattr(secrets, "credentials", lambda name: {"username": "oauth2", "token": "super-secret-token"})
    monkeypatch.setattr(
        sync,
        "read_remote_refs",
        lambda remote, auth=None: sync.RemoteRefs(tags={"v1.0": "abc", "v1.1": "def"}, heads={}),
    )
    seen = []

    def fake_urlopen(request):
        seen.append(request)
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", Message(), None)

    monkeypatch.setattr(sync, "_urlopen", fake_urlopen)

    with pytest.raises(ValueError) as error:
        sync.sync_package("demo", repository=repo, config=config, secrets=secrets)

    request = seen[0]
    assert "super-secret-token" not in request.full_url
    assert request.unredirected_hdrs == {"Private-token": "super-secret-token"}
    assert "super-secret-token" not in str(request.headers)
    assert "super-secret-token" not in str(error.value)


def test_private_archive_requires_https_for_credentials(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    package = repo / "packages" / "demo"
    package.mkdir(parents=True)
    (package / "package.py").write_text(
        "class Demo:\n"
        '    url = "http://gitlab.example.org/group/demo/-/archive/v1.0/demo-v1.0.tar.gz"\n'
        '    git = "http://gitlab.example.org/group/demo.git"\n'
        '    seanerstack_resource = "gitlab"\n'
        '    version("1.0", sha256="aaa")\n',
        encoding="utf-8",
    )
    config = Config(
        path=tmp_path / "config.toml",
        resources={
            "gitlab": Resource(name="gitlab", kind="git", url="http://gitlab.example.org/", credentials="gitlab-user")
        },
    )

    with pytest.raises(ValueError, match="non-HTTPS"):
        sync.sync_package("demo", repository=repo, check=True, config=config, secrets=SecretStore(None))


@pytest.mark.parametrize(
    ("output", "version"),
    [
        ("git version 2.31.0\n", (2, 31)),
        ("git version 2.39.3 (Apple Git-146)\n", (2, 39)),
        ("git version 2.45.1.windows.1\n", (2, 45)),
    ],
)
def test_parse_git_version(output, version):
    assert parse_git_version(output) == version


def test_parse_git_version_rejects_unknown_output():
    with pytest.raises(RuntimeError, match="cannot determine the Git version"):
        parse_git_version("hub version 2.14.2\n")


def test_credentials_require_git_2_31_before_contacting_the_remote(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    package = repo / "packages" / "demo"
    package.mkdir(parents=True)
    (package / "package.py").write_text(
        '''class Demo:\n    git = "https://gitlab.example.org/group/demo.git"\n    seanerstack_resource = "gitlab"\n    version("1.0", tag="v1.0")\n''',
        encoding="utf-8",
    )
    config = Config(
        path=tmp_path / "config.toml",
        resources={"gitlab": Resource(name="gitlab", kind="git", url="https://gitlab.example.org/", credentials="gitlab-user")},
    )
    secrets = SecretStore(None)
    monkeypatch.setattr(secrets, "credentials", lambda name: {"username": "oauth2", "token": "super-secret-token"})
    monkeypatch.setattr(auth, "git_version", lambda: (2, 30))
    calls = []
    monkeypatch.setattr(sync.subprocess, "run", lambda args, **kwargs: calls.append(args))

    with pytest.raises(RuntimeError, match=r"Git 2\.30 cannot send the credentials for https://gitlab\.example\.org/; Git 2\.31 or later is required"):
        sync.sync_package("demo", repository=repo, check=True, config=config, secrets=secrets)
    assert calls == []


def test_remote_without_credentials_does_not_check_git_version(monkeypatch):
    def unexpected():
        raise AssertionError("git --version must not run without credentials")

    monkeypatch.setattr(auth, "git_version", unexpected)
    with git_environment(None) as env:
        assert "GIT_CONFIG_COUNT" not in env or env["GIT_CONFIG_COUNT"] == os.environ.get("GIT_CONFIG_COUNT")
