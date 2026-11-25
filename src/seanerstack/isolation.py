# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
from typing import Mapping

from .config import Config
from .paths import repository_path
from .pins import BUILTIN_REPO_COMMIT, BUILTIN_REPO_GIT, SPACK_COMMIT, SPACK_GIT, SPACK_VERSION
from .auth import git_auth, spack_resource_environment
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

# The names under which a build finds a compiler on PATH. Spack puts its
# compiler wrapper, under these names, in front of PATH only for a package
# that depends on c, cxx or fortran; a package without a language gets none,
# and its build would take the system compiler from PATH, outside the
# compiler rule of the stack and without the include directories of its
# dependencies. The guard directory holds a script under each name that
# stops such a build. cpp is left out: tools call it as a plain preprocessor.
GUARDED_COMPILERS = ("cc", "c89", "c99", "gcc", "c++", "g++", "fc", "gfortran", "f77", "f90", "f95", "clang", "clang++")


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
    # The credentials of the configured resources, as the shell exports that
    # Spack reads them from. Written by `seanerstack init`, mode 0600.
    credentials_env: Path
    # The same credentials as a secrets mapping, for Seanerstack itself.
    credentials: Path
    # The credentials of each Git resource, one file each in the format of a
    # Git credential helper, mode 0600, for the Git that Spack clones with.
    git_credentials: Path
    # The Git configuration that hands them to that Git, for the URLs under
    # each resource only. It holds no secret, only where they are.
    git_config: Path
    # What `seanerstack init` chose, so that no later command asks again.
    record: Path
    # The packages init detected on the machine, for `toolchain bootstrap --external`.
    detected: Path
    # Stops a build that calls a compiler from PATH, in front of PATH for every Spack run.
    guard: Path


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
        credentials_env=root / "credentials.sh",
        credentials=state / "credentials.json",
        git_credentials=root / "git-credentials",
        git_config=root / "gitconfig",
        record=state / "seanerstack.json",
        detected=state / "detected.json",
        guard=root / "compiler-guard",
    )


