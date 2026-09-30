# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
from getpass import getpass
from pathlib import Path
import sys
from typing import Any, Callable


@dataclass
class SecretStore:
    path: Path | None
    password_file: Path | None = None
    password_stdin: bool = False
    _data: dict[str, Any] | None = None

    def _password(self) -> str:
        if self.password_stdin:
            value = sys.stdin.readline()
        elif self.password_file is not None:
            value = self.password_file.read_text(encoding="utf-8")
        else:
            value = getpass("Seanervault password: ")
        if value.endswith("\r\n"):
            value = value[:-2]
        elif value.endswith("\n"):
            value = value[:-1]
        if not value:
            raise ValueError("Seanervault password must not be empty")
        return value

    def _load(self) -> dict[str, Any]:
        if self.path is None:
            raise ValueError("resource requires credentials; provide --secrets-file FILE")
        if self._data is None:
            try:
                from seanervault import load
            except ImportError as error:
                raise RuntimeError("seanervault is required to read --secrets-file") from error
            data = load(self.path, self._password())
            if not isinstance(data, dict):
                raise ValueError(f"{self.path}: decrypted secrets root must be a mapping")
            self._data = data
        return self._data

    def has_credentials(self, name: str) -> bool:
        credentials = self._load().get("credentials")
        return isinstance(credentials, dict) and isinstance(credentials.get(name), dict)

    def credentials(self, name: str) -> dict[str, Any]:
        data = self._load()
        credentials = data.get("credentials", {}).get(name) if isinstance(data.get("credentials"), dict) else None
        if not isinstance(credentials, dict):
            raise ValueError(f"credentials {name!r} not found in {self.path}")
        return dict(credentials)
