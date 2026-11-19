# SPDX-License-Identifier: Apache-2.0
"""The lockfile of the compiler, kept as a tag in the project build cache.

The compiler environment is concretized where the cache is filled, and its
`spack.lock` is stored under a tag of the build cache's repository. Every
other machine installs exactly those specs from the cache, whatever its system
compiler and its state directory. Spack takes only tags that end in `.spack`
for binaries, so it never sees this one.

The tag is derived from everything that decides the hash of the compiler: the
pinned Spack and builtin recipes, the compiler, both stages, the operating
system and the target. A Seanerstack with other pins looks for another tag, and
finds none rather than a wrong one.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .bootstrap import stage_roots
from .config import Config, Resource
from .pins import BUILTIN_REPO_COMMIT, SPACK_COMMIT
from .registry import MANIFEST_MEDIA_TYPE, Registry, RegistryError


CONFIG_MEDIA_TYPE = "application/vnd.seanerstack.compiler-lockfile.config.v1+json"
LOCKFILE_MEDIA_TYPE = "application/vnd.seanerstack.spack-lock.v1+json"


def _key(compiler: str, target: str, operating_system: str) -> dict:
    first, second = stage_roots(compiler)
    return {
        "spack": SPACK_COMMIT, "builtin": BUILTIN_REPO_COMMIT, "compiler": compiler,
        "first_stage": first, "second_stage": second, "operating_system": operating_system, "target": target,
    }


def compiler_lockfile_tag(compiler: str, target: str, operating_system: str) -> str:
    """The tag of the compiler lockfile for these, such as compiler-gcc-15-rocky10-x86_64_v3-0123456789ab.

    @param compiler: the compiler spec, such as gcc@15
    @param target: the target of the toolchain, such as x86_64_v3
    @param operating_system: the operating system as Spack names it, such as rocky10
    @return: the tag
    """
    key = _key(compiler, target, operating_system)
    digest = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:12]
    readable = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{compiler}-{operating_system}-{target}").strip("-.")
    return f"compiler-{readable}-{digest}"


def fetch_compiler_lockfile(resource: Resource, tag: str, env, directory: Path) -> Path | None:
    """The compiler lockfile under `tag` in the build cache, saved in `directory`, or None.

    @param resource: the build cache, in an OCI registry
    @param tag: the tag of the lockfile
    @param env: the environment with the credentials of the cache, or without for an anonymous read
    @param directory: where to save it
    @return: the saved lockfile, or None when the cache has no such tag or is not in a registry;
        a registry that refuses or holds something else raises RegistryError
    """
    if not resource.oci:
        return None
    registry = Registry.of(resource, env)
    manifest = registry.manifest(tag)
    if manifest is None:
        return None
    layers = [layer for layer in manifest.get("layers", []) if layer.get("mediaType") == LOCKFILE_MEDIA_TYPE]
    if len(layers) != 1:
        raise RegistryError(f"the tag {tag} of {resource.url} holds no compiler lockfile")
    data = registry.blob(layers[0]["digest"])
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{tag}.lock"
    path.write_bytes(data)
    return path


def find_compiler_lockfile(
    config: Config, env, *, compiler: str, target: str | None, operating_system: str, directory: Path,
) -> Path | None:
    """The compiler lockfile for these in the build cache of the toolchain, saved in `directory`, or None.

    @param config: the Seanerstack configuration, whose [toolchain] names the build cache
    @param env: the environment with the credentials of the cache, or without for an anonymous read
    @param compiler: the compiler spec, such as gcc@15
    @param target: the target of the toolchain, or None, which has no lockfile
    @param operating_system: the operating system as Spack names it
    @param directory: where to save it
    @return: the saved lockfile, or None when there is none
    """
    if config.toolchain is None or target is None:
        return None
    tag = compiler_lockfile_tag(compiler, target, operating_system)
    return fetch_compiler_lockfile(config.resource(config.toolchain.cache), tag, env, directory)


def publish_compiler_lockfile(
    resource: Resource, lockfile: Path, env, *, compiler: str, target: str, operating_system: str,
) -> tuple[str, bool]:
    """Store the compiler lockfile in the build cache, unless the cache has one under its tag.

    A lockfile already there is left as it is: machines may have installed from
    it, and the binaries it names are in the cache.

    @param resource: the build cache, in an OCI registry
    @param lockfile: the `spack.lock` of the compiler environment
    @param env: the environment with the push credentials of the cache
    @param compiler: the compiler spec, such as gcc@15
    @param target: the target of the toolchain
    @param operating_system: the operating system as Spack names it
    @return: the tag, and whether the lockfile was stored
    """
    tag = compiler_lockfile_tag(compiler, target, operating_system)
    registry = Registry.of(resource, env)
    if registry.manifest(tag) is not None:
        return tag, False
    data = lockfile.read_bytes()
    # What the tag was derived from, for whoever inspects the registry.
    config = json.dumps(_key(compiler, target, operating_system), sort_keys=True).encode()
    manifest = {
        "schemaVersion": 2,
        "mediaType": MANIFEST_MEDIA_TYPE,
        "config": {"mediaType": CONFIG_MEDIA_TYPE, "digest": registry.put_blob(config), "size": len(config)},
        "layers": [{
            "mediaType": LOCKFILE_MEDIA_TYPE, "digest": registry.put_blob(data), "size": len(data),
            "annotations": {"org.opencontainers.image.title": "spack.lock"},
        }],
    }
    registry.put_manifest(tag, manifest)
    return tag, True