def resolve_state_dir(value: Path | None) -> Path:
    if value is not None:
        return value.expanduser().resolve()
    raw = os.environ.get("SEANERSTACK_STATE_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return DEFAULT_STATE_DIR


def _write_private(path: Path, text: str) -> None:
    """Write a file that only its owner can read, also while it is written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.unlink(missing_ok=True)
    descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(text)
    partial.replace(path)


def store_credentials(x: SpackLayout, config: Config, secrets: SecretStore) -> list[str]:
    """Keep the credentials that the resources of `config` name, readable only by the owner.

    Seanerstack reads them back as a secrets file, and the spack wrapper as the
    variables Spack takes them from. Returns the names of the stored credentials.
    """
    names = sorted({resource.credentials for resource in config.resources.values() if resource.credentials})
    stored = {name: secrets.credentials(name) for name in names if secrets.path is not None and secrets.has_credentials(name)}
    _write_private(x.credentials, json.dumps({"credentials": stored}, indent=2) + "\n")
    holder = SecretStore.stored(x.credentials)
    exports = {}
    for resource in config.resources.values():
        if resource.kind == "spack-buildcache" and resource.credentials in stored:
            exports.update(spack_resource_environment(resource, holder))
    _write_private(x.credentials_env, "".join(f"export {name}={shlex.quote(value)}\n" for name, value in exports.items()))
    store_git_credentials(x, config, holder)
    return sorted(stored)


def _git_config_string(value: str) -> str:
    """A value or subsection name of a Git configuration file, quoted.

    @param value: the text
    @return: the text in double quotes, with backslashes and quotes escaped
    """
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def store_git_credentials(x: SpackLayout, config: Config, stored: SecretStore) -> None:
    """Keep the credentials of each Git resource where the Git of the state's Spack finds them.

    Spack clones a private recipe with Git itself. For the URLs under a Git
    resource, the Git configuration of the state replaces every credential
    helper with one that hands Git the stored credentials of that resource,
    and Git asks it only when the server wants credentials. The secret stays
    in a file readable only by its owner and never enters an environment,
    which every build inherits.
    Credentials that are no longer stored are removed.

    @param x: the layout of the state
    @param config: the Seanerstack configuration, which names the Git resources
    @param stored: the credentials that init stored in the state
    @return: None
    """
    shutil.rmtree(x.git_credentials, ignore_errors=True)
    x.git_credentials.mkdir(mode=0o700, parents=True)
    sections = []
    for resource in sorted(config.resources.values(), key=lambda item: item.name):
        if resource.kind != "git" or not resource.credentials or not stored.has_credentials(resource.credentials):
            continue
        auth = git_auth(resource, stored)
        assert auth is not None
        if any(character in value for value in (auth.username, auth.password) for character in "\r\n"):
            raise ValueError(f"credentials {resource.credentials!r} for {resource.name!r} must be a single line each")
        # A quoted TOML key can hold any character, a file name cannot.
        path = x.git_credentials / re.sub(r"[^A-Za-z0-9._-]", "_", resource.name)
        _write_private(path, f"username={auth.username}\npassword={auth.password}\n")
        # Git appends the action, get, store or erase; only get answers, so
        # Git can neither change nor remove the stored credentials. The
        # request on standard input is read in full before the answer.
        helper = f'!f() {{ cat >/dev/null; test "$1" = get && cat {shlex.quote(str(path))}; }}; f'
        sections.append(
            f"[credential {_git_config_string(resource.url)}]\n"
            # An empty helper drops the helpers of the user's own configuration for these URLs.
            "\thelper =\n"
            f"\thelper = {_git_config_string(helper)}\n"
        )
    _write(x.git_config, "".join(sections))


def write_record(
    x: SpackLayout, *, config_file: Path | None, spack_executable: Path | None, find: list[Path] = ()
) -> None:
    """Remember what `seanerstack init` was given, for every later command."""
    record = {
        "config_file": str(config_file.expanduser().resolve()) if config_file else None,
        "spack_executable": str(spack_executable.expanduser().resolve()) if spack_executable else None,
        "find": [str(prefix.expanduser().resolve()) for prefix in find],
    }
    _write(x.record, json.dumps(record, indent=2) + "\n")


def recorded_find(state_dir: Path) -> list[Path]:
    """The installations off PATH that init was told to search, with --find."""
    path = layout(state_dir).record
    raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return [Path(prefix) for prefix in raw.get("find") or []]


def read_record(state_dir: Path) -> dict[str, Path | None]:
    """What `seanerstack init` recorded in a state directory; nothing before init."""
    path = layout(state_dir).record
    raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    return {key: Path(raw[key]) if raw.get(key) else None for key in ("config_file", "spack_executable")}


def pinned_spack(state_dir: Path) -> Path:
    """Where the pinned Spack lives in a state directory, installed or not."""
    return state_dir / f"spack-{SPACK_COMMIT[:12]}" / "bin" / "spack"


def clone_pinned_spack_commands(destination: str) -> list[list[str]]:
    """The commands that put the pinned commit of Spack into `destination`.

    A commit is not a branch or tag, so `git clone --branch` cannot name it;
    the repository is fetched at that one commit instead.

    @param destination: the directory to fill, which must not exist
    @return: the commands, to run one after the other
    """
    return [
        ["git", "init", "--quiet", destination],
        ["git", "-C", destination, "fetch", "--quiet", "--depth", "1", SPACK_GIT, SPACK_COMMIT],
        ["git", "-C", destination, "-c", "advice.detachedHead=false", "checkout", "--quiet", "FETCH_HEAD"],
    ]


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
    for command in clone_pinned_spack_commands(str(partial)):
        subprocess.run(command, check=True)
    partial.rename(root)
    return executable


def spack_version(executable: Path) -> tuple[str, str | None]:
    """The version a Spack executable reports, and its commit when it runs from a Git checkout.

    @param executable: the `spack` to ask
    @return: the version, such as 1.3.0.dev0, and the commit, or None when it prints none
    """
    result = subprocess.run([str(executable), "--version"], check=True, capture_output=True, text=True)
    words = result.stdout.split()
    commit = words[1].strip("()") if len(words) > 1 else None
    return words[0], commit


def describe_pinned_spack() -> str:
    """The pinned Spack in words, such as 1.3.0.dev0 at commit 7188f9d6e0."""
    return f"{SPACK_VERSION} at commit {SPACK_COMMIT[:10]}"


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
    version, commit = spack_version(path)
    if version != SPACK_VERSION or not (commit and SPACK_COMMIT.startswith(commit)):
        found = f"{version} at commit {commit[:10]}" if commit else f"{version} without a commit"
        raise RuntimeError(
            f"{path} is Spack {found}, and Seanerstack needs Spack {describe_pinned_spack()}; "
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
    _write(x.config / "repos.yaml", _repos_yaml(x))

    _write_compiler_guard(x)

    # Runs Spack in this state from any shell, so that putting x.bin on PATH
    # once is all a user does: no activation, no variables to set.
    shim = x.bin / "spack"
    _write(
        shim,
        "#!/bin/sh\n"
        f"# Spack in the Seanerstack state {x.state}, written by Seanerstack.\n"
        + "".join(f"unset {name}\n" for name in UNSET_ON_ACTIVATION)
        + "".join(f"export {name}={shlex.quote(value)}\n" for name, value in spack_env(x).items())
        + f"if [ -r {shlex.quote(str(x.credentials_env))} ]; then . {shlex.quote(str(x.credentials_env))}; fi\n"
        # The Git that Spack clones with reads the Git credentials of the
        # state, after the configuration the caller already passes to Git.
        + 'i="${GIT_CONFIG_COUNT:-0}"\n'
        + f'export "GIT_CONFIG_KEY_$i=include.path" "GIT_CONFIG_VALUE_$i="{shlex.quote(str(x.git_config))}\n'
        + 'GIT_CONFIG_COUNT=$((i + 1)); export GIT_CONFIG_COUNT\n'
        # Only for Spack: the shell that runs it keeps its compilers.
        + f'case ":$PATH:" in *:{shlex.quote(str(x.guard))}:*) ;; *) PATH={shlex.quote(str(x.guard))}:"$PATH"; export PATH ;; esac\n'
        + f'exec {shlex.quote(str(real_spack))} -C {shlex.quote(str(x.config))} "$@"\n',
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return x


def _write_compiler_guard(x: SpackLayout) -> None:
    """Write the scripts that stop a build calling a compiler from PATH.

    @param x: the layout of the state
    @return: nothing
    """
    x.guard.mkdir(parents=True, exist_ok=True)
    for name in GUARDED_COMPILERS:
        script = x.guard / name
        _write(
            script,
            "#!/bin/sh\n"
            f"# Written by Seanerstack: see GUARDED_COMPILERS in seanerstack/isolation.py.\n"
            f"echo 'seanerstack: a Spack build called {name} from PATH. The package declares no "
            'depends_on("c"), depends_on("cxx") or depends_on("fortran"), so Spack gives it no compiler; '
            "declare the languages it is compiled from.' >&2\n"
            "exit 1\n",
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def guarded_path(x: SpackLayout, path: str) -> str:
    """PATH with the compiler guard of the state in front, once.

    @param x: the layout of the state
    @param path: the PATH to extend
    @return: the guarded PATH
    """
    entries = [entry for entry in path.split(os.pathsep) if entry and entry != str(x.guard)]
    return os.pathsep.join([str(x.guard), *entries])


def _repos_yaml(x: SpackLayout) -> str:
    """The repositories of a state: Seanerstack's own first, then builtin at the pinned commit.

    @param x: the layout of the state
    @return: the text of repos.yaml
    """
    return (
        "repos::\n"
        f"  seanerstack: {repository_path()}\n"
        "  builtin:\n"
        f"    git: {resolve_builtin_repo_git()}\n"
        f"    commit: {BUILTIN_REPO_COMMIT}\n"
        f"    destination: {x.package_repos / f'builtin-{BUILTIN_REPO_COMMIT[:12]}'}\n"
    )


def bootstrap_layout(state_dir: Path) -> SpackLayout:
    """The layout of the bootstrap instance of a state, below `<state>/bootstrap`.

    @param state_dir: the state directory
    @return: the layout; only its configuration, store, stage, cache and
        environments are used
    """
    state = state_dir.expanduser().resolve()
    root = state / "bootstrap"
    return replace(
        layout(state),
        config=root / "config",
        store=root / "store",
        stage=root / "stage",
        cache=root / "cache",
        environments=root / "environments",
        bin=root / "bin",
    )


def prepare_bootstrap_instance(x: SpackLayout, real_spack: Path, env: Mapping[str, str]) -> tuple[list[str], dict[str, str], SpackLayout]:
    """Set up the Spack instance that builds the first stage of the compiler.

    The compiler of the stack is built twice. The system compiler builds a
    first GCC here, and that GCC, known to the actual instance only as an
    external at a fixed path, builds the compiler of the stack there. Spack's
    gcc recipe lets whatever gcc@15 compiles depend only on gcc@:15, and a
    compiler built directly by a system GCC 16 would carry that GCC 16 into
    every build. An external records nothing about what built it.

    The instance has its own configuration and installations, so that nothing
    the system compiler built enters the actual instance, and the same Spack
    and recipes. The first stage is installed at `store/gcc-VERSION`, without
    a hash: the actual instance hashes the external by that path, and the path
    stays the same when the system compiler changes.

    @param x: the layout of the actual instance
    @param real_spack: the pinned Spack executable
    @param env: the environment of the actual instance
    @return: the command and environment of the bootstrap instance, and its layout
    """
    b = bootstrap_layout(x.state)
    for directory in (b.config, b.store, b.stage, b.cache, b.environments):
        directory.mkdir(parents=True, exist_ok=True)
    _write_if_missing(
        b.config / "config.yaml",
        "config::\n"
        f"  install_tree:\n    root: {b.store}\n"
        "    projections:\n"
        "      gcc: '{name}-{version}'\n"
        "      all: '{name}-{version}-{hash}'\n"
        f"  build_stage:\n  - {b.stage}\n"
        f"  source_cache: {x.source_cache}\n"
        f"  misc_cache: {b.cache / 'misc'}\n"
        f"  test_stage: {b.cache / 'test'}\n"
        f"  environments_root: {b.environments}\n",
    )
    _write_if_missing(b.config / "packages.yaml", "packages:: {}\n")
    _write_if_missing(b.config / "mirrors.yaml", "mirrors:: {}\n")
    _write_if_missing(b.config / "upstreams.yaml", "upstreams:: {}\n")
    _write_if_missing(b.config / "concretizer.yaml", "concretizer:\n  reuse: false\n")
    _write(b.config / "repos.yaml", _repos_yaml(x))
    # The user cache holds Spack's own bootstrap, such as clingo, which both instances share.
    bootstrap_env = {**env, "SPACK_USER_CONFIG_PATH": str(b.config)}
    return spack_command(b, real_spack), bootstrap_env, b


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


def git_config_environment(x: SpackLayout, env: Mapping[str, str]) -> dict[str, str]:
    """The variables that make the Git of a Spack run read the Git credentials of the state.

    As the spack wrapper does: the state's Git configuration comes after the
    entries that `env` already passes to Git.

    @param x: the layout of the state
    @param env: the environment the Spack run starts from
    @return: the variables to set in it
    """
    index = int(env.get("GIT_CONFIG_COUNT") or 0)
    return {
        f"GIT_CONFIG_KEY_{index}": "include.path",
        f"GIT_CONFIG_VALUE_{index}": str(x.git_config),
        "GIT_CONFIG_COUNT": str(index + 1),
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
