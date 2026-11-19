# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import yaml


DEFAULT_LANGUAGES = ("c", "cxx", "fortran")
# Every language that a compiler rule of Seanerstack can be about.
LANGUAGE_VIRTUALS = ("c", "cxx", "fortran")
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
    # The lockfile that the compiler was installed from, when it was not concretized here.
    lockfile: Path | None = None


def _run(
    args: list[str], *, check: bool = True, env=None, timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, check=check, text=True, capture_output=True, env=env, timeout=timeout
    )


def _probe_timeout(probe: str, timeout: float | None, error: subprocess.TimeoutExpired, hint: str) -> RuntimeError:
    """The error for a probe that Spack was still concretizing when its time ran out.

    A solve that is only slow and a requirement without a solution look the
    same from here, so the error says what Spack printed and how to tell them
    apart, and names no cause.

    @param probe: the spec of the probe
    @param timeout: the seconds the probe was given
    @param error: the timeout, with what Spack printed until then
    @param hint: what to check when the requirement has no solution
    @return: the error to raise
    """
    printed = []
    for stream in (error.stdout, error.stderr):
        text = stream.decode(errors="replace") if isinstance(stream, bytes) else stream or ""
        if text.strip():
            printed.append(text.strip())
    output = "Until then it printed:\n" + "\n".join(printed) if printed else "It printed nothing until then."
    return RuntimeError(
        f"Spack did not concretize compiler probe {probe!r} within {timeout or 0:g} seconds. {output}\n"
        f"Run `spack spec {probe}` in this state without a limit: if it finishes, the solve is only slow and "
        f"needs a longer limit, which `init` and `toolchain bootstrap` take as --probe-timeout; if it fails, its message names the conflict. {hint}"
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


def _compiler_root(compiler: str, source: str | None = None) -> str:
    """The root spec of the compiler environment.

    @param compiler: the compiler spec, such as gcc@15
    @param source: the registered compiler that builds it, or None for Spack's choice
    @return: the spec that the environment asks for
    """
    return f"{compiler} %c,cxx={source}" if source else f"{compiler} %c"


def lockfile_for(lockfile: Path | None, compiler: str) -> Path | None:
    """`lockfile` when it holds the compiler environment of COMPILER, and None otherwise.

    A lockfile is shipped for the compiler of the shipped `[toolchain]`. A
    config.toml that names another compiler has no lockfile, and concretizes.

    @param lockfile: a lockfile of a compiler environment, or None
    @param compiler: the compiler spec, such as gcc@15
    @return: the lockfile, or None when there is none or it is for another compiler
    """
    if lockfile is None:
        return None
    roots = [root.get("spec") for root in json.loads(lockfile.read_text(encoding="utf-8")).get("roots", [])]
    return lockfile if roots == [_compiler_root(compiler)] else None


def _install_compiler(
    command: list[str], environment: Path, compiler: str, env, source: str | None = None, lockfile: Path | None = None
) -> None:
    """Build the compiler in an environment of its own, even where the system compiler has the same version.

    The system compiler is registered as an external, and an external that
    satisfies the spec is taken instead of a build: on Ubuntu 26.04,
    `gcc@15` alone takes the system GCC 15.2.0 and installs nothing. An
    external is a leaf, so asking for a C compiler as a dependency rules it
    out, while the system compiler can still be that dependency. `source`
    names the registered compiler that builds it; by default Spack chooses.

    The environment records which installation is the compiler, with
    everything it links to: its lockfile is what the concretizer reuses.

    With `lockfile`, the environment is not concretized here. The compiler is
    built by the system compiler, an external whose hash holds its version and
    the languages it offers, so a machine with another system compiler, or
    without gfortran, concretizes the compiler to a hash that no build cache
    holds. The lockfile is the concretization of the machine that filled the
    cache, and Spack installs exactly its specs.

    @param command: the isolated Spack command
    @param environment: the directory of the compiler environment, written here
    @param compiler: the compiler spec, such as gcc@15
    @param env: the environment of the command
    @param source: the registered compiler that builds it, or None for Spack's choice
    @param lockfile: the concretized environment to install, or None to concretize here
    @return: nothing; a failed build raises CalledProcessError
    """
    environment.mkdir(parents=True, exist_ok=True)
    manifest = {"spack": {"specs": [_compiler_root(compiler, source)], "view": False, "concretizer": {"unify": True}}}
    (environment / "spack.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    if lockfile is None:
        _run_streaming([*command, "-e", str(environment), "concretize", "--force"], env=env)
    else:
        shutil.copyfile(lockfile, environment / "spack.lock")
    _run_streaming([*command, "-e", str(environment), "install"], env=env)


def _reuse_environment(spack_config: Path, environment: Path, compiler: str) -> None:
    """Let the concretizer reuse the compiler that the compiler environment installed, and nothing else.

    Spack takes a compiler only when it is an external or a concrete spec it
    may reuse. A state concretizes everything fresh, so that the same recipes
    give the same hashes on every machine; the compiler is the one exception.
    Reused as the installed package it is, it enters the hash of what it
    builds by its own hash, which is the same wherever it is installed, and
    not by its path, as an external does.

    Only the compiler: the environment also holds what the compiler was built
    with, such as ncurses, readline and gmake, which the system compiler
    compiled. Left reusable, Spack takes them for every package that needs
    them, because it prefers an installed package to a new one. With `include`
    the stack builds its own with the project compiler. What the compiler
    itself links against, zlib-ng and zstd, stays the compiler's.

    @param spack_config: the Spack configuration directory of the state
    @param environment: the directory of the compiler environment
    @param compiler: the compiler spec, such as gcc@15
    @return: nothing
    """
    source = {"type": "environment", "path": str(environment), "include": [compiler]}
    settings = {"concretizer": {"reuse": {"from": [source]}}}
    (spack_config / "concretizer.yaml").write_text(yaml.safe_dump(settings), encoding="utf-8")


def _concretize_as_a_new_state_does(spack_config: Path) -> None:
    """Take out of the configuration what an earlier bootstrap wrote for the compiler.

    The compiler environment has to concretize to the same compiler whenever
    it is concretized. With the compiler rule in place and the earlier compiler
    reusable, its dependencies would be new packages that the rule compiles
    with that earlier compiler, and the result another compiler with another
    hash. A new state has neither, so they are removed first; bootstrap writes
    both again once the compiler is installed.

    @param spack_config: the Spack configuration directory of the state
    @return: nothing
    """
    (spack_config / "concretizer.yaml").write_text(yaml.safe_dump({"concretizer": {"reuse": False}}), encoding="utf-8")

    def change(packages: dict) -> None:
        for language in LANGUAGE_VIRTUALS:
            section = packages.get(language) or {}
            section.pop("require", None)
            if not section:
                packages.pop(language, None)
        requirements = _requirements_of_all(packages)
        requirements[:] = [found for found in requirements if not _is_compiler_rule(found)]

    _edit_packages(spack_config, change)


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


def _edit_packages(spack_config: Path, change: Callable[[dict], None]) -> None:
    """Change the `packages` section of the state's own packages.yaml.

    Written directly, because a requirement with a condition is a mapping,
    which `spack config add` takes only from a file, and removing one entry of
    `packages:all:require` with `spack config remove` removes them all.

    @param spack_config: the Spack configuration directory of the state
    @param change: called with the section, which it changes in place
    @return: nothing
    """
    path = spack_config / "packages.yaml"
    data = (yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None) or {}
    # A new state has `packages::`, which Spack itself rewrites as `packages:`.
    key = next((name for name in data if name.rstrip(":") == "packages"), "packages")
    packages = data.pop(key, None) or {}
    change(packages)
    data["packages"] = packages
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def _requirements_of_all(packages: dict) -> list:
    """The requirements on every package, as the list that the section then holds."""
    everything = packages.setdefault("all", {})
    found = everything.get("require", [])
    everything["require"] = list(found) if isinstance(found, list) else [found]
    return everything["require"]


def _is_compiler_rule(requirement) -> bool:
    """Whether a requirement on every package is a compiler rule that Seanerstack wrote."""
    condition = str(requirement.get("when", "")) if isinstance(requirement, dict) else ""
    return condition.startswith(tuple(f"%{language}=" for language in LANGUAGE_VIRTUALS))


def _require_compiler_where_used(spack_config: Path, languages: tuple[str, ...], compiler: str | None) -> None:
    """Compile every new package with COMPILER, in each of `languages` that the package uses.

    The rule is a requirement on every package, with a condition, and not a
    requirement on the language, because of how Spack 1.2.2 and the develop
    branch of 2026-11-18 treat a compiler that is reused as a package:

    - `packages:c:require:gcc@15` also holds for the compiler's own
      dependencies, which the system compiler built. Nothing satisfies it, and
      Spack searches for minutes before it says so, or without end.
    - A requirement on every package that names a compiler is not applied to
      compilers and their runtime libraries, so the compiler's own tree is
      left alone.
    - The condition `%cxx` also holds for a package that has no C++ itself but
      depends directly on one that has, such as a C library built with CMake,
      and Spack then refuses it. `%cxx=gcc`, "takes C++ from a gcc", holds only
      for the package itself.
    - Spack warns about a single spec with a compiler under `all`, and
      suggests the requirement on the language. `any_of` of the same spec
      twice means the same and has no such warning.

    With `compiler` None, the rules are removed: an external compiler has no
    tree of its own, and is required on the language.

    @param spack_config: the Spack configuration directory of the state
    @param languages: the language virtuals to compile with the compiler
    @param compiler: the compiler spec, such as gcc@15, or None for no rule
    @return: nothing
    """
    rules = []
    if compiler is not None:
        name = re.match(r"[A-Za-z0-9_.+-]+", compiler)
        if not name:
            raise ValueError(f"cannot determine compiler package name from {compiler!r}")
        for language in languages:
            rule = f"%{language}={compiler}"
            rules.append({"any_of": [rule, rule], "when": f"%{language}={name.group(0)}"})

    def change(packages: dict) -> None:
        if compiler is not None:
            # The requirement on the language that an earlier Seanerstack wrote.
            for language in LANGUAGE_VIRTUALS:
                section = packages.get(language) or {}
                section.pop("require", None)
                if not section:
                    packages.pop(language, None)
        requirements = _requirements_of_all(packages)
        requirements[:] = [found for found in requirements if not _is_compiler_rule(found)] + rules

    _edit_packages(spack_config, change)


def require_target(spack_config: Path, target: str) -> None:
    """Build every package for `target`, such as x86_64_v3, not for the host's CPU.

    The target is part of every hash. Without the requirement, each machine
    builds for its own processor, and no hash matches another machine's. The
    compiler rules among the requirements on every package stay as they are.

    @param spack_config: the Spack configuration directory of the state
    @param target: the target to build for
    @return: nothing
    """
    def change(packages: dict) -> None:
        requirements = _requirements_of_all(packages)
        kept = [found for found in requirements if not (isinstance(found, str) and found.startswith("target="))]
        requirements[:] = [f"target={target}", *kept]

    _edit_packages(spack_config, change)


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
    installed_compiler: Callable[[], None] | None = None,
    lockfile: Path | None = None,
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
    @param installed_compiler: called once the compiler environment holds the
        compiler, before anything requires or probes it, so that a caller can
        keep the build whatever happens next; not called for an external
    @param lockfile: the concretized compiler environment of this platform. The
        compiler is installed from it and not concretized here, unless it is
        for another compiler or `source_compiler` names what builds it
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
        if spack_config is not None and not dry_run:
            _require_compiler_where_used(spack_config, (), None)
        return _bootstrap_external(
            compiler, external, languages=languages, probe=probe, command=command,
            env=env, dry_run=dry_run, probe_timeout=probe_timeout,
        )

    if environment is None or spack_config is None:
        raise ValueError("the compiler environment and the Spack configuration of the state are required")
    locked = None if source_compiler else lockfile_for(lockfile, compiler)
    installed = _environment_compiler(command, environment, compiler, env)
    already_installed = installed is not None
    if (force or not already_installed) and not dry_run:
        _ensure_system_compiler(command, env)
        if locked is None:
            _concretize_as_a_new_state_does(spack_config)
        _install_compiler(command, environment, compiler, env, source_compiler, locked)
        installed = _environment_compiler(command, environment, compiler, env)

    if not dry_run:
        if installed is None:
            raise RuntimeError(f"the compiler environment {environment} holds no installation of {compiler!r}")
        if installed_compiler is not None:
            installed_compiler()
        # Before the rule: only a compiler that the concretizer may reuse can
        # satisfy it.
        _reuse_environment(spack_config, environment, compiler)
        _forget_registered_compilers(command, compiler, env)
        _require_compiler_where_used(spack_config, languages, compiler)

    probe_ok = False
    if not dry_run:
        try:
            probe_result = _run(
                [*command, "spec", "--json", probe], check=False, env=env, timeout=probe_timeout
            )
        except subprocess.TimeoutExpired as error:
            raise _probe_timeout(
                probe, probe_timeout, error,
                f"Without a solution, check that the compiler environment {environment} has {compiler} "
                "installed and that `spack config get concretizer` reuses that environment.",
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
        lockfile=locked,
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
        raise _probe_timeout(
            probe, probe_timeout, error,
            f"Without a solution, check that `spack compiler list` reports the compiler in {prefix}.",
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
