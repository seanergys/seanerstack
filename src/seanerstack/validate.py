# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ast
import shutil
import subprocess
import tempfile

import yaml

from .auth import git_auth
from .bootstrap import DEFAULT_LANGUAGES
from .config import Config
from .secrets import SecretStore
from .paths import environments_path, repository_path
from .sync import package_paths, read_remote_refs, sync_many


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


def _validate_compiler(compiler: str, languages: tuple[str, ...], command: list[str], env) -> list[Finding]:
    process = subprocess.run(
        [*command, "config", "get", "packages"],
        text=True,
        capture_output=True, env=env,
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
            findings.append(Finding("ok", f"compiler:{language}", f"requires {compiler} in the isolated Seanerstack configuration"))
        else:
            findings.append(
                Finding(
                    "error",
                    f"compiler:{language}",
                    f"does not require {compiler} in the isolated Seanerstack configuration; run `seanerstack toolchain bootstrap {compiler}`",
                )
            )
    return findings


def _validate_with_spack(environments: Path, command: list[str], env) -> list[Finding]:
    findings: list[Finding] = []
    for directory in sorted(path for path in environments.iterdir() if path.is_dir() and (path / "spack.yaml").is_file()):
        with tempfile.TemporaryDirectory(prefix="seanerstack-validate-") as temp:
            temp_env = Path(temp) / directory.name
            shutil.copytree(directory, temp_env)
            process = subprocess.run(
                [*command, "-e", str(temp_env), "concretize", "-f"],
                text=True,
                capture_output=True, env=env,
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
        if not recipe.seanerstack_resource:
            continue
        try:
            resource = config.resource(recipe.seanerstack_resource)
        except ValueError as error:
            findings.append(Finding("error", f"resource:{name}", str(error)))
            continue
        if resource.kind != "git":
            findings.append(Finding("error", f"resource:{name}", f"{resource.name} is {resource.kind}, expected git"))
        elif recipe.git and not recipe.git.startswith(resource.url):
            findings.append(Finding("error", f"resource:{name}", f"Git URL is outside resource {resource.name}"))
        elif recipe.url and any(
            directive.name == "version" and "sha256" in directive.kwargs for directive in recipe.directives
        ) and not recipe.url.startswith(resource.url):
            findings.append(Finding("error", f"resource:{name}", f"archive URL is outside resource {resource.name}"))
        else:
            findings.append(Finding("ok", f"resource:{name}", f"uses {resource.name}"))
    return findings


def _validate_resource_options(config: Config) -> list[Finding]:
    """Warnings about options of a resource that its URL has no use for.

    They are warnings, not errors, so that every config.toml that loaded
    before still passes.

    @param config: the Seanerstack configuration
    @return: one warning for each such option
    """
    findings: list[Finding] = []
    for name, resource in config.resources.items():
        if resource.endpoint_url and not resource.s3:
            findings.append(Finding(
                "warning", f"resource:{name}",
                f"endpoint_url names an S3 service and takes effect only with an s3:// URL, not {resource.url}",
            ))
    return findings


def check_git_access(
    config: Config, secrets: SecretStore, *, repository: Path | None = None, every_recipe: bool = False
) -> list[tuple[str, bool, str]]:
    """Whether each Git resource can be read, tried on one recipe that uses it.

    Access to a resource can still differ between its repositories: a CI job
    token reads only the projects that allow it. `every_recipe` checks them all.

    @param config: the resources
    @param secrets: their credentials
    @param repository: the recipes (default: the shipped repository)
    @param every_recipe: check every recipe of a Git resource, not just one per resource
    @return: one (name, readable, message) for each Git resource of `config` that a recipe uses,
        or with `every_recipe`, for each such recipe, named after its package
    """
    from .recipe import parse_recipe
    results: list[tuple[str, bool, str]] = []
    checked: set[str] = set()
    for package, path in package_paths(repository or repository_path()).items():
        recipe = parse_recipe(path)
        name = recipe.seanerstack_resource
        if not name or name in checked or not recipe.git:
            continue
        # A config that does not declare the resource does not use its recipes.
        resource = config.resources.get(name)
        if resource is None or resource.kind != "git":
            continue
        if not every_recipe:
            checked.add(name)
        subject = package if every_recipe else name
        try:
            read_remote_refs(recipe.git, auth=git_auth(resource, secrets))
        except subprocess.CalledProcessError as error:
            results.append((subject, False, (error.stderr or "").strip() or f"cannot read {recipe.git}"))
        except (RuntimeError, ValueError) as error:
            results.append((subject, False, str(error)))
        else:
            results.append((subject, True, f"reads {recipe.git}"))
    return results


def validate(
    *,
    online: bool = False,
    access: bool = False,
    with_spack: bool = False,
    compiler: str | None = None,
    languages: tuple[str, ...] = DEFAULT_LANGUAGES,
    spack_command: list[str] | None = None,
    spack_env=None,
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
        findings.extend(_validate_resource_options(config))

    if access:
        if config is None or secrets is None:
            raise ValueError("access validation requires the configuration and its credentials")
        for package, ok, message in check_git_access(config, secrets, repository=repository, every_recipe=True):
            findings.append(Finding("ok" if ok else "error", f"access:{package}", message))

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
        if spack_command is None:
            raise ValueError("compiler validation requires isolated Spack runtime")
        findings.extend(_validate_compiler(compiler, languages, spack_command, spack_env))

    if with_spack:
        if spack_command is None:
            raise ValueError("Spack validation requires isolated Spack runtime")
        findings.extend(_validate_with_spack(environments, spack_command, spack_env))
    return findings
