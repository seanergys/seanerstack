# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import subprocess


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


def _compiler_prefix(command: list[str], compiler: str, env) -> str | None:
    # Once a build has used the compiler, the database also holds an external
    # record for the same prefix, so `location -i COMPILER` is ambiguous. Only a
    # real installation counts.
    result = _run([*command, "find", "--json", compiler], check=False, env=env)
    if result.returncode != 0:
        return None
    hashes = [spec["hash"] for spec in json.loads(result.stdout or "[]") if not spec.get("external")]
    if not hashes:
        return None
    if len(hashes) > 1:
        raise RuntimeError(f"{compiler!r} matches {len(hashes)} installations; use a more specific spec")
    result = _run([*command, "location", "-i", f"/{hashes[0]}"], check=False, env=env)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


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


def _install_compiler(command: list[str], compiler: str, env) -> None:
    """Build the compiler, even where the system compiler has the same version.

    The system compiler is registered as an external, and an external that
    satisfies the spec is taken instead of a build: on Ubuntu 26.04,
    `install gcc@15` takes the system GCC 15.2.0 and installs nothing. An
    external is a leaf, so asking for a C compiler as a dependency rules it
    out, while the system compiler can still be that dependency.
    """
    _run_streaming([*command, "install", compiler, "%c"], env=env)


def _replace_registered_compilers(command: list[str], compiler: str, prefix: str, env) -> None:
    """Make the installed compiler the only registered compiler of its name.

    The system compiler that built it stays registered, and the language
    requirements would accept it too where its version matches, so packages
    could be built with it instead. A name without registered compilers makes
    `compiler remove` fail, which is fine.
    """
    _run([*command, "compiler", "remove", "-a", _compiler_name(compiler)], check=False, env=env)
    _register_compiler(command, prefix, env)


def _compiler_name(compiler: str) -> str:
    match = re.match(r"([A-Za-z0-9_.+-]+)", compiler)
    if not match:
        raise ValueError(f"cannot determine compiler package name from {compiler!r}")
    return match.group(1)


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
) -> BootstrapResult:
    """Make COMPILER the compiler of every SEANERGYS build.

    Without `external`, Spack installs COMPILER unless it already has, and the
    installation is registered as an external. With `external`, a compiler
    already in that prefix, such as /usr or a gcc-toolset, is registered
    instead and nothing is built; COMPILER must name it.
    """
    command = command or ["spack"]
    if not languages:
        raise ValueError("at least one compiler language is required")
    if external is not None:
        if force:
            raise ValueError("--force builds the compiler, and an external compiler is not built")
        if not os.path.isdir(external):
            raise ValueError(f"external compiler prefix is not a directory: {external}")
        return _bootstrap_external(
            compiler, external, languages=languages, probe=probe, command=command,
            env=env, dry_run=dry_run, probe_timeout=probe_timeout,
        )

    prefix = _compiler_prefix(command, compiler, env)
    already_installed = prefix is not None
    if (force or not already_installed) and not dry_run:
        _ensure_system_compiler(command, env)
        _install_compiler(command, compiler, env)
        prefix = _compiler_prefix(command, compiler, env)

    registered = False
    if not dry_run:
        if prefix is None:
            raise RuntimeError(
                f"Spack reports no installation prefix for {compiler!r}; "
                "cannot register it as a compiler"
            )
        _replace_registered_compilers(command, compiler, prefix, env)
        registered = True
        for language in languages:
            _set_language_requirement(command, language, compiler, env)

    probe_ok = False
    if not dry_run:
        try:
            probe_result = _run(
                [*command, "spec", probe], check=False, env=env, timeout=probe_timeout
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"Spack did not concretize compiler probe {probe!r} within "
                f"{probe_timeout:g} seconds. This usually means the {compiler} "
                "requirement cannot be satisfied: check that `spack compiler list` "
                "reports it and that `spack config get packages` lists it under "
                "`gcc: externals`."
            ) from error
        if probe_result.returncode != 0:
            message = probe_result.stderr.strip() or probe_result.stdout.strip()
            raise RuntimeError(f"Spack could not concretize compiler probe {probe!r}:\n{message}")
        compiler_name = _compiler_name(compiler)
        probe_ok = compiler_name in (probe_result.stdout + probe_result.stderr)

    return BootstrapResult(
        compiler=compiler,
        installed=already_installed or not dry_run,
        registered=registered,
        languages=languages,
        probe=probe,
        probe_ok=probe_ok,
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
