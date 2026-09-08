# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import shutil
import stat
from typing import Mapping

from .config import Config
from .paths import repository_path
from .auth import spack_resource_environment
from .secrets import SecretStore


@dataclass(frozen=True)
class SpackLayout:
    state: Path
    config: Path
    store: Path
    stage: Path
    cache: Path
    source_cache: Path
    environments: Path
    bin: Path


def layout(state_dir: Path) -> SpackLayout:
    state = state_dir.expanduser().resolve()
    root = state / "spack"
    return SpackLayout(
        state=state,
        config=root / "config",
        store=root / "store",
        stage=root / "stage",
        cache=root / "cache",
        source_cache=root / "source-cache",
        environments=root / "environments",
        bin=root / "bin",
    )


def resolve_state_dir(value: Path | None) -> Path:
    if value is not None:
        return value.expanduser().resolve()
    raw = os.environ.get("SEANSTACK_STATE_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    raise ValueError("Spack isolation requires --state-dir DIR or SEANSTACK_STATE_DIR")


def resolve_real_spack(explicit: Path | None = None) -> Path:
    if explicit is not None:
        path = explicit.expanduser().resolve()
    elif os.environ.get("SEANSTACK_REAL_SPACK"):
        path = Path(os.environ["SEANSTACK_REAL_SPACK"]).expanduser().resolve()
    else:
        found = shutil.which("spack")
        if not found:
            raise RuntimeError("spack executable not found in PATH; provide --spack-executable FILE")
        path = Path(found).resolve()
    if not path.is_file():
        raise ValueError(f"Spack executable does not exist: {path}")
    return path


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_if_missing(path: Path, text: str) -> None:
    if not path.exists():
        _write(path, text)


def prepare_isolation(state_dir: Path, real_spack: Path) -> SpackLayout:
    x = layout(state_dir)
    for directory in (x.config, x.store, x.stage, x.cache, x.source_cache, x.environments, x.bin):
        directory.mkdir(parents=True, exist_ok=True)

    # Double-colon keys intentionally replace lower-precedence configuration,
    # preventing site/instance/user configuration from merging into SeanStack.
    _write_if_missing(
        x.config / "config.yaml",
        "config::\n"
        f"  install_tree:\n    root: {x.store}\n"
        f"  build_stage:\n  - {x.stage}\n"
        f"  source_cache: {x.source_cache}\n"
        f"  misc_cache: {x.cache / 'misc'}\n"
        f"  test_stage: {x.cache / 'test'}\n"
        f"  environments_root: {x.environments}\n",
    )
    _write_if_missing(x.config / "packages.yaml", "packages:: {}\n")
    _write_if_missing(x.config / "mirrors.yaml", "mirrors:: {}\n")
    _write_if_missing(x.config / "upstreams.yaml", "upstreams:: {}\n")
    _write_if_missing(x.config / "concretizer.yaml", "concretizer::\n  reuse: false\n")
    _write_if_missing(x.config / "repos.yaml", f"repos::\n- {repository_path()}\n")

    shim = x.bin / "spack"
    _write(
        shim,
        "#!/bin/sh\n"
        'if [ -z "${SEANSTACK_REAL_SPACK:-}" ] || [ -z "${SEANSTACK_SPACK_CONFIG_DIR:-}" ]; then\n'
        '  echo "seanstack: isolated spack launcher requires an activated SeanStack environment" >&2\n'
        "  exit 2\n"
        "fi\n"
        'exec "$SEANSTACK_REAL_SPACK" -C "$SEANSTACK_SPACK_CONFIG_DIR" "$@"\n',
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return x


def spack_env(x: SpackLayout) -> dict[str, str]:
    return {
        "SPACK_DISABLE_LOCAL_CONFIG": "true",
        "SPACK_USER_CONFIG_PATH": str(x.config),
        "SPACK_SYSTEM_CONFIG_PATH": str(x.state / "spack" / "system-config-disabled"),
        "SPACK_USER_CACHE_PATH": str(x.cache),
    }


def spack_command(x: SpackLayout, real_spack: Path, *args: str) -> list[str]:
    return [str(real_spack), "-C", str(x.config), *args]


def _export(name: str, value: str) -> str:
    return f"export {name}={shlex.quote(value)}"


def activation_script(
    *,
    state_dir: Path,
    real_spack: Path,
    config: Config,
    secrets: SecretStore | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    env = dict(os.environ if environ is None else environ)
    if env.get("SEANSTACK_ACTIVE") == "1":
        raise ValueError("SeanStack is already active; deactivate it before activating another state directory")
    x = prepare_isolation(state_dir, real_spack)

    changes = spack_env(x)
    changes.update({
        "SEANSTACK_ACTIVE": "1",
        "SEANSTACK_STATE_DIR": str(x.state),
        "SEANSTACK_REAL_SPACK": str(real_spack),
        "SEANSTACK_SPACK_CONFIG_DIR": str(x.config),
        "PATH": f"{x.bin}{os.pathsep}{env.get('PATH', '')}",
    })
    if secrets is not None and secrets.path is not None:
        for resource in config.resources.values():
            if resource.kind == "spack-buildcache" and resource.credentials:
                changes.update(spack_resource_environment(resource, secrets))

    lines = []
    for name in changes:
        marker = f"SEANSTACK_SAVED_{name}_SET"
        saved = f"SEANSTACK_SAVED_{name}"
        if name in env:
            lines.extend((_export(marker, "1"), _export(saved, env[name])))
        else:
            lines.extend((_export(marker, "0"), f"unset {saved}"))
    lines.extend(_export(name, value) for name, value in changes.items())
    return "\n".join(lines) + "\n"


def deactivation_script(environ: Mapping[str, str] | None = None) -> str:
    env = dict(os.environ if environ is None else environ)
    if env.get("SEANSTACK_ACTIVE") != "1":
        raise ValueError("SeanStack is not active")

    managed = [
        "SPACK_DISABLE_LOCAL_CONFIG", "SPACK_USER_CONFIG_PATH", "SPACK_SYSTEM_CONFIG_PATH",
        "SPACK_USER_CACHE_PATH", "SEANSTACK_ACTIVE", "SEANSTACK_STATE_DIR",
        "SEANSTACK_REAL_SPACK", "SEANSTACK_SPACK_CONFIG_DIR", "PATH",
    ]
    managed.extend(name for name in env if name.startswith("SEANSTACK_RESOURCE_") and not name.startswith("SEANSTACK_SAVED_"))
    lines = []
    for name in dict.fromkeys(managed):
        marker = f"SEANSTACK_SAVED_{name}_SET"
        saved = f"SEANSTACK_SAVED_{name}"
        if env.get(marker) == "1":
            lines.append(_export(name, env.get(saved, "")))
        else:
            lines.append(f"unset {name}")
        lines.extend((f"unset {marker}", f"unset {saved}"))
    return "\n".join(lines) + "\n"
