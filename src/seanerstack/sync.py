# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .auth import GitAuth, git_environment, http_auth_headers
from .config import Config
from .secrets import SecretStore
from typing import Collection, Iterable

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
        # grammar, but existing Seanerstack release recipes use PEP 440-compatible
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


def _has_releases(recipe: Recipe) -> bool:
    """Whether the recipe has a release, fetched by tag or as an archive."""
    return any(
        directive.name == "version" and directive.args and ({"tag", "sha256"} & directive.kwargs.keys())
        for directive in recipe.directives
    )


def _tracked_branches(recipe: Recipe) -> dict[str, str]:
    return {
        str(directive.kwargs["branch"]): str(directive.args[0])
        for directive in recipe.directives
        if directive.name == "version"
        and directive.args
        and isinstance(directive.kwargs.get("branch"), str)
    }


def _release_kind(recipe: Recipe) -> str:
    """Return "tag" for Git-fetched releases or "sha256" for archive releases."""
    tagged: list[str] = []
    archived: list[str] = []
    for directive in recipe.directives:
        if directive.name != "version" or not directive.args:
            continue
        if "tag" in directive.kwargs:
            tagged.append(str(directive.args[0]))
        elif "sha256" in directive.kwargs and not {"branch", "commit"} & directive.kwargs.keys():
            archived.append(str(directive.args[0]))
    if tagged and archived:
        raise ValueError(
            f"{recipe.path}: recipe mixes tag= releases ({', '.join(tagged)}) "
            f"and sha256= releases ({', '.join(archived)}); use one release kind"
        )
    return "sha256" if archived else "tag"


def _version_pattern(version: str) -> re.Pattern[str]:
    # Match a whole version: "0.2" must not match inside "0.2.1" or "10.2".
    return re.compile(rf"(?<![0-9.]){re.escape(version)}(?!\.?[0-9])")


def _url_version(recipe: Recipe) -> str:
    """Return the release version the recipe's url points to."""
    assert recipe.url is not None
    candidates = [
        str(directive.args[0])
        for directive in recipe.directives
        if directive.name == "version"
        and directive.args
        and "sha256" in directive.kwargs
        and _version_pattern(str(directive.args[0])).search(recipe.url)
    ]
    if len(candidates) != 1:
        found = ", ".join(candidates) if candidates else "none"
        raise ValueError(
            f"{recipe.path}: url must contain exactly one sha256 release version "
            f"(found: {found}): {recipe.url}"
        )
    return candidates[0]


def archive_url(recipe: Recipe, version: str) -> str:
    """Substitute version into the recipe url, like Spack's url_for_version."""
    assert recipe.url is not None
    return _version_pattern(_url_version(recipe)).sub(lambda _: version, recipe.url)


def _url_tag_convention(recipe: Recipe, tags: Collection[str] | None) -> TagConvention:
    if not recipe.url:
        raise ValueError(f"{recipe.path}: sha256 releases require a url to infer the release-tag convention")
    version = _url_version(recipe)
    pattern = _version_pattern(version)
    conventions: set[tuple[str, str]] = set()
    for segment in urlsplit(recipe.url).path.split("/"):
        matches = list(pattern.finditer(segment))
        if len(matches) == 1:
            conventions.add((segment[:matches[0].start()], segment[matches[0].end():]))
    if tags is not None:
        conventions = {(prefix, suffix) for prefix, suffix in conventions if f"{prefix}{version}{suffix}" in tags}
    if len(conventions) != 1:
        rendered = ", ".join(f"{prefix}{{version}}{suffix}" for prefix, suffix in sorted(conventions)) or "none"
        raise ValueError(
            f"{recipe.path}: cannot infer one release-tag convention for {version} "
            f"from url {recipe.url} (candidates: {rendered})"
        )
    prefix, suffix = next(iter(conventions))
    return TagConvention(prefix=prefix, suffix=suffix)


def infer_tag_convention(recipe: Recipe, tags: Collection[str] | None = None) -> TagConvention:
    """Infer how release tags are named from the recipe's existing releases.

    Tag releases carry the tag name directly. For sha256 releases the tag is
    taken from the url path segment holding the version; upstream tags, when
    given, pick among several such segments.
    """
    if _release_kind(recipe) == "sha256":
        return _url_tag_convention(recipe, tags)
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
            "add at least one version(..., tag=...) or version(..., sha256=...) directive"
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


def _urlopen(request: urllib.request.Request):
    return urllib.request.urlopen(request, timeout=120)


