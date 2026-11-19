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
    # The prefix of the first stage that built the compiler here, when one did.
    first_stage: str | None = None


@dataclass(frozen=True)
class BootstrapInstance:
    """The Spack instance that builds the first stage of the compiler.

    @param command: its isolated Spack command
    @param env: the environment of that command
    @param environment: the directory of its environment for the first stage
    @param store: its install tree, where the first stage is installed
    """

    command: list[str]
    env: dict
    environment: Path
    store: Path


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


def _package_name(compiler: str) -> str:
    """The package of a compiler spec.

    @param compiler: the compiler spec, such as gcc@15
    @return: its package, such as gcc
    """
    name = re.match(r"[A-Za-z0-9_.+-]+", compiler)
    if not name:
        raise ValueError(f"cannot determine compiler package name from {compiler!r}")
    return name.group(0)


def _first_stage_root(compiler: str, source: str | None = None) -> str:
    """The root spec of the first stage of the compiler, in the bootstrap instance.

    Only what building the compiler of the stack needs: C and C++, without
    GCC's own three-stage bootstrap and without binutils, which take most of
    the time of a full build. The second stage bootstraps itself.

    The system compiler is registered as an external, and an external that
    satisfies the spec is taken instead of a build: on Ubuntu 26.04, `gcc@15`
    alone takes the system GCC 15.2.0 and installs nothing. An external is a
    leaf, so asking for a C compiler as a dependency rules it out.

    @param compiler: the compiler spec, such as gcc@15
    @param source: the registered compiler that builds it, or None for Spack's choice
    @return: the spec that the bootstrap instance installs
    """
    # `:=`, exactly these: `=` would also allow Fortran, which the recipe adds by default.
    return f"{compiler} languages:=c,c++ ~bootstrap ~binutils " + (f"%c,cxx={source}" if source else "%c")


def _second_stage_root(compiler: str) -> str:
    """The root spec of the compiler environment: the compiler, built by its first stage.

    The first stage is the one registered compiler that the spec matches, an
    external, and the compiler asks for it as its C and C++ compiler, which
    also keeps the external itself from being taken as the compiler.

    @param compiler: the compiler spec, such as gcc@15
    @return: the compiler, compiled by the registered compiler of the same spec, the first stage
    """
    return f"{compiler} %c,cxx={compiler}"


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
    return lockfile if roots == [_second_stage_root(compiler)] else None


def _install_environment(command: list[str], environment: Path, env, *, cache_only: bool) -> bool:
    """Install what an environment holds, with `cache_only` only from build caches.

    @param command: the isolated Spack command
    @param environment: the directory of the environment
    @param env: the environment of the command
    @param cache_only: fail instead of building what no build cache holds
    @return: whether everything is installed; a failed build without
        `cache_only` raises CalledProcessError
    """
    args = [*command, "-e", str(environment), "install", *(["--cache-only"] if cache_only else [])]
    try:
        _run_streaming(args, env=env)
    except subprocess.CalledProcessError:
        if not cache_only:
            raise
        return False
    return True


