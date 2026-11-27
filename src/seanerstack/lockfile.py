# SPDX-License-Identifier: Apache-2.0
"""The lockfile of the compiler, kept in the build cache of the toolchain.

The compiler environment is concretized where the cache is filled, and its
`spack.lock` is stored in the build cache: in a registry under a tag of the
cache's repository, elsewhere as a file below the cache, which the Spack of
the state reads and writes. Every other machine installs exactly those specs
from the cache, whatever its system compiler and its state directory. Spack
takes only tags that end in `.spack` for binaries, and no file outside its own
layout, so it never sees the lockfile.

The tag is derived from everything that decides the hash of the compiler: the
pinned Spack and builtin recipes, the compiler, both stages, the operating
system and the target. A Seanerstack with other pins looks for another tag, and
finds none rather than a wrong one.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile

from .bootstrap import stage_roots
from .config import Config, Resource
from .pins import BUILTIN_REPO_COMMIT, SPACK_COMMIT
from .registry import MANIFEST_MEDIA_TYPE, Registry, RegistryError


# An ordinary image of one layer, as Spack stores its binaries: a registry
# that checks media types, such as GitLab's, refuses types of our own.
CONFIG_MEDIA_TYPE = "application/vnd.oci.image.config.v1+json"
LAYER_MEDIA_TYPE = "application/vnd.oci.image.layer.v1.tar+gzip"
LOCKFILE_NAME = "spack.lock"
# Run by `spack python`, so that it reads and writes with the Spack of the session.
LOCKFILE_SCRIPT = Path(__file__).with_name("_spack_lockfile.py")
# Where a cache outside a registry keeps the lockfile of a tag, below its URL.
LOCKFILE_DIRECTORY = "compiler-lockfiles"
# The exit status of LOCKFILE_SCRIPT when the cache has no file to read, or one already.
_ABSENT = 2


def _layer(data: bytes) -> tuple[bytes, bytes]:
    """A layer that holds `data` as spack.lock, the same bytes for the same lockfile.

    @param data: the lockfile
    @return: the uncompressed tar, whose digest is the layer's diff_id, and the gzip of it
    """
    tar = io.BytesIO()
    with tarfile.open(fileobj=tar, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        member = tarfile.TarInfo(LOCKFILE_NAME)
        member.size, member.mode = len(data), 0o644
        archive.addfile(member, io.BytesIO(data))
    compressed = io.BytesIO()
    with gzip.GzipFile(fileobj=compressed, mode="wb", mtime=0) as stream:
        stream.write(tar.getvalue())
    return tar.getvalue(), compressed.getvalue()


def _lockfile_of(layer: bytes) -> bytes | None:
    """The spack.lock in a layer, or None when it holds none.

    @param layer: the gzip of a tar
    @return: the lockfile
    """
    with tarfile.open(fileobj=io.BytesIO(layer), mode="r:gz") as archive:
        member = next((member for member in archive.getmembers() if member.name == LOCKFILE_NAME and member.isfile()), None)
        stream = archive.extractfile(member) if member is not None else None
        return stream.read() if stream is not None else None


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


def lockfile_path(tag: str) -> str:
    """The path of the lockfile of `tag` below a build cache outside a registry.

    @param tag: the tag of the lockfile
    @return: the path, relative to the URL of the cache
    """
    return f"{LOCKFILE_DIRECTORY}/{tag}.lock"


def _lockfile_script(resource: Resource, action: str, tag: str, file: Path, command: list[str], env) -> bool:
    """Read or store the lockfile of `tag` in a build cache outside a registry, with Spack.

    @param resource: the build cache, a mirror of the instance that `command` runs
    @param action: "get" to save the lockfile as `file`, "put" to store `file`
    @param tag: the tag of the lockfile
    @param file: where to save it, or what to store
    @param command: the isolated Spack command of that instance
    @param env: its environment, with the credentials of the cache
    @return: whether the lockfile was read or stored; False when the cache has
        none to read, or one already; a cache that cannot be read or written raises RuntimeError
    """
    process = subprocess.run(
        [*command, "python", str(LOCKFILE_SCRIPT), action, resource.name, lockfile_path(tag), str(file)],
        check=False, text=True, capture_output=True, env=env,
    )
    if process.returncode == _ABSENT:
        return False
    if process.returncode != 0:
        said = (process.stdout + process.stderr).strip()
        raise RuntimeError(said or f"Spack could not {'read' if action == 'get' else 'write'} {resource.url}")
    return True


def fetch_compiler_lockfile(
    resource: Resource, tag: str, env, directory: Path, *, command: list[str] | None = None,
) -> Path | None:
    """The compiler lockfile under `tag` in the build cache, saved in `directory`, or None.

    @param resource: the build cache
    @param tag: the tag of the lockfile
    @param env: the environment with the credentials of the cache, or without for an anonymous read
    @param directory: where to save it
    @param command: the isolated Spack command of the state, which reads a cache
        outside a registry; without it, such a cache gives no lockfile
    @return: the saved lockfile, or None when the cache has none;
        a registry that refuses or holds something else raises RegistryError,
        another cache that cannot be read raises RuntimeError
    """
    if not resource.oci:
        if command is None:
            return None
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{tag}.lock"
        return path if _lockfile_script(resource, "get", tag, path, command, env) else None
    registry = Registry.of(resource, env)
    manifest = registry.manifest(tag)
    if manifest is None:
        return None
    layers = [layer for layer in manifest.get("layers", []) if layer.get("mediaType") == LAYER_MEDIA_TYPE]
    data = _lockfile_of(registry.blob(layers[0]["digest"])) if len(layers) == 1 else None
    if data is None:
        raise RegistryError(f"the tag {tag} of {resource.url} holds no compiler lockfile")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{tag}.lock"
    path.write_bytes(data)
    return path


def find_compiler_lockfile(
    config: Config, env, *, compiler: str, target: str | None, operating_system: str, directory: Path,
    command: list[str] | None = None,
) -> Path | None:
    """The compiler lockfile for these in the build caches, saved in `directory`, or None.

    The build cache of the toolchain is asked first, then the other build
    caches of the configuration, in their order. A state that fills one cache
    from another, such as a public cache from the project cache, thereby
    installs the compiler that the other holds, until its own cache has a
    lockfile.

    @param config: the Seanerstack configuration, whose [toolchain] names the build cache
    @param env: the environment with the credentials of the caches, or without for an anonymous read
    @param compiler: the compiler spec, such as gcc@15
    @param target: the target of the toolchain, or None, which has no lockfile
    @param operating_system: the operating system as Spack names it
    @param directory: where to save it
    @param command: the isolated Spack command of the state, which reads the
        caches outside a registry; without it, they give no lockfile
    @return: the saved lockfile of the first cache that has one, or None when
        none has, also when the configuration defines no build cache
    """
    from .buildcache import buildcaches
    if config.toolchain is None or target is None:
        return None
    tag = compiler_lockfile_tag(compiler, target, operating_system)
    names = [cache.name for cache in buildcaches(config)]
    if config.toolchain.cache in names:
        names.remove(config.toolchain.cache)
        names.insert(0, config.toolchain.cache)
    for name in names:
        found = fetch_compiler_lockfile(config.resource(name), tag, env, directory, command=command)
        if found is not None:
            return found
    return None


def publish_compiler_lockfile(
    resource: Resource, lockfile: Path, env, *, compiler: str, target: str, operating_system: str,
    command: list[str] | None = None,
) -> tuple[str, bool]:
    """Store the compiler lockfile in the build cache, unless the cache has one under its tag.

    A lockfile already there is left as it is: machines may have installed from
    it, and the binaries it names are in the cache.

    @param resource: the build cache
    @param lockfile: the `spack.lock` of the compiler environment
    @param env: the environment with the push credentials of the cache
    @param compiler: the compiler spec, such as gcc@15
    @param target: the target of the toolchain
    @param operating_system: the operating system as Spack names it
    @param command: the isolated Spack command of the state, which writes a
        cache outside a registry; such a cache without it raises ValueError
    @return: the tag, and whether the lockfile was stored
    """
    tag = compiler_lockfile_tag(compiler, target, operating_system)
    if not resource.oci:
        if command is None:
            raise ValueError(f"{resource.name} is not in a registry: Spack writes its lockfile, so give the Spack command")
        return tag, _lockfile_script(resource, "put", tag, lockfile, command, env)
    registry = Registry.of(resource, env)
    if registry.manifest(tag) is not None:
        return tag, False
    tar, layer = _layer(lockfile.read_bytes())
    # An image config, with what the tag was derived from beside its fields,
    # for whoever inspects the registry, as Spack keeps the spec in its own.
    config = json.dumps({
        "architecture": "arm64" if target.startswith("aarch64") else "amd64", "os": "linux",
        "rootfs": {"type": "layers", "diff_ids": [f"sha256:{hashlib.sha256(tar).hexdigest()}"]},
        **_key(compiler, target, operating_system),
    }, sort_keys=True).encode()
    manifest = {
        "schemaVersion": 2,
        "mediaType": MANIFEST_MEDIA_TYPE,
        "config": {"mediaType": CONFIG_MEDIA_TYPE, "digest": registry.put_blob(config), "size": len(config)},
        "layers": [{
            "mediaType": LAYER_MEDIA_TYPE, "digest": registry.put_blob(layer), "size": len(layer),
            "annotations": {"org.opencontainers.image.title": LOCKFILE_NAME},
        }],
    }
    registry.put_manifest(tag, manifest)
    return tag, True
