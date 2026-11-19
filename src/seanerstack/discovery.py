# SPDX-License-Identifier: Apache-2.0
"""What is installed on the machine: the compilers Spack registers, and packages it could use.

`seanerstack init` finds both and prints them; `seanerstack toolchain bootstrap`
then chooses among them by name, with --source-compiler and --external.
Compilers are registered, because building the toolchain needs one. Packages
are only detected: one registered as an external would replace every build of
it, so it is registered only when chosen.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess

import yaml

from .isolation import SpackLayout


# Run by `spack python`, so that it uses the Spack of the session.
DETECT_SCRIPT = Path(__file__).with_name("_spack_detect.py")


@dataclass(frozen=True)
class Found:
    """An installed compiler or package, as Spack names it, and where it is."""

    spec: str
    prefix: str

    @property
    def name(self) -> str:
        return re.split(r"[@\s%^+~]", self.spec, maxsplit=1)[0]

    @property
    def version(self) -> str:
        match = re.match(r"[^@\s]+@=?([^\s%^+~]+)", self.spec)
        return match.group(1) if match else ""


def search_directories(prefixes: list[Path]) -> list[Path]:
    """The directories to search below each prefix: its bin directory, where there is one."""
    return [prefix / "bin" if (prefix / "bin").is_dir() else prefix for prefix in prefixes]


def find_compilers(command: list[str], env, prefixes: list[Path]) -> None:
    """Register the compilers on PATH, and those below `prefixes`, with Spack.

    @param command: the isolated Spack command
    @param env: its environment
    @param prefixes: installations off PATH, such as a gcc-toolset under /opt/rh
    @return: nothing; Spack writes them into the state's packages.yaml
    """
    subprocess.run([*command, "compiler", "find"], check=False, capture_output=True, text=True, env=env)
    if prefixes:
        directories = [str(directory) for directory in search_directories(prefixes)]
        subprocess.run([*command, "compiler", "find", *directories], check=False, capture_output=True, text=True, env=env)


def registered_compilers(x: SpackLayout) -> list[Found]:
    """The compilers registered in the state, from its packages.yaml.

    @param x: the state
    @return: each registered compiler, sorted by spec
    """
    path = x.config / "packages.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
    packages = (data or {}).get("packages") or (data or {}).get("packages:") or {}
    found = []
    for package in packages.values():
        for external in (package or {}).get("externals") or []:
            if (external.get("extra_attributes") or {}).get("compilers"):
                found.append(Found(spec=str(external["spec"]).split()[0], prefix=str(external["prefix"])))
    return sorted(set(found), key=lambda item: (item.name, item.version, item.prefix))


def detect_packages(command: list[str], env, packages: list[str], prefixes: list[Path]) -> dict[str, list[Found]]:
    """Packages installed on PATH or below `prefixes`, without registering them.

    @param command: the isolated Spack command
    @param env: its environment
    @param packages: the Spack packages to look for, such as rust
    @param prefixes: installations off PATH to search as well
    @return: each package that was found, with every installation of it;
        a failed detection raises RuntimeError with what Spack said
    """
    if not packages:
        return {}
    paths = [f"--path={directory}" for directory in search_directories(prefixes)]
    result = subprocess.run(
        [*command, "python", str(DETECT_SCRIPT), *packages, *paths],
        check=False, capture_output=True, text=True, env=env,
    )
    if result.returncode != 0:
        # What Spack said is the cause; the command alone names none.
        message = result.stderr.strip() or result.stdout.strip() or f"exit status {result.returncode}"
        raise RuntimeError(f"Spack could not detect {', '.join(packages)}: {message}")
    lines = [line for line in result.stdout.splitlines() if line.startswith("{")]
    raw = json.loads(lines[-1]) if lines else {}
    return {name: [Found(spec=entry["spec"].split()[0], prefix=entry["prefix"]) for entry in entries] for name, entries in raw.items()}


def save_detected(x: SpackLayout, detected: dict[str, list[Found]]) -> None:
    """Keep what init detected, for `toolchain bootstrap --external`."""
    x.detected.write_text(
        json.dumps({name: [asdict(item) for item in items] for name, items in detected.items()}, indent=2) + "\n",
        encoding="utf-8",
    )


def load_detected(x: SpackLayout) -> dict[str, list[Found]]:
    """What init detected in the state; nothing before init."""
    if not x.detected.is_file():
        return {}
    raw = json.loads(x.detected.read_text(encoding="utf-8"))
    return {name: [Found(**item) for item in items] for name, items in raw.items()}


def matching(found: list[Found], wanted: str) -> list[Found]:
    """The entries that `wanted` names: a name, or a name and a version or its start.

    `gcc@16` matches gcc@16.2.1 but not gcc@161; `gcc` matches every gcc.
    """
    name, _, version = wanted.partition("@")
    version = version.lstrip("=")
    return [
        item for item in found
        if item.name == name and (not version or item.version == version or item.version.startswith(version + "."))
    ]


def describe(found: list[Found]) -> list[str]:
    """One line for each entry, spec and prefix in columns."""
    width = max((len(item.spec) for item in found), default=0)
    return [f"{item.spec.ljust(width)}  {item.prefix}" for item in found]
