# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from .auth import GitAuth, git_environment
from .config import Config
from .secrets import SecretStore
from typing import Iterable

from packaging.version import InvalidVersion, Version

from .paths import repository_path
from .recipe import Recipe, parse_recipe


@dataclass(frozen=True)
class RemoteRefs:
    tags: dict[str, str]
    heads: dict[str, str]


@dataclass(frozen=True)
class SyncResult:
    package: str
    changed: bool
    missing_versions: tuple[str, ...]
    missing_branches: tuple[str, ...]


@dataclass(frozen=True)
class TagConvention:
    prefix: str
    suffix: str

    def version_from_tag(self, tag: str) -> str | None:
        if not tag.startswith(self.prefix):
            return None
        if self.suffix and not tag.endswith(self.suffix):
            return None
        end = len(tag) - len(self.suffix) if self.suffix else len(tag)
        version = tag[len(self.prefix):end]
        if not version:
            return None
        # Keep synchronization conservative. Spack accepts a broad version
        # grammar, but existing Seanstack release recipes use PEP 440-compatible
        # version strings and packaging gives us reliable ordering as well.
        try:
            Version(version)
        except InvalidVersion:
            return None
        return version


def package_paths(repository: Path | None = None) -> dict[str, Path]:
    packages = (repository or repository_path()) / "packages"
    if not packages.is_dir():
        return {}
    result: dict[str, Path] = {}
    for directory in sorted(path for path in packages.iterdir() if path.is_dir()):
        recipe = directory / "package.py"
        if recipe.is_file():
            result[directory.name.replace("_", "-")] = recipe
    return result


def read_remote_refs(remote: str, *, auth: GitAuth | None = None) -> RemoteRefs:
    with git_environment(auth) as env:
        process = subprocess.run(
            ["git", "ls-remote", "--heads", "--tags", remote],
            check=True,
            text=True,
            capture_output=True,
            env=env,
        )
    tags: dict[str, str] = {}
    dereferenced: dict[str, str] = {}
    heads: dict[str, str] = {}
    for line in process.stdout.splitlines():
        if not line.strip():
            continue
        commit, ref = line.split(maxsplit=1)
        if ref.startswith("refs/heads/"):
            heads[ref.removeprefix("refs/heads/")] = commit
        elif ref.startswith("refs/tags/"):
            tag = ref.removeprefix("refs/tags/")
            if tag.endswith("^{}"):
                dereferenced[tag[:-3]] = commit
            else:
                tags[tag] = commit
    tags.update(dereferenced)
    return RemoteRefs(tags=tags, heads=heads)


def _release_versions(recipe: Recipe) -> set[str]:
    return {
        str(directive.args[0])
        for directive in recipe.directives
        if directive.name == "version" and directive.args
    }


def _tracked_branches(recipe: Recipe) -> dict[str, str]:
    return {
        str(directive.kwargs["branch"]): str(directive.args[0])
        for directive in recipe.directives
        if directive.name == "version"
        and directive.args
        and isinstance(directive.kwargs.get("branch"), str)
    }


def infer_tag_convention(recipe: Recipe) -> TagConvention:
    conventions: set[tuple[str, str]] = set()
    for directive in recipe.directives:
        if directive.name != "version" or not directive.args:
            continue
        tag = directive.kwargs.get("tag")
        if not isinstance(tag, str):
            continue
        version = str(directive.args[0])
        first = tag.find(version)
        if first < 0 or tag.find(version, first + len(version)) >= 0:
            raise ValueError(
                f"{recipe.path}: cannot infer tag convention from "
                f'version("{version}", tag="{tag}")'
            )
        conventions.add((tag[:first], tag[first + len(version):]))

    if not conventions:
        raise ValueError(
            f"{recipe.path}: cannot infer release-tag convention; "
            "add at least one version(..., tag=...) directive"
        )
    if len(conventions) != 1:
        rendered = ", ".join(f"{prefix}{{version}}{suffix}" for prefix, suffix in sorted(conventions))
        raise ValueError(f"{recipe.path}: inconsistent release-tag conventions: {rendered}")

    prefix, suffix = next(iter(conventions))
    return TagConvention(prefix=prefix, suffix=suffix)


def _version_key(value: str) -> tuple[int, Version | str]:
    try:
        return (1, Version(value))
    except InvalidVersion:
        return (0, value)


def _insert_releases(path: Path, recipe: Recipe, releases: list[tuple[str, str, str]]) -> None:
    if not releases:
        return

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    version_directives = [directive for directive in recipe.directives if directive.name == "version"]
    if version_directives:
        branch_directives = [directive for directive in version_directives if directive.kwargs.get("branch")]
        anchor = (branch_directives[-1] if branch_directives else version_directives[0]).end_lineno
    else:
        raise ValueError(f"{path}: at least one version directive is required for synchronization")

    additions = [
        f'    version("{version}", tag="{tag}", commit="{commit}")\n'
        for version, tag, commit in releases
    ]
    lines[anchor:anchor] = additions
    path.write_text("".join(lines), encoding="utf-8")


def sync_package(
    package: str,
    *,
    repository: Path | None = None,
    check: bool = False,
    dry_run: bool = False,
    config: Config | None = None,
    secrets: SecretStore | None = None,
) -> SyncResult:
    paths = package_paths(repository)
    if package not in paths:
        raise ValueError(f"unknown Seanstack package: {package}")

    path = paths[package]
    recipe = parse_recipe(path)
    if not recipe.git:
        raise ValueError(f"{package}: recipe has no git URL")

    auth = None
    if recipe.seanstack_resource:
        if config is None:
            raise ValueError(f"{package}: recipe requires resource {recipe.seanstack_resource!r} but no Seanstack config was supplied")
        resource = config.resource(recipe.seanstack_resource)
        if resource.kind != "git":
            raise ValueError(f"{package}: resource {resource.name!r} is {resource.kind!r}, expected 'git'")
        if not recipe.git.startswith(resource.url):
            raise ValueError(f"{package}: Git URL {recipe.git!r} does not belong to resource {resource.name!r} ({resource.url!r})")
        if resource.credentials:
            if secrets is None:
                raise ValueError(f"{package}: resource {resource.name!r} requires credentials")
            from .auth import git_auth
            auth = git_auth(resource, secrets)
    refs = read_remote_refs(recipe.git, auth=auth) if auth is not None else read_remote_refs(recipe.git)
    convention = infer_tag_convention(recipe)
    existing = _release_versions(recipe)

    releases: list[tuple[str, str, str]] = []
    for tag, commit in refs.tags.items():
        version = convention.version_from_tag(tag)
        if version is not None and version not in existing:
            releases.append((version, tag, commit))
    releases.sort(key=lambda item: _version_key(item[0]), reverse=True)

    tracked_branches = _tracked_branches(recipe)
    missing_branches = tuple(sorted(branch for branch in tracked_branches if branch not in refs.heads))

    if releases and not (check or dry_run):
        _insert_releases(path, recipe, releases)

    return SyncResult(
        package=package,
        changed=bool(releases or missing_branches),
        missing_versions=tuple(version for version, _, _ in releases),
        missing_branches=missing_branches,
    )


def sync_many(
    packages: Iterable[str],
    *,
    repository: Path | None = None,
    check: bool = False,
    dry_run: bool = False,
    config: Config | None = None,
    secrets: SecretStore | None = None,
) -> list[SyncResult]:
    return [
        sync_package(
            package,
            repository=repository,
            check=check,
            dry_run=dry_run,
            config=config,
            secrets=secrets,
        )
        for package in packages
    ]
