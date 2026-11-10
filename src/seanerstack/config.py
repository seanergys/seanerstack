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
        return f"SEANERSTACK_RESOURCE_{normalized}"

    @property
    def oci(self) -> bool:
        return self.url.startswith(("oci://", "oci+http://"))

    @property
    def filesystem(self) -> bool:
        return self.url.startswith("file://")

    @property
    def credential_variables(self) -> tuple[str, str]:
        """Variables Spack reads the user name (or key id) and secret from."""
        if self.oci:
            return (f"{self.env_prefix}_USERNAME", f"{self.env_prefix}_PASSWORD")
        return (f"{self.env_prefix}_ACCESS_KEY_ID", f"{self.env_prefix}_SECRET_ACCESS_KEY")


PACKAGE_MANAGERS = ("dnf", "apt", "pacman")


@dataclass(frozen=True)
class Platform:
    """An operating system that `seanerstack buildcache prepare` builds the toolchain for."""

    name: str
    image: str
    # As `spack arch --operating-system` names it, which is what the hashes contain.
    operating_system: str
    package_manager: str
    system_packages: tuple[str, ...]
    python: str = "python3"


@dataclass(frozen=True)
class Toolchain:
    """What `seanerstack buildcache prepare` builds, and where it pushes it."""

    compiler: str
    packages: tuple[str, ...]
    cache: str
    target: str
    platforms: dict[str, Platform]

    def platform(self, name: str) -> Platform:
        try:
            return self.platforms[name]
        except KeyError as error:
            raise ValueError(f"unknown toolchain platform {name!r}; known: {', '.join(self.platforms)}") from error


@dataclass(frozen=True)
class Config:
    path: Path
    resources: dict[str, Resource]
    toolchain: Toolchain | None = None

    def resource(self, name: str) -> Resource:
        try:
            return self.resources[name]
        except KeyError as error:
            raise ValueError(f"unknown Seanerstack resource: {name}") from error


def default_config_path() -> Path:
    return share_path() / "config.toml"


def _platform(name: str, raw: dict, system_packages: dict, path: Path) -> Platform:
    where = f"{path}: toolchain.platforms.{name}"
    try:
        manager = raw["package_manager"]
        platform = Platform(
            name=name,
            image=raw["image"],
            operating_system=raw["operating_system"],
            package_manager=manager,
            # What the package manager needs everywhere, then what this platform adds.
            system_packages=(*system_packages.get(manager, ()), *raw.get("system_packages", ())),
            python=raw.get("python", "python3"),
        )
    except KeyError as error:
        raise ValueError(f"{where} requires {error.args[0]}") from error
    if manager not in PACKAGE_MANAGERS:
        raise ValueError(f"{where}: package_manager must be one of {', '.join(PACKAGE_MANAGERS)}")
    return platform


def _toolchain(data: dict, path: Path) -> Toolchain:
    # A config.toml names only what it changes, down to a single platform.
    shipped = tomllib.loads(default_config_path().read_text(encoding="utf-8")).get("toolchain", {})
    own = data.get("toolchain", {})
    raw = {**shipped, **own}
    for table in ("platforms", "system_packages"):
        raw[table] = {**shipped.get(table, {}), **own.get(table, {})}
    try:
        return Toolchain(
            compiler=raw["compiler"],
            packages=tuple(raw["packages"]),
            cache=raw["cache"],
            target=raw["target"],
            platforms={
                name: _platform(name, platform, raw["system_packages"], path)
                for name, platform in raw["platforms"].items()
            },
        )
    except KeyError as error:
        raise ValueError(f"{path}: [toolchain] requires {error.args[0]}") from error


def load_config(path: Path | None = None) -> Config:
    path = path or default_config_path()
    if not path.is_file():
        raise ValueError(f"Seanerstack config does not exist: {path}")
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
            # A filesystem cache is local or project-private, so it defaults to unsigned.
            signed=bool(raw.get("signed", not url.startswith("file://"))),
        )
        # Spack cannot sign OCI build caches; it warns and pushes unsigned anyway.
        if resource.kind == "spack-buildcache" and resource.oci and resource.signed:
            raise ValueError(f"{path}: resources.{name}: OCI build caches cannot be signed; set signed = false")
        # File permissions are the access control of a filesystem cache.
        if resource.kind == "spack-buildcache" and resource.filesystem and resource.credentials:
            raise ValueError(f"{path}: resources.{name}: filesystem build caches take no credentials")
        resources[name] = resource
    return Config(path=path, resources=resources, toolchain=_toolchain(data, path))
