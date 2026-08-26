# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
import re
import shutil
import subprocess


DEFAULT_LANGUAGES = ("c", "cxx", "fortran")
DEFAULT_PROBE = "zlib"
DEFAULT_SCOPE = "user"


@dataclass(frozen=True)
class BootstrapResult:
    compiler: str
    installed: bool
    scope: str
    languages: tuple[str, ...]
    probe: str
    probe_ok: bool


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def _compiler_installed(compiler: str) -> bool:
    result = _run(["spack", "location", "-i", compiler], check=False)
    return result.returncode == 0


def _compiler_name(compiler: str) -> str:
    match = re.match(r"([A-Za-z0-9_.+-]+)", compiler)
    if not match:
        raise ValueError(f"cannot determine compiler package name from {compiler!r}")
    return match.group(1)


def _set_language_requirement(scope: str, language: str, compiler: str) -> None:
    # Remove an earlier Seanstack-style single requirement before adding the new
    # one. A missing path is harmless and is intentionally ignored.
    _run(
        ["spack", "config", "--scope", scope, "remove", f"packages:{language}:require"],
        check=False,
    )
    _run(
        ["spack", "config", "--scope", scope, "add", f"packages:{language}:require:{compiler}"]
    )


def bootstrap(
    compiler: str,
    *,
    languages: tuple[str, ...] = DEFAULT_LANGUAGES,
    probe: str = DEFAULT_PROBE,
    scope: str = DEFAULT_SCOPE,
    force: bool = False,
    dry_run: bool = False,
) -> BootstrapResult:
    if shutil.which("spack") is None:
        raise RuntimeError("spack executable not found in PATH")
    if not languages:
        raise ValueError("at least one compiler language is required")

    already_installed = _compiler_installed(compiler)
    if (force or not already_installed) and not dry_run:
        _run(["spack", "install", compiler])

    if not dry_run:
        for language in languages:
            _set_language_requirement(scope, language, compiler)

    probe_ok = False
    if not dry_run:
        probe_result = _run(["spack", "spec", probe], check=False)
        if probe_result.returncode != 0:
            message = probe_result.stderr.strip() or probe_result.stdout.strip()
            raise RuntimeError(f"Spack could not concretize compiler probe {probe!r}:\n{message}")
        compiler_name = _compiler_name(compiler)
        probe_ok = compiler_name in (probe_result.stdout + probe_result.stderr)

    return BootstrapResult(
        compiler=compiler,
        installed=already_installed or not dry_run,
        scope=scope,
        languages=languages,
        probe=probe,
        probe_ok=probe_ok,
    )
