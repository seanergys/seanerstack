# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import os
import subprocess

from .auth import spack_resource_environment
from .config import Config, Resource
from .secrets import SecretStore


# What Spack warns when the index of a build cache is newer than it can read.
UNREADABLE_INDEX = "you need a newer Spack version to read the buildcache index"


def buildcaches(config: Config) -> tuple[Resource, ...]:
    return tuple(resource for resource in config.resources.values() if resource.kind == "spack-buildcache")


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


def configure_buildcaches(config: Config, *, command: list[str] | None = None, env=None) -> None:
    command = command or ["spack"]
    for resource in buildcaches(config):
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
                "rebuild it with `spack buildcache update-index` from the pinned Spack"
            )
        results.append((resource.name, process.returncode == 0 and not unreadable, message))
    return results
