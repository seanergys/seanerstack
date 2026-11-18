# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess

import yaml


DEFAULT_LANGUAGES = ("c", "cxx", "fortran")
DEFAULT_PROBE = "zlib"
DEFAULT_PROBE_TIMEOUT = 300


@dataclass(frozen=True)
class BootstrapResult:
    compiler: str
    installed: bool
    registered: bool
    languages: tuple[str, ...]
    probe: str
    probe_ok: bool
    external: str | None = None
    # The hash of the installed compiler that the concretizer reuses.
    hash: str | None = None


def _run(
    args: list[str], *, check: bool = True, env=None, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, check=check, text=True, capture_output=True, env=env, timeout=timeout
    )


def _run_streaming(args: list[str], *, env=None) -> None:
    # Building a compiler takes upwards of an hour; capturing the output would
    # make a long build indistinguishable from a hang.
    subprocess.run(args, check=True, text=True, env=env)


def _environment_compiler(command: list[str], environment: Path, compiler: str, env) -> str | None:
    """The hash of the compiler that the compiler environment has installed, or None.

    @param command: the isolated Spack command
    @param environment: the directory of the compiler environment
    @param compiler: the compiler spec, such as gcc@15
    @param env: the environment of the command
    @return: the hash of the installed compiler, or None when the environment has none
    """
    if not (environment / "spack.lock").is_file():
        return None
    result = _run([*command, "-e", str(environment), "find", "--json", compiler], check=False, env=env)
    if result.returncode != 0:
        return None
    hashes = [spec["hash"] for spec in json.loads(result.stdout or "[]") if not spec.get("external")]
    if not hashes:
        return None
    if len(hashes) > 1:
        raise RuntimeError(f"{compiler!r} matches {len(hashes)} installations; use a more specific spec")
    return hashes[0]


def _ensure_system_compiler(command: list[str], env) -> None:
    """Register whatever compiler is visible on PATH as a Spack external.

    Seanerstack's isolated packages.yaml starts out empty, so on a fresh state
    directory nothing provides the `c`/`cxx` virtuals that building the
    project's own compiler itself requires: concretizing `install COMPILER`
    fails outright with "Only external, or concrete, compilers are allowed".
    A no-op when a compiler is already registered.
    """
    _run([*command, "compiler", "find"], check=False, env=env)


def _register_compiler(command: list[str], prefix: str, env) -> None:
    """Register an installed compiler as an external package.

    Must run before the language requirements are written. Those apply to
    every node needing `c`/`cxx`/`fortran`, including the ones in the
    compiler's own build tree, which the system compiler built, so they forbid
    reusing the compiler just installed and leave no solution. An external node
    has no build dependencies and so contradicts nothing.
    """
    _run([*command, "compiler", "find", prefix], env=env)


def _spec_nodes(output: str) -> list:
    """Return the nodes of `spack spec --json` output.

    The spec is one line of JSON; on a fresh state directory Spack first
    prints its own bootstrapping, such as `==> Installing clingo-bootstrap`,
    on the same stream.
    """
    for line in reversed(output.splitlines()):
        if line.startswith("{"):
            return json.loads(line)["spec"]["nodes"]
    raise RuntimeError("`spack spec --json` printed no spec")


def _root_node(output: str):
    """Return the root node of `spack spec --json` output."""
    return _spec_nodes(output)[0]


def _compiler_node(output: str, languages: tuple[str, ...]):
    """Return the node of `spack spec --json` output that compiles the root.

    That is the dependency of the root providing one of `languages`, or None.
    """
    nodes = _spec_nodes(output)
    by_hash = {node.get("hash"): node for node in nodes}
    for dependency in nodes[0].get("dependencies", []):
        if set(dependency.get("parameters", {}).get("virtuals", [])) & set(languages):
            return by_hash.get(dependency.get("hash"))
    return None


def _same_prefix(node, prefix: str) -> bool:
    path = (node or {}).get("external", {}).get("path")
    return path is not None and os.path.realpath(path) == os.path.realpath(prefix)


def _check_external(command: list[str], compiler: str, prefix: str, env, timeout) -> None:
    """Make sure COMPILER means the compiler in PREFIX before anything requires it.

    Without a matching external, Spack does not refuse `gcc@16`: it plans to
    build it from source, which a requirement would then start on the next
    install. So the spec of the compiler itself has to be that external.
    """
    result = _run([*command, "spec", "--json", compiler], check=False, env=env, timeout=timeout)
    node = None
    if result.returncode == 0:
        node = _root_node(result.stdout)
    if not _same_prefix(node, prefix):
        found = "nothing" if node is None else (
            f"{node['name']}@{node['version']} "
            + (f"in {node['external']['path']}" if "external" in node else "built from source")
        )
        raise RuntimeError(
            f"{compiler!r} does not name the compiler in {prefix}: Spack resolves it to {found}. "
            f"Check `spack compiler list` and the version of the compiler in {prefix}."
        )


