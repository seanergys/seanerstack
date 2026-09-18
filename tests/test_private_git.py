# SPDX-License-Identifier: Apache-2.0
from email.message import Message
from pathlib import Path
import subprocess
import urllib.error

import pytest

import seanstack.sync as sync
from seanstack.config import Config, Resource
from seanstack.secrets import SecretStore


def test_private_repo_uses_named_resource_credentials_without_argv_secret(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    package = repo / "packages" / "demo"
    package.mkdir(parents=True)
    (package / "package.py").write_text(
        '''class Demo:\n    git = "https://gitlab.example.org/group/demo.git"\n    seanstack_resource = "gitlab"\n    version("1.0", tag="v1.0")\n''',
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
    assert seen["env"]["SEANSTACK_GIT_PASSWORD"] == "super-secret-token"
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_private_archive_download_sends_token_only_as_unredirected_header(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    package = repo / "packages" / "demo"
    package.mkdir(parents=True)
    (package / "package.py").write_text(
        "class Demo:\n"
        '    url = "https://gitlab.example.org/group/demo/-/archive/v1.0/demo-v1.0.tar.gz"\n'
        '    git = "https://gitlab.example.org/group/demo.git"\n'
        '    seanstack_resource = "gitlab"\n'
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
        '    seanstack_resource = "gitlab"\n'
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
