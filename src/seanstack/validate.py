# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ast
import shutil
import subprocess
import tempfile

import yaml

from .bootstrap import DEFAULT_LANGUAGES, DEFAULT_SCOPE
from .config import Config
from .secrets import SecretStore
from .paths import environments_path, repository_path
from .sync import package_paths, sync_many


@dataclass(frozen=True)
class Finding:
    level: str
    subject: str
    message: str


def _validate_packages(repository: Path) -> list[Finding]:
    findings: list[Finding] = []
    for name, path in package_paths(repository).items():
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            findings.append(Finding("ok", f"package:{name}", "Python syntax is valid"))
        except SyntaxError as error:
            findings.append(Finding("error", f"package:{name}", str(error)))
    return findings


def _validate_environments(environments: Path) -> list[Finding]:
    findings: list[Finding] = []
    if not environments.is_dir():
        return [Finding("error", "environments", "environment directory does not exist")]

    for directory in sorted(path for path in environments.iterdir() if path.is_dir()):
        manifest = directory / "spack.yaml"
        if not manifest.is_file():
            findings.append(Finding("error", f"environment:{directory.name}", "spack.yaml is missing"))
            continue
        try:
            data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as error:
            findings.append(Finding("error", f"environment:{directory.name}", f"invalid YAML: {error}"))
            continue
        if not isinstance(data.get("spack"), dict):
            findings.append(Finding("error", f"environment:{directory.name}", "top-level 'spack' mapping is missing"))
            continue
        findings.append(Finding("ok", f"environment:{directory.name}", "manifest is structurally valid"))

        develop = data["spack"].get("develop", {}) or {}
        if isinstance(develop, dict):
            for package, entry in develop.items():
                if not isinstance(entry, dict) or "path" not in entry:
                    continue
                target = (directory / str(entry["path"])).resolve()
                if target.exists():
                    findings.append(Finding("ok", f"develop:{package}", f"{target} exists"))
                else:
                    findings.append(Finding("error", f"develop:{package}", f"{target} does not exist"))
    return findings


def _requirements(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict) and isinstance(item.get("spec"), str):
                result.append(item["spec"])
        return result
    return []


def _validate_compiler(compiler: str, languages: tuple[str, ...], scope: str) -> list[Finding]:
    if shutil.which("spack") is None:
        return [Finding("error", "compiler", "spack executable not found in PATH")]

    process = subprocess.run(
        ["spack", "config", "--scope", scope, "get", "packages"],
        text=True,
        capture_output=True,
    )
    if process.returncode != 0:
        message = process.stderr.strip() or process.stdout.strip() or "could not read Spack packages configuration"
        return [Finding("error", "compiler", message)]

    data = yaml.safe_load(process.stdout) or {}
    packages = data.get("packages", {}) if isinstance(data, dict) else {}
    findings: list[Finding] = []
    for language in languages:
        require = _requirements(packages.get(language, {}).get("require") if isinstance(packages.get(language), dict) else None)
        if compiler in require:
            findings.append(Finding("ok", f"compiler:{language}", f"requires {compiler} in Spack scope {scope}"))
        else:
            findings.append(
                Finding(
                    "error",
                    f"compiler:{language}",
                    f"does not require {compiler} in Spack scope {scope}; run `seanstack toolchain bootstrap {compiler}`",
                )
            )
    return findings


def _validate_with_spack(environments: Path) -> list[Finding]:
    if shutil.which("spack") is None:
        return [Finding("error", "spack", "spack executable not found in PATH")]

    findings: list[Finding] = []
    for directory in sorted(path for path in environments.iterdir() if path.is_dir() and (path / "spack.yaml").is_file()):
        with tempfile.TemporaryDirectory(prefix="seanstack-validate-") as temp:
            temp_env = Path(temp) / directory.name
            shutil.copytree(directory, temp_env)
            process = subprocess.run(
                ["spack", "-e", str(temp_env), "concretize", "-f"],
                text=True,
                capture_output=True,
            )
            if process.returncode == 0:
                findings.append(Finding("ok", f"spack:{directory.name}", "environment concretizes"))
            else:
                message = process.stderr.strip() or process.stdout.strip() or "concretization failed"
                findings.append(Finding("error", f"spack:{directory.name}", message))
    return findings


def _validate_resources(repository: Path, config: Config) -> list[Finding]:
    findings: list[Finding] = []
    for name, path in package_paths(repository).items():
        from .recipe import parse_recipe
        recipe = parse_recipe(path)
        if not recipe.seanstack_resource:
            continue
        try:
            resource = config.resource(recipe.seanstack_resource)
        except ValueError as error:
            findings.append(Finding("error", f"resource:{name}", str(error)))
            continue
        if resource.kind != "git":
            findings.append(Finding("error", f"resource:{name}", f"{resource.name} is {resource.kind}, expected git"))
        elif recipe.git and not recipe.git.startswith(resource.url):
            findings.append(Finding("error", f"resource:{name}", f"Git URL is outside resource {resource.name}"))
        else:
            findings.append(Finding("ok", f"resource:{name}", f"uses {resource.name}"))
    return findings


def validate(
    *,
    online: bool = False,
    with_spack: bool = False,
    compiler: str | None = None,
    languages: tuple[str, ...] = DEFAULT_LANGUAGES,
    scope: str = DEFAULT_SCOPE,
    repository: Path | None = None,
    environments: Path | None = None,
    config: Config | None = None,
    secrets: SecretStore | None = None,
) -> list[Finding]:
    repository = repository or repository_path()
    environments = environments or environments_path()
    findings = _validate_packages(repository) + _validate_environments(environments)
    if config is not None:
        findings.extend(_validate_resources(repository, config))

    if online:
        results = sync_many(
            package_paths(repository),
            repository=repository,
            check=True,
            config=config,
            secrets=secrets,
        )
        for result in results:
            if result.changed:
                missing = ", ".join(result.missing_versions + result.missing_branches)
                findings.append(Finding("error", f"sync:{result.package}", f"recipe is out of sync: {missing}"))
            else:
                findings.append(Finding("ok", f"sync:{result.package}", "recipe is synchronized with upstream"))

    if compiler:
        findings.extend(_validate_compiler(compiler, languages, scope))

    if with_spack:
        findings.extend(_validate_with_spack(environments))
    return findings