def _build_first_stage(instance: BootstrapInstance, compiler: str, source: str | None) -> str:
    """Build the first stage of the compiler with the system compiler, in the bootstrap instance.

    The first stage is installed without a hash in its path, at
    `store/gcc-VERSION`. One built earlier by another system compiler has a
    different hash at the same path, and is uninstalled first.

    @param instance: the bootstrap instance
    @param compiler: the compiler spec, such as gcc@15
    @param source: the registered compiler that builds it, or None for Spack's choice
    @return: the prefix of the first stage
    """
    command, env, environment = instance.command, instance.env, instance.environment
    _ensure_system_compiler(command, env)
    environment.mkdir(parents=True, exist_ok=True)
    root = _first_stage_root(compiler, source)
    manifest = {"spack": {"specs": [root], "view": False, "concretizer": {"unify": True}}}
    (environment / "spack.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    _run_streaming([*command, "-e", str(environment), "concretize", "--force"], env=env)
    roots = json.loads((environment / "spack.lock").read_text(encoding="utf-8")).get("roots", [])
    if len(roots) != 1:
        raise RuntimeError(f"the first stage {environment} has {len(roots)} roots, not one")
    wanted = roots[0]["hash"]
    found = _run([*command, "find", "--json", _package_name(compiler)], check=False, env=env)
    for spec in json.loads(found.stdout or "[]") if found.returncode == 0 else []:
        if not spec.get("external") and spec.get("hash") != wanted:
            _run([*command, "uninstall", "--yes-to-all", f"/{spec['hash']}"], env=env)
    _run_streaming([*command, "-e", str(environment), "install"], env=env)
    return _run([*command, "location", "--install-dir", f"/{wanted}"], env=env).stdout.strip()


def _use_first_stage(command: list[str], compiler: str, prefix: str, env) -> None:
    """Make the first stage the only compiler of its kind in the actual instance.

    Every gcc that the actual instance knows, such as the system's, is
    removed, so that the first stage compiles the whole compiler environment
    and nothing in it records the system compiler.

    @param command: the isolated Spack command of the actual instance
    @param compiler: the compiler spec, such as gcc@15
    @param prefix: the prefix of the first stage
    @param env: the environment of the command
    @return: nothing
    """
    _run([*command, "compiler", "remove", "-a", _package_name(compiler)], check=False, env=env)
    _register_compiler(command, prefix, env)


def _stage_external_path(lockfile: Path, compiler: str) -> str | None:
    """The path of the first stage that a lockfile of the compiler environment records.

    @param lockfile: a lockfile of the compiler environment
    @param compiler: the compiler spec, such as gcc@15
    @return: the path of the external of that compiler, or None when the lockfile has none
    """
    name = _package_name(compiler)
    specs = json.loads(lockfile.read_text(encoding="utf-8")).get("concrete_specs", {})
    for spec in specs.values():
        if spec.get("name") == name and "external" in spec:
            return spec["external"].get("path")
    return None


def _install_in_two_stages(
    command: list[str], environment: Path, compiler: str, env, *, instance: BootstrapInstance,
    source: str | None, lockfile: Path | None, spack_config: Path, cache_only: bool,
) -> str | None:
    """Install the compiler in the compiler environment, built by a first stage of itself.

    The environment records which installation is the compiler, with
    everything it links to: its lockfile is what the concretizer reuses.

    The system compiler builds the first stage in the bootstrap instance. The
    actual instance knows it only as an external, the one gcc it has, and that
    external builds the compiler with everything it links against. Nothing in
    the compiler environment then records the system compiler, which Spack's
    gcc recipe would refuse where it is newer than the compiler, such as the
    GCC 16 of Fedora 44 and 45.

    With `lockfile`, the compiler of the lockfile comes from the build caches,
    without the first stage. When the caches lack it, `cache_only` stops; else
    the first stage is built and the lockfile installed with it, which works
    only in the state directory that made the lockfile, because the lockfile
    records the path of the first stage.

    @param command: the isolated Spack command of the actual instance
    @param environment: the directory of the compiler environment
    @param compiler: the compiler spec, such as gcc@15
    @param env: the environment of the command
    @param instance: the bootstrap instance
    @param source: the registered compiler that builds the first stage, or None for Spack's choice
    @param lockfile: the concretized compiler environment to install, or None to concretize here
    @param spack_config: the Spack configuration directory of the state
    @param cache_only: with `lockfile`, fail instead of building
    @return: the prefix of the first stage that built the compiler, or None when the caches held it
    """
    environment.mkdir(parents=True, exist_ok=True)
    manifest = {"spack": {"specs": [_second_stage_root(compiler)], "view": False, "concretizer": {"unify": True}}}
    (environment / "spack.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    if lockfile is not None:
        shutil.copyfile(lockfile, environment / "spack.lock")
        if _install_environment(command, environment, env, cache_only=True):
            return None
        if cache_only:
            raise RuntimeError(
                f"the build caches do not hold the compiler of the lockfile {lockfile}, and it is not built here. "
                "`seanerstack buildcache explain` shows what the caches hold; --concretize builds the compiler on this "
                "machine, in two stages, which takes hours."
            )
        recorded = _stage_external_path(lockfile, compiler)
        if recorded is not None and Path(recorded).parent != instance.store:
            raise RuntimeError(
                f"the lockfile {lockfile} records the first stage in {recorded}, and this state builds it in "
                f"{instance.store}; build the compiler in the state directory that made the lockfile, or concretize it"
            )
        prefix = _build_first_stage(instance, compiler, source)
        _use_first_stage(command, compiler, prefix, env)
        _install_environment(command, environment, env, cache_only=False)
        return prefix
    _concretize_as_a_new_state_does(spack_config)
    prefix = _build_first_stage(instance, compiler, source)
    _use_first_stage(command, compiler, prefix, env)
    _run_streaming([*command, "-e", str(environment), "concretize", "--force"], env=env)
    _install_environment(command, environment, env, cache_only=False)
    return prefix


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
        name = _package_name(compiler)
        for language in languages:
            rule = f"%{language}={compiler}"
            rules.append({"any_of": [rule, rule], "when": f"%{language}={name}"})

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
    bootstrap_instance: BootstrapInstance | None = None,
    cache_only: bool = False,
) -> BootstrapResult:
    """Make COMPILER the compiler of every SEANERGYS build.

    Without `external`, Spack installs COMPILER in the compiler environment
    unless it already has, and the concretizer reuses that installation as
    the package it is. It is built in two stages: `source_compiler`, or
    Spack's choice of the system compilers, builds a first stage in the
    bootstrap instance, and that first stage builds COMPILER. With
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
    @param bootstrap_instance: the Spack instance that builds the first stage
        of the compiler; needed wherever the compiler is installed
    @param cache_only: with a lockfile, take the compiler from the build
        caches or fail, and never build it
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
    first_stage = None
    if (force or not already_installed) and not dry_run:
        if bootstrap_instance is None:
            raise ValueError("installing the compiler needs the bootstrap instance that builds its first stage")
        first_stage = _install_in_two_stages(
            command, environment, compiler, env, instance=bootstrap_instance, source=source_compiler,
            lockfile=locked, spack_config=spack_config, cache_only=cache_only,
        )
        installed = _environment_compiler(command, environment, compiler, env)

    if not dry_run:
        if installed is None:
            raise RuntimeError(f"the compiler environment {environment} holds no installation of {compiler!r}")
        if installed_compiler is not None:
            installed_compiler()
        if first_stage is not None:
            # The first stage only built the compiler. The system compilers come
            # back, for --source-compiler, and the rule keeps them from the stack.
            _run([*command, "compiler", "remove", "-a", _package_name(compiler)], check=False, env=env)
            _ensure_system_compiler(command, env)
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
        first_stage=first_stage,
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