def archive_sha256(url: str, *, auth: GitAuth | None = None) -> str:
    """Download a .tar.gz archive and return its sha256 without keeping it."""
    request = urllib.request.Request(url)
    for name, value in http_auth_headers(auth).items():
        # Unredirected headers are not sent again if the server redirects.
        request.add_unredirected_header(name, value)
    digest = hashlib.sha256()
    try:
        with _urlopen(request) as response:
            content_type = response.headers.get_content_type()
            head = response.read(2)
            digest.update(head)
            while chunk := response.read(1 << 16):
                digest.update(chunk)
    except urllib.error.HTTPError as error:
        raise ValueError(f"{url}: download failed: HTTP {error.code} {error.reason}") from None
    except urllib.error.URLError as error:
        raise ValueError(f"{url}: download failed: {error.reason}") from None

    # A private archive fetched without valid credentials is GitLab's sign-in
    # page, served with HTTP 200.
    if content_type == "text/html" or head != b"\x1f\x8b":  # gzip magic bytes
        raise ValueError(
            f"{url}: download is not a gzip archive (Content-Type {content_type}); "
            "check that the recipe's seanerstack_resource credentials grant access"
        )
    return digest.hexdigest()


def _insert_releases(path: Path, recipe: Recipe, directives: list[str]) -> None:
    if not directives:
        return

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    version_directives = [directive for directive in recipe.directives if directive.name == "version"]
    if version_directives:
        branch_directives = [directive for directive in version_directives if directive.kwargs.get("branch")]
        anchor = (branch_directives[-1] if branch_directives else version_directives[0]).end_lineno
    else:
        raise ValueError(f"{path}: at least one version directive is required for synchronization")

    additions = [f"    {directive}\n" for directive in directives]
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
        raise ValueError(f"unknown Seanerstack package: {package}")

    path = paths[package]
    recipe = parse_recipe(path)
    if not recipe.git:
        raise ValueError(f"{package}: recipe has no git URL")

    kind = _release_kind(recipe)
    if kind == "sha256" and not recipe.url:
        raise ValueError(f"{package}: recipe has sha256 releases but no url")

    auth = None
    if recipe.seanerstack_resource:
        if config is None:
            raise ValueError(f"{package}: recipe requires resource {recipe.seanerstack_resource!r} but no Seanerstack config was supplied")
        resource = config.resource(recipe.seanerstack_resource)
        if resource.kind != "git":
            raise ValueError(f"{package}: resource {resource.name!r} is {resource.kind!r}, expected 'git'")
        if not recipe.git.startswith(resource.url):
            raise ValueError(f"{package}: Git URL {recipe.git!r} does not belong to resource {resource.name!r} ({resource.url!r})")
        if kind == "sha256":
            assert recipe.url is not None
            if not recipe.url.startswith(resource.url):
                raise ValueError(f"{package}: archive URL {recipe.url!r} does not belong to resource {resource.name!r} ({resource.url!r})")
            if resource.credentials and not recipe.url.startswith("https://"):
                raise ValueError(f"{package}: refusing to send credentials of {resource.name!r} to non-HTTPS URL {recipe.url!r}")
        if resource.credentials:
            if secrets is None:
                raise ValueError(f"{package}: resource {resource.name!r} requires credentials")
            from .auth import git_auth
            auth = git_auth(resource, secrets)
    refs = read_remote_refs(recipe.git, auth=auth) if auth is not None else read_remote_refs(recipe.git)
    existing = _release_versions(recipe)

    # A recipe without releases follows its branches only, so it takes no
    # releases from the upstream tags and has no tag convention to infer.
    releases: list[tuple[str, str, str]] = []
    if _has_releases(recipe):
        convention = infer_tag_convention(recipe, tags=refs.tags)
        for tag, commit in refs.tags.items():
            version = convention.version_from_tag(tag)
            if version is not None and version not in existing:
                releases.append((version, tag, commit))
        releases.sort(key=lambda item: _version_key(item[0]), reverse=True)

    tracked_branches = _tracked_branches(recipe)
    missing_branches = tuple(sorted(branch for branch in tracked_branches if branch not in refs.heads))

    if releases and not (check or dry_run):
        if kind == "sha256":
            # Download everything before touching the recipe.
            directives = [
                f'version("{version}", sha256="{archive_sha256(archive_url(recipe, version), auth=auth)}")'
                for version, _, _ in releases
            ]
        else:
            directives = [f'version("{version}", tag="{tag}", commit="{commit}")' for version, tag, commit in releases]
        _insert_releases(path, recipe, directives)

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
