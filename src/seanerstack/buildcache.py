# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import os
import re
from pathlib import Path
import subprocess

from .auth import spack_resource_environment
from .config import Config, Resource
from .secrets import SecretStore


# Run by `spack python`, so that it uses the Spack of the session.
UPDATE_INDEX_SCRIPT = Path(__file__).with_name("_spack_update_index.py")
CACHE_ACCESS_SCRIPT = Path(__file__).with_name("_spack_cache_access.py")
PUSH_ACCESS_SCRIPT = Path(__file__).with_name("_spack_push_access.py")

# How Spack reports a build cache without an index: the registry knows no
# manifest of that name, which a refused request (401, 403) never says.
EMPTY_CACHE = re.compile(r"FetchIndexError.*returned 404", re.DOTALL)
EMPTY_CACHE_MESSAGE = (
    "empty: the cache has no index yet, so everything is built until "
    "`seanerstack buildcache prepare` or a push with an index update fills it"
)

# What Spack warns when the index of a build cache is newer than it can read.
UNREADABLE_INDEX = "you need a newer Spack version to read the buildcache index"


def buildcaches(config: Config) -> tuple[Resource, ...]:
    """The build caches of the Spack that builds the stack: all but the bootstrap cache.

    @param config: the Seanerstack configuration
    @return: each build cache that the stack reads
    """
    bootstrap = config.toolchain.bootstrap_cache if config.toolchain else None
    return tuple(
        resource for resource in config.resources.values() if resource.kind == "spack-buildcache" and resource.name != bootstrap
    )


def bootstrap_buildcache(config: Config) -> Resource | None:
    """The build cache of the bootstrap instance, which holds the first stage of the compiler.

    A config.toml takes the [toolchain] of the shipped one for what it does
    not set, and with it the name of the shipped bootstrap cache. A
    config.toml that does not define that resource has no bootstrap cache:
    the first stage is then built wherever it is needed.

    @param config: the Seanerstack configuration
    @return: the cache that `[toolchain] bootstrap_cache` names, or None when
        it names none or the configuration does not define it
    """
    name = config.toolchain.bootstrap_cache if config.toolchain else None
    if name is None or name not in config.resources:
        return None
    resource = config.resource(name)
    if resource.kind != "spack-buildcache":
        raise ValueError(f"[toolchain] bootstrap_cache: resource {name!r} is not a spack-buildcache")
    return resource


def _mirror_args(resource: Resource, command: list[str]) -> list[str]:
    args = [*command, "mirror", "add", "--scope", "user", "--type", "binary"]
    if resource.autopush:
        args.append("--autopush")
    args.append("--signed" if resource.signed else "--unsigned")
    if resource.endpoint_url:
        args.extend(["--s3-endpoint-url", resource.endpoint_url])
    if resource.credentials:
        user_variable, secret_variable = resource.credential_variables
        if resource.oci:
            args.extend(["--oci-username-variable", user_variable, "--oci-password-variable", secret_variable])
        else:
            args.extend(["--s3-access-key-id-variable", user_variable, "--s3-access-key-secret-variable", secret_variable])
            # The session-token variable is configured only when a token is present at runtime.
    args.extend([resource.name, resource.url])
    return args


def configure_buildcache(resource: Resource, *, command: list[str], env=None) -> None:
    """Make one build cache a mirror of a Spack instance, replacing an earlier one of that name.

    @param resource: the build cache
    @param command: the isolated Spack command of the instance
    @param env: its environment
    @return: nothing; a mirror that Spack refuses raises RuntimeError
    """
    # `-C` also loads the private configuration as an immutable scope, and an
    # unscoped remove picks that one and fails. Name the writable scope.
    subprocess.run(
        [*command, "mirror", "remove", "--scope", "user", resource.name],
        check=False,
        text=True,
        capture_output=True, env=env,
    )
    process = subprocess.run(_mirror_args(resource, command), check=False, text=True, capture_output=True, env=env)
    if process.returncode != 0:
        message = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError(f"could not configure build cache {resource.name!r}: {message}")


def configure_buildcaches(config: Config, *, command: list[str] | None = None, env=None) -> None:
    command = command or ["spack"]
    for resource in buildcaches(config):
        configure_buildcache(resource, command=command, env=env)


# Run by `spack python`, so that it uses the Spack of the session.
HASHDIFF_SCRIPT = os.path.join(os.path.dirname(__file__), "_spack_hashdiff.py")


def buildcache_environment(config: Config, secrets: SecretStore, env) -> dict[str, str]:
    """`env` with the credentials of every build cache that has them, for reading all of them.

    The bootstrap cache is among them: the bootstrap instance takes its
    environment from the actual one.

    A cache whose credentials are missing is read anonymously, as Spack would.
    """
    env = dict(env)
    bootstrap = bootstrap_buildcache(config)
    for resource in (*buildcaches(config), *([bootstrap] if bootstrap else [])):
        if resource.credentials and not all(name in env for name in resource.credential_variables):
            try:
                env.update(spack_resource_environment(resource, secrets))
            except ValueError:
                pass
    return env


def require_cache_access(command: list[str], env) -> None:
    """Fail when an OCI build cache of the session refuses a request made with `env`.

    Spack reports such a cache as "no binary available" and builds from source
    what the cache holds, so an install that follows would hide the refusal.

    @param command: the isolated Spack command
    @param env: the environment the install will run in, with its credentials
    @return: nothing; a refused cache raises RuntimeError that names it
    """
    result = subprocess.run([*command, "python", str(CACHE_ACCESS_SCRIPT)], check=False, text=True, capture_output=True, env=env)
    if result.returncode != 0:
        reason = result.stdout.strip() or result.stderr.strip()
        raise RuntimeError(
            f"a build cache cannot be read, so Spack would build from source what it holds:\n{reason}\n"
            "Run `seanerstack init --secrets-file FILE` again with credentials that can read it."
        )


