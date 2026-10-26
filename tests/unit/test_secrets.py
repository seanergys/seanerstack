# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import keyloom
import pytest

from seanerstack.secrets import SecretStore

PASSWORD = "correct horse battery staple"


def _vault(path: Path) -> Path:
    keyloom.store(
        path=path,
        data={
            "credentials": {
                "gitlab": {
                    "username": "oauth2",
                    "token": keyloom.secret(value="secret-token"),
                }
            }
        },
        password=PASSWORD,
        algorithm="argon2-v2",
    )
    return path


def test_secret_store_decrypts_keyloom_file_with_password_file(tmp_path: Path):
    vault = _vault(tmp_path / "secrets.toml")
    password = tmp_path / "password"
    password.write_text(PASSWORD + "\n", encoding="utf-8")

    store = SecretStore(vault, password_file=password)

    assert store.has_credentials("gitlab")
    assert store.credentials("gitlab") == {"username": "oauth2", "token": "secret-token"}


def test_secret_store_reports_wrong_password_as_value_error(tmp_path: Path):
    vault = _vault(tmp_path / "secrets.toml")
    password = tmp_path / "password"
    password.write_text("wrong\n", encoding="utf-8")

    store = SecretStore(vault, password_file=password)

    with pytest.raises(ValueError, match="secrets.toml"):
        store.credentials("gitlab")


def test_secret_store_rejects_plaintext_secret(tmp_path: Path):
    vault = tmp_path / "secrets.toml"
    vault.write_text(
        '[credentials.gitlab]\ntoken = { __keyloom__ = "secret", value = "plain" }\n',
        encoding="utf-8",
    )
    password = tmp_path / "password"
    password.write_text(PASSWORD, encoding="utf-8")

    with pytest.raises(ValueError):
        SecretStore(vault, password_file=password).credentials("gitlab")
