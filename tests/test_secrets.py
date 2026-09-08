# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import sys
import types

from seanstack.secrets import SecretStore


def test_secret_store_uses_seanvault_load_and_password_file(monkeypatch, tmp_path: Path):
    vault = tmp_path / "secrets.toml"
    vault.write_text("ignored", encoding="utf-8")
    password = tmp_path / "password"
    password.write_text("correct horse battery staple\n", encoding="utf-8")
    seen = {}

    module = types.ModuleType("seanvault")

    def fake_load(path, supplied_password):
        seen["path"] = path
        seen["password"] = supplied_password
        return {"credentials": {"gitlab": {"username": "oauth2", "token": "secret-token"}}}

    module.load = fake_load
    monkeypatch.setitem(sys.modules, "seanvault", module)

    store = SecretStore(vault, password_file=password)
    assert store.credentials("gitlab")["token"] == "secret-token"
    assert seen == {"path": vault, "password": "correct horse battery staple"}
