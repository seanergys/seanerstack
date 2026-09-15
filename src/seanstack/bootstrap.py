# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
import json
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


def _register_compiler(command: list[str], prefix: str, env) -> None:
    """Register an installed compiler as an external package.

    Must run before the language requirements are written. Those apply to
    every node needing `c`/`cxx`/`fortran`, including the ones in the
    compiler's own build tree, which the system compiler built, so they forbid
    reusing the compiler just installed and leave no solution. An external node
    has no build dependencies and so contradicts nothing.
    """
    _run([*command, "compiler", "find", prefix], env=env)


def _compiler_name(compiler: str) -> str:
    match = re.match(r"([A-Za-z0-9_.+-]+)", compiler)
    if not match:
        raise ValueError(f"cannot determine compiler package name from {compiler!r}")
    return match.group(1)


def _set_language_requirement(command: list[str], language: str, compiler: str, env) -> None:
    # Remove an earlier Seanstack-style single requirement before adding the new
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
) -> BootstrapResult:
    command = command or ["spack"]
    if not languages:
        raise ValueError("at least one compiler language is required")

    prefix = _compiler_prefix(command, compiler, env)
    already_installed = prefix is not None
    if (force or not already_installed) and not dry_run:
        _run_streaming([*command, "install", compiler], env=env)
        prefix = _compiler_prefix(command, compiler, env)

    registered = False
    if not dry_run:
        if prefix is None:
            raise RuntimeError(
                f"Spack reports no installation prefix for {compiler!r}; "
                "cannot register it as a compiler"
            )
        _register_compiler(command, prefix, env)
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
