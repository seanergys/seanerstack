# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import os
import subprocess

from .auth import spack_resource_environment
from .config import Config, Resource
from .secrets import SecretStore


def buildcaches(config: Config) -> tuple[Resource, ...]:
    return tuple(resource for resource in config.resources.values() if resource.kind == "spack-buildcache")


def _mirror_args(resource: Resource, command: list[str]) -> list[str]:
    args = [*command, "mirror", "add", "--type", "binary"]
    if resource.autopush:
        args.append("--autopush")
    args.append("--signed" if resource.signed else "--unsigned")
    if resource.endpoint_url:
        args.extend(["--s3-endpoint-url", resource.endpoint_url])
    if resource.credentials:
        args.extend([
            "--s3-access-key-id-variable", f"{resource.env_prefix}_ACCESS_KEY_ID",
            "--s3-access-key-secret-variable", f"{resource.env_prefix}_SECRET_ACCESS_KEY",
        ])
        # The session-token variable is configured only when a token is present at runtime.
    args.extend([resource.name, resource.url])
    return args


def configure_buildcaches(config: Config, *, command: list[str] | None = None, env=None) -> None:
    command = command or ["spack"]
    for resource in buildcaches(config):
        subprocess.run(
            [*command, "mirror", "remove", resource.name],
            check=False,
            text=True,
            capture_output=True, env=env,
        )
        subprocess.run(_mirror_args(resource, command), check=True, text=True, capture_output=True, env=env)


def check_buildcaches(config: Config, secrets: SecretStore, *, command: list[str] | None = None, base_env=None) -> list[tuple[str, bool, str]]:
    command = command or ["spack"]
    results: list[tuple[str, bool, str]] = []
    for resource in buildcaches(config):
        env = dict(os.environ if base_env is None else base_env)
        env.update(spack_resource_environment(resource, secrets))
        process = subprocess.run(
            [*command, "buildcache", "list", "--allarch"],
            check=False,
            text=True,
            capture_output=True,
            env=env,
        )
        message = process.stderr.strip() or process.stdout.strip()
        results.append((resource.name, process.returncode == 0, message))
    return results
