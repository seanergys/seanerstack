# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
from typing import Mapping

from .config import Config
from .paths import repository_path
from .pins import BUILTIN_REPO_COMMIT, BUILTIN_REPO_GIT, SPACK_GIT, SPACK_VERSION
from .auth import spack_resource_environment
from .secrets import SecretStore


# Hosts without internet access point this at a mirror or a local clone. The
# pinned commit still applies, so build-cache hashes stay the same.
BUILTIN_REPO_GIT_ENV = "SEANERSTACK_BUILTIN_REPO_GIT"

# Every hash contains the install path of the compiler that built it, and Spack
# cannot relocate a binary to a longer path, so a machine reuses the binaries of
# the project build cache only with this state directory. It is where the
# toolchain is built, where seanerctl builds, and where the services install.
DEFAULT_STATE_DIR = Path("/opt/seanergys/state")

# Spack tests for the presence of this variable, not its value, so an inherited
# one has to be removed rather than overridden. It switches the user scope off,
# and that scope is where the private configuration lives.
UNSET_ON_ACTIVATION = ("SPACK_DISABLE_LOCAL_CONFIG",)


@dataclass(frozen=True)
class SpackLayout:
    state: Path
    config: Path
    store: Path
    stage: Path
    cache: Path
    source_cache: Path
    environments: Path
    package_repos: Path
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
        package_repos=root / "package_repos",
        bin=root / "bin",
    )


