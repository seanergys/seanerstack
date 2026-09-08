# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess


DEFAULT_LANGUAGES = ("c", "cxx", "fortran")
DEFAULT_PROBE = "zlib"


@dataclass(frozen=True)
class BootstrapResult:
    compiler: str
    installed: bool
    languages: tuple[str, ...]
    probe: str
    probe_ok: bool


def _run(args: list[str], *, check: bool = True, env=None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True, env=env)


def _compiler_installed(command: list[str], compiler: str, env) -> bool:
    result = _run([*command, "location", "-i", compiler], check=False, env=env)
    return result.returncode == 0


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
) -> BootstrapResult:
    command = command or ["spack"]
    if not languages:
        raise ValueError("at least one compiler language is required")

    already_installed = _compiler_installed(command, compiler, env)
    if (force or not already_installed) and not dry_run:
        _run([*command, "install", compiler], env=env)

    if not dry_run:
        for language in languages:
            _set_language_requirement(command, language, compiler, env)

    probe_ok = False
    if not dry_run:
        probe_result = _run([*command, "spec", probe], check=False, env=env)
        if probe_result.returncode != 0:
            message = probe_result.stderr.strip() or probe_result.stdout.strip()
            raise RuntimeError(f"Spack could not concretize compiler probe {probe!r}:\n{message}")
        compiler_name = _compiler_name(compiler)
        probe_ok = compiler_name in (probe_result.stdout + probe_result.stderr)

    return BootstrapResult(
        compiler=compiler,
        installed=already_installed or not dry_run,
        languages=languages,
        probe=probe,
        probe_ok=probe_ok,
    )