def _install_compiler(command: list[str], environment: Path, compiler: str, env, source: str | None = None) -> None:
    """Build the compiler in an environment of its own, even where the system compiler has the same version.

    The system compiler is registered as an external, and an external that
    satisfies the spec is taken instead of a build: on Ubuntu 26.04,
    `gcc@15` alone takes the system GCC 15.2.0 and installs nothing. An
    external is a leaf, so asking for a C compiler as a dependency rules it
    out, while the system compiler can still be that dependency. `source`
    names the registered compiler that builds it; by default Spack chooses.

    The environment records which installation is the compiler, with
    everything it links to: its lockfile is what the concretizer reuses.

    @param command: the isolated Spack command
    @param environment: the directory of the compiler environment, written here
    @param compiler: the compiler spec, such as gcc@15
    @param env: the environment of the command
    @param source: the registered compiler that builds it, or None for Spack's choice
    @return: nothing; a failed build raises CalledProcessError
    """
    environment.mkdir(parents=True, exist_ok=True)
    root = f"{compiler} %c,cxx={source}" if source else f"{compiler} %c"
    manifest = {"spack": {"specs": [root], "view": False, "concretizer": {"unify": True}}}
    (environment / "spack.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    _run_streaming([*command, "-e", str(environment), "concretize", "--force"], env=env)
    _run_streaming([*command, "-e", str(environment), "install"], env=env)


def _reuse_environment(spack_config: Path, environment: Path) -> None:
    """Let the concretizer reuse what the compiler environment installed, and nothing else.

    Spack takes a compiler only when it is an external or a concrete spec it
    may reuse. A state concretizes everything fresh, so that the same recipes
    give the same hashes on every machine; the compiler is the one exception.
    Reused as the installed package it is, it enters the hash of what it
    builds by its own hash, which is the same wherever it is installed, and
    not by its path, as an external does.

    @param spack_config: the Spack configuration directory of the state
    @param environment: the directory of the compiler environment
    @return: nothing
    """
    settings = {"concretizer": {"reuse": {"from": [{"type": "environment", "path": str(environment)}]}}}
    (spack_config / "concretizer.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")


def _forget_registered_compilers(command: list[str], compiler: str, env) -> None:
    """Leave the installed compiler as the only one that its spec matches.

    A system compiler that the spec matches too, such as gcc 15.2.0 for
    gcc@15, would satisfy the language requirements as well, so packages could
    be built with it instead. The same goes for the external record that an
    earlier Seanerstack wrote for the installed compiler. Other compilers,
    such as gcc 16 or clang, stay registered for --source-compiler. A spec
    that matches nothing makes `compiler remove` fail, which is fine.
    """
    _run([*command, "compiler", "remove", "-a", compiler], check=False, env=env)


def _set_language_requirement(command: list[str], language: str, compiler: str, env) -> None:
    # Remove an earlier Seanerstack-style single requirement before adding the new
    # one. A missing path is harmless and is intentionally ignored.
    _run(
        [*command, "config", "remove", f"packages:{language}:require"],
        check=False, env=env,
    )
    _run(
        [*command, "config", "add", f"packages:{language}:require:{compiler}"], env=env
    )


def require_target(command: list[str], target: str, env) -> None:
    """Build every package for `target`, such as x86_64_v3, not for the host's CPU.

    The target is part of every hash. Without the requirement, each machine
    builds for its own processor, and no hash matches another machine's.
    """
    _run([*command, "config", "remove", "packages:all:require"], check=False, env=env)
    _run([*command, "config", "add", f"packages:all:require:target={target}"], env=env)


def bootstrap(
    compiler: str,
    *,
    languages: tuple[str, ...] = DEFAULT_LANGUAGES,
    probe: str = DEFAULT_PROBE,
    command: list[str] | None = None,
    env=None,
    force: bool = False,
    dry_run: bool = False,
    probe_timeout: float | None = DEFAULT_PROBE_TIMEOUT,
    external: str | None = None,
    source_compiler: str | None = None,
    environment: Path | None = None,
    spack_config: Path | None = None,
) -> BootstrapResult:
    """Make COMPILER the compiler of every SEANERGYS build.

    Without `external`, Spack installs COMPILER in the compiler environment
    unless it already has, built with `source_compiler` or Spack's choice, and
    the concretizer reuses that installation as the package it is. With
    `external`, a compiler already in that prefix, such as /usr or a
    gcc-toolset, is registered instead and nothing is built; COMPILER must
    name it.

    @param environment: the directory of the compiler environment in the state
    @param spack_config: the Spack configuration directory of the state
    """
    command = command or ["spack"]
    if not languages:
        raise ValueError("at least one compiler language is required")
    if external is not None and source_compiler:
        raise ValueError("an external compiler is not built, so it takes no source compiler")
    if external is not None:
        if force:
            raise ValueError("--force builds the compiler, and an external compiler is not built")
        if not os.path.isdir(external):
            raise ValueError(f"external compiler prefix is not a directory: {external}")
        return _bootstrap_external(
            compiler, external, languages=languages, probe=probe, command=command,
            env=env, dry_run=dry_run, probe_timeout=probe_timeout,
        )

    if environment is None or spack_config is None:
        raise ValueError("the compiler environment and the Spack configuration of the state are required")
    installed = _environment_compiler(command, environment, compiler, env)
    already_installed = installed is not None
    if (force or not already_installed) and not dry_run:
        _ensure_system_compiler(command, env)
        _install_compiler(command, environment, compiler, env, source_compiler)
        installed = _environment_compiler(command, environment, compiler, env)

    if not dry_run:
        if installed is None:
            raise RuntimeError(f"the compiler environment {environment} holds no installation of {compiler!r}")
        # Before the requirements: only a compiler that the concretizer may
        # reuse can satisfy them.
        _reuse_environment(spack_config, environment)
        _forget_registered_compilers(command, compiler, env)
        for language in languages:
            _set_language_requirement(command, language, compiler, env)

    probe_ok = False
    if not dry_run:
        try:
            probe_result = _run(
                [*command, "spec", "--json", probe], check=False, env=env, timeout=probe_timeout
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"Spack did not concretize compiler probe {probe!r} within "
                f"{probe_timeout:g} seconds. This usually means the {compiler} "
                "requirement cannot be satisfied: check that the compiler environment "
                f"{environment} has it installed and that `spack config get concretizer` "
                "reuses that environment."
            ) from error
        if probe_result.returncode != 0:
            message = probe_result.stderr.strip() or probe_result.stdout.strip()
            raise RuntimeError(f"Spack could not concretize compiler probe {probe!r}:\n{message}")
        node = _compiler_node(probe_result.stdout, languages) or {}
        # The installed compiler itself, not another build of the same spec.
        probe_ok = node.get("hash") == installed and "external" not in node

    return BootstrapResult(
        compiler=compiler,
        installed=already_installed or not dry_run,
        registered=False,
        languages=languages,
        probe=probe,
        probe_ok=probe_ok,
        hash=installed,
    )


def _bootstrap_external(
    compiler: str,
    prefix: str,
    *,
    languages: tuple[str, ...],
    probe: str,
    command: list[str],
    env,
    dry_run: bool,
    probe_timeout: float | None,
) -> BootstrapResult:
    """Register the compiler in PREFIX and require it, building nothing."""
    if dry_run:
        return BootstrapResult(
            compiler=compiler, installed=False, registered=False, languages=languages,
            probe=probe, probe_ok=False, external=prefix,
        )

    _register_compiler(command, prefix, env)
    _check_external(command, compiler, prefix, env, probe_timeout)
    for language in languages:
        _set_language_requirement(command, language, compiler, env)

    try:
        probe_result = _run(
            [*command, "spec", "--json", probe], check=False, env=env, timeout=probe_timeout
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"Spack did not concretize compiler probe {probe!r} within {probe_timeout:g} seconds."
        ) from error
    if probe_result.returncode != 0:
        message = probe_result.stderr.strip() or probe_result.stdout.strip()
        raise RuntimeError(f"Spack could not concretize compiler probe {probe!r}:\n{message}")
    node = _compiler_node(probe_result.stdout, languages)

    return BootstrapResult(
        compiler=compiler,
        installed=False,
        registered=True,
        languages=languages,
        probe=probe,
        probe_ok=_same_prefix(node, prefix),
        external=prefix,
    )


def use_external_package(command: list[str], name: str, prefix: str, env) -> None:
    """Use an installed package, found by init, instead of building it.

    Registers what is installed below `prefix` and stops Spack from building
    the package, so that every spec that needs it takes this one. Its hash
    then depends on this machine.
    """
    directory = Path(prefix) / "bin"
    _run([*command, "external", "find", "--path", str(directory if directory.is_dir() else prefix), name], env=env)
    _run([*command, "config", "add", f"packages:{name}:buildable:false"], env=env)


def install_packages(command: list[str], packages: list[str], env) -> None:
    """Install the toolchain's packages, such as rust, with the toolchain compiler."""
    if packages:
        _run_streaming([*command, "install", *packages], env=env)