def explain(spec: str, *, command: list[str], env, match: str = "os") -> int:
    """Explain why `spec` is not taken from the build caches.

    Concretizes `spec` in the session, and for each cached spec of the same
    name and version, prints the nodes whose own hashed fields differ, such
    as the target, a variant, the package recipe or the path of an external.
    A cache holds a package for every platform it is built on, so only the
    cached specs that `match` selects are compared.

    @param spec: the spec as `spack install` would get it, such as gcc@15.3.0
    @param command: the isolated Spack command
    @param env: its environment, with the credentials of the caches
    @param match: "os" for the cached specs of this operating system, "target" for those of this target as well, "all" for every one
    @return: 0 when a cached spec was compared, 1 when the caches hold none that `match` selects
    """
    if match not in ("os", "target", "all"):
        raise ValueError(f"unknown match {match!r}; one of os, target, all")
    selection = [] if match == "os" else [f"--match={match}"]
    return subprocess.run([*command, "python", HASHDIFF_SCRIPT, *selection, spec], check=False, text=True, env=env).returncode


def check_buildcaches(config: Config, secrets: SecretStore, *, command: list[str] | None = None, base_env=None) -> list[tuple[str, bool, str]]:
    command = command or ["spack"]
    results: list[tuple[str, bool, str]] = []
    for resource in buildcaches(config):
        env = dict(os.environ if base_env is None else base_env)
        # An activated session already carries the credentials; only then is the vault skipped.
        if not all(name in env for name in resource.credential_variables):
            try:
                env.update(spack_resource_environment(resource, secrets))
            except ValueError as error:
                # Missing credentials fail this cache, not the whole check.
                results.append((resource.name, False, str(error)))
                continue
        process = subprocess.run(
            [*command, "buildcache", "list", "--allarch"],
            check=False,
            text=True,
            capture_output=True,
            env=env,
        )
        message = process.stderr.strip() or process.stdout.strip()
        # Spack lists nothing and still succeeds when a newer Spack wrote the
        # index, so nothing in that cache can be installed.
        unreadable = UNREADABLE_INDEX in process.stdout + process.stderr
        if unreadable:
            message = (
                "a newer Spack wrote the index of this cache, and the pinned one cannot read it; "
                "rebuild it with `seanerstack buildcache update-index`, which needs write access"
            )
        # A cache that nothing was pushed to yet has no index. It answered the
        # request, so the credentials read it, and it holds nothing to install.
        if process.returncode != 0 and EMPTY_CACHE.search(process.stdout + process.stderr):
            results.append((resource.name, True, EMPTY_CACHE_MESSAGE))
            continue
        results.append((resource.name, process.returncode == 0 and not unreadable, message))
    return results


def check_push(resource: Resource, *, command: list[str], env) -> tuple[bool, str]:
    """Whether the credentials of `env` can push to a build cache.

    An OCI cache is asked to start an upload, which stores nothing. Any other
    cache gets a small file below test/ of its push URL, the way Spack pushes
    a binary there, which is removed again.

    @param resource: the build cache, configured as a mirror of the instance that `command` runs
    @param command: the isolated Spack command of that instance
    @param env: its environment, with the cache's push credentials
    @return: whether the cache took the push, and a message that says what happened
    """
    if resource.oci:
        from .prepare import check_push_access
        try:
            check_push_access(resource, env)
        except RuntimeError as error:
            return False, str(error)
        return True, f"takes a push to {resource.url}"
    process = subprocess.run(
        [*command, "python", str(PUSH_ACCESS_SCRIPT), resource.name], check=False, text=True, capture_output=True, env=env,
    )
    message = process.stdout.strip() or process.stderr.strip()
    return process.returncode == 0, message.removeprefix(f"{resource.name}: ")


def push_installed(resource: Resource, *, command: list[str], env) -> int:
    """Push everything a Spack instance has installed to a build cache, and rebuild its index.

    Also what came from another cache, so that this one is complete by itself.
    Spack leaves out externals.

    @param resource: the build cache, configured as a mirror of the instance
    @param command: the isolated Spack command of the instance
    @param env: its environment, with the cache's push credentials
    @return: how many specs were pushed; with none, nothing is sent; a failed
        push raises CalledProcessError
    """
    found = subprocess.run([*command, "find", "--format", "/{hash}"], check=False, text=True, capture_output=True, env=env)
    specs = found.stdout.split() if found.returncode == 0 else []
    if specs:
        subprocess.run([*command, "buildcache", "push", "--only", "package", resource.name, *specs], check=True, text=True, env=env)
        update_index(resource, command=command, env=env)
    return len(specs)


def update_index(resource: Resource, *, command: list[str], env) -> None:
    """Rebuild the index of a build cache from the binaries it holds.

    For an OCI cache, specs that this Spack cannot read, such as those a newer
    Spack pushed, are left out and named instead of stopping the rebuild, as
    `spack buildcache update-index` does. Other caches take Spack's own.

    @param resource: the build cache, configured as a mirror of the session
    @param command: the isolated Spack command
    @param env: its environment, with the cache's push credentials
    @return: nothing; a failed rebuild raises CalledProcessError
    """
    if resource.oci:
        args = [*command, "python", str(UPDATE_INDEX_SCRIPT), resource.name]
    else:
        args = [*command, "buildcache", "update-index", resource.name]
    subprocess.run(args, check=True, text=True, env=env)