def resolve_state_dir(value: Path | None) -> Path:
    if value is not None:
        return value.expanduser().resolve()
    raw = os.environ.get("SEANERSTACK_STATE_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_STATE_DIR


def pinned_spack(state_dir: Path) -> Path:
    """Where the pinned Spack lives in a state directory, installed or not."""
    return state_dir / f"spack-{SPACK_VERSION}" / "bin" / "spack"


def install_pinned_spack(state_dir: Path) -> Path:
    """Clone the pinned Spack into the state directory, unless it is there already."""
    executable = pinned_spack(state_dir)
    if executable.is_file():
        return executable
    root = executable.parents[1]
    # A clone that was interrupted is started again rather than used.
    partial = root.with_name(root.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    root.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1", "--branch", SPACK_VERSION, SPACK_GIT, str(partial)],
        check=True,
    )
    partial.rename(root)
    return executable


def spack_version(executable: Path) -> str:
    """The version a Spack executable reports, such as 1.2.2."""
    result = subprocess.run([str(executable), "--version"], check=True, capture_output=True, text=True)
    return result.stdout.split()[0]


def resolve_real_spack(explicit: Path | None, state_dir: Path) -> Path:
    """The Spack of the session: the pinned one, which is installed when missing.

    Another Spack, given with --spack-executable or SEANERSTACK_REAL_SPACK, has
    to be the pinned version. A different one writes specs and build-cache
    indexes that the pinned one cannot read, and its hashes match no binary of
    the project build cache.
    """
    if explicit is None and os.environ.get("SEANERSTACK_REAL_SPACK"):
        explicit = Path(os.environ["SEANERSTACK_REAL_SPACK"])
    if explicit is None:
        return install_pinned_spack(state_dir)
    path = explicit.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Spack executable does not exist: {path}")
    found, wanted = spack_version(path), SPACK_VERSION.removeprefix("v")
    if found != wanted:
        raise RuntimeError(
            f"{path} is Spack {found}, and Seanerstack needs Spack {wanted}; "
            "leave out --spack-executable and SEANERSTACK_REAL_SPACK to use the one it installs"
        )
    return path


def resolve_builtin_repo_git() -> str:
    return os.environ.get(BUILTIN_REPO_GIT_ENV) or BUILTIN_REPO_GIT


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_if_missing(path: Path, text: str) -> None:
    if not path.exists():
        _write(path, text)


def prepare_isolation(state_dir: Path, real_spack: Path) -> SpackLayout:
    x = layout(state_dir)
    for directory in (x.config, x.store, x.stage, x.cache, x.source_cache, x.environments, x.package_repos, x.bin):
        directory.mkdir(parents=True, exist_ok=True)

    # Double-colon keys intentionally replace lower-precedence configuration,
    # preventing site/instance/user configuration from merging into Seanerstack.
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
    # Merged, not replaced. Spack's concretizer defaults carry structured keys
    # it reads unconditionally, such as `externals:completion`; replacing the
    # section wholesale leaves them unset and concretization fails with
    # "Unknown value for concretizer:externals:completion: None". Unlike
    # packages, mirrors, and repos, this section is not a boundary against
    # outside configuration, so merging costs nothing.
    _write_if_missing(x.config / "concretizer.yaml", "concretizer:\n  reuse: false\n")
    # The private scope replaces lower-precedence configuration, so it has to
    # carry `builtin` itself. Spack's defaults declare it as a git remote, and
    # without it no package loads at all: Seanerstack recipes, and every recipe
    # they depend on, import from spack_repo.builtin. Seanerstack comes first so
    # its own recipes take precedence.
    #
    # Rewritten every time, so an existing state follows a new pin or a moved
    # installation. The clone directory names the commit: a new pin gets a fresh
    # clone at that commit, where reusing the old one would need `spack repo update`.
    _write(
        x.config / "repos.yaml",
        "repos::\n"
        f"  seanerstack: {repository_path()}\n"
        "  builtin:\n"
        f"    git: {resolve_builtin_repo_git()}\n"
        f"    commit: {BUILTIN_REPO_COMMIT}\n"
        f"    destination: {x.package_repos / f'builtin-{BUILTIN_REPO_COMMIT[:12]}'}\n",
    )

    shim = x.bin / "spack"
    _write(
        shim,
        "#!/bin/sh\n"
        'if [ -z "${SEANERSTACK_REAL_SPACK:-}" ] || [ -z "${SEANERSTACK_SPACK_CONFIG_DIR:-}" ]; then\n'
        '  echo "seanerstack: isolated spack launcher requires an activated Seanerstack environment" >&2\n'
        "  exit 2\n"
        "fi\n"
        'exec "$SEANERSTACK_REAL_SPACK" -C "$SEANERSTACK_SPACK_CONFIG_DIR" "$@"\n',
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return x


def spack_env(x: SpackLayout) -> dict[str, str]:
    # SPACK_DISABLE_LOCAL_CONFIG is deliberately not set. It switches the user
    # scope off entirely, which also disables SPACK_USER_CONFIG_PATH, leaving
    # no writable scope at all: `spack config add` and `spack compiler find`
    # then fall through to the site scope inside the Spack checkout, where the
    # `::` keys below override them and they have no effect. Pointing the user
    # scope at the private directory achieves the isolation on its own, and
    # SPACK_SYSTEM_CONFIG_PATH already takes care of the system scope.
    return {
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
    if env.get("SEANERSTACK_ACTIVE") == "1":
        raise ValueError("Seanerstack is already active; deactivate it before activating another state directory")
    x = prepare_isolation(state_dir, real_spack)

    changes = spack_env(x)
    changes.update({
        "SEANERSTACK_ACTIVE": "1",
        "SEANERSTACK_STATE_DIR": str(x.state),
        "SEANERSTACK_REAL_SPACK": str(real_spack),
        "SEANERSTACK_SPACK_CONFIG_DIR": str(x.config),
        "PATH": f"{x.bin}{os.pathsep}{env.get('PATH', '')}",
    })
    if secrets is not None and secrets.path is not None:
        for resource in config.resources.values():
            # A vault need not hold credentials for every shipped build cache.
            if (
                resource.kind == "spack-buildcache"
                and resource.credentials
                and secrets.has_credentials(resource.credentials)
            ):
                changes.update(spack_resource_environment(resource, secrets))

    lines = []
    for name in (*changes, *UNSET_ON_ACTIVATION):
        marker = f"SEANERSTACK_SAVED_{name}_SET"
        saved = f"SEANERSTACK_SAVED_{name}"
        if name in env:
            lines.extend((_export(marker, "1"), _export(saved, env[name])))
        else:
            lines.extend((_export(marker, "0"), f"unset {saved}"))
    lines.extend(_export(name, value) for name, value in changes.items())
    lines.extend(f"unset {name}" for name in UNSET_ON_ACTIVATION)
    return "\n".join(lines) + "\n"


def deactivation_script(environ: Mapping[str, str] | None = None) -> str:
    env = dict(os.environ if environ is None else environ)
    if env.get("SEANERSTACK_ACTIVE") != "1":
        raise ValueError("Seanerstack is not active")

    managed = [
        "SPACK_DISABLE_LOCAL_CONFIG", "SPACK_USER_CONFIG_PATH", "SPACK_SYSTEM_CONFIG_PATH",
        "SPACK_USER_CACHE_PATH", "SEANERSTACK_ACTIVE", "SEANERSTACK_STATE_DIR",
        "SEANERSTACK_REAL_SPACK", "SEANERSTACK_SPACK_CONFIG_DIR", "PATH",
    ]
    managed.extend(name for name in env if name.startswith("SEANERSTACK_RESOURCE_") and not name.startswith("SEANERSTACK_SAVED_"))
    lines = []
    for name in dict.fromkeys(managed):
        marker = f"SEANERSTACK_SAVED_{name}_SET"
        saved = f"SEANERSTACK_SAVED_{name}"
        if env.get(marker) == "1":
            lines.append(_export(name, env.get(saved, "")))
        else:
            lines.append(f"unset {name}")
        lines.extend((f"unset {marker}", f"unset {saved}"))
    return "\n".join(lines) + "\n"
