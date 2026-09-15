# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib

from .paths import share_path


@dataclass(frozen=True)
class Resource:
    name: str
    kind: str
    url: str
    credentials: str | None = None
    endpoint_url: str | None = None
    autopush: bool = False
    signed: bool = True

    @property
    def env_prefix(self) -> str:
        normalized = re.sub(r"[^A-Za-z0-9]+", "_", self.name).strip("_").upper()
        return f"SEANSTACK_RESOURCE_{normalized}"

    @property
    def oci(self) -> bool:
        return self.url.startswith(("oci://", "oci+http://"))

    @property
    def credential_variables(self) -> tuple[str, str]:
        """Variables Spack reads the user name (or key id) and secret from."""
        if self.oci:
            return (f"{self.env_prefix}_USERNAME", f"{self.env_prefix}_PASSWORD")
        return (f"{self.env_prefix}_ACCESS_KEY_ID", f"{self.env_prefix}_SECRET_ACCESS_KEY")


@dataclass(frozen=True)
class Config:
    path: Path
    resources: dict[str, Resource]

    def resource(self, name: str) -> Resource:
        try:
            return self.resources[name]
        except KeyError as error:
            raise ValueError(f"unknown Seanstack resource: {name}") from error


def default_config_path() -> Path:
    return share_path() / "config.toml"


def load_config(path: Path | None = None) -> Config:
    path = path or default_config_path()
    if not path.is_file():
        raise ValueError(f"Seanstack config does not exist: {path}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    raw_resources = data.get("resources", {})
    if not isinstance(raw_resources, dict):
        raise ValueError(f"{path}: [resources] must be a table")

    resources: dict[str, Resource] = {}
    for name, raw in raw_resources.items():
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: resources.{name} must be a table")
        kind = raw.get("kind")
        url = raw.get("url")
        if not isinstance(kind, str) or not isinstance(url, str):
            raise ValueError(f"{path}: resources.{name} requires string kind and url")
        resource = Resource(
            name=name,
            kind=kind,
            url=url,
            credentials=raw.get("credentials") if isinstance(raw.get("credentials"), str) else None,
            endpoint_url=raw.get("endpoint_url") if isinstance(raw.get("endpoint_url"), str) else None,
            autopush=bool(raw.get("autopush", False)),
            signed=bool(raw.get("signed", True)),
        )
        # Spack cannot sign OCI build caches; it warns and pushes unsigned anyway.
        if resource.kind == "spack-buildcache" and resource.oci and resource.signed:
            raise ValueError(f"{path}: resources.{name}: OCI build caches cannot be signed; set signed = false")
        resources[name] = resource
    return Config(path=path, resources=resources)
