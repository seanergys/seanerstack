# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import subprocess

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
