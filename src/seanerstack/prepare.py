# SPDX-License-Identifier: Apache-2.0
"""Build the SEANERGYS toolchain and push it to a build cache."""
from __future__ import annotations

import base64
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request

import yaml

from .auth import spack_resource_environment
from .bootstrap import bootstrap
from .buildcache import buildcaches, configure_buildcaches
from .config import Config, Resource, Toolchain
from .secrets import SecretStore


GIB = 1024**3

# Rust with four jobs ran a desktop with 4 GiB free out of memory, and the kernel
# then also killed what else was running there. Two jobs finished.
MEMORY_PER_JOB = 2 * GIB


def _toolchain(config: Config) -> tuple[Toolchain, Resource]:
    if config.toolchain is None:
        raise ValueError(f"{config.path}: [toolchain] is missing")
    target = config.resource(config.toolchain.cache)
    if target.kind != "spack-buildcache":
        raise ValueError(f"resource {target.name!r} is not a spack-buildcache")
    return config.toolchain, target


def _session(config: Config, secrets: SecretStore, environ) -> tuple[dict[str, Resource], dict[str, str]]:
    """The build caches that can be used, and the credentials that are missing from `environ`."""
    caches: dict[str, Resource] = {}
    credentials: dict[str, str] = {}
    for resource in buildcaches(config):
        if not resource.credentials or all(name in environ for name in resource.credential_variables):
            caches[resource.name] = resource
        elif secrets.path is not None and secrets.has_credentials(resource.credentials):
            # A vault need not hold credentials for every shipped build cache.
            caches[resource.name] = resource
            credentials.update(spack_resource_environment(resource, secrets))
    return caches, credentials


def _registry(resource: Resource) -> tuple[str, str]:
    scheme, _, rest = resource.url.partition("://")
    host, _, repository = rest.partition("/")
    return f"{'http' if scheme == 'oci+http' else 'https'}://{host}", repository


def _send(url: str, method: str, headers: dict[str, str]):
    request = urllib.request.Request(url, method=method, headers=headers, data=b"" if method == "POST" else None)
    return urllib.request.urlopen(request, timeout=30)


def _bearer_token(challenge: str, username: str, password: str) -> str:
    fields = dict(re.findall(r'(\w+)="([^"]*)"', challenge))
    query = urllib.parse.urlencode({key: fields[key] for key in ("service", "scope") if key in fields})
    basic = base64.b64encode(f"{username}:{password}".encode()).decode()
    with _send(f"{fields['realm']}?{query}", "GET", {"Authorization": f"Basic {basic}"}) as response:
        answer = json.load(response)
    return answer.get("token") or answer["access_token"]


def check_push_access(resource: Resource, env) -> None:
    """Fail now, not when a build of hours tries its first push.

    Starting an upload needs write access and stores nothing. The registry only
    grants a token what its owner may do, so asking for a push token proves nothing.
    """
    if not resource.oci:
        return
    username, password = (env.get(name, "") for name in resource.credential_variables)
    base, repository = _registry(resource)
    uploads = f"{base}/v2/{repository}/blobs/uploads/"
    denied = (
        f"the credentials of {resource.name!r} cannot push to {resource.url}; "
        "a GitLab registry needs a token with write_registry"
    )
    headers: dict[str, str] = {}
    for _ in range(2):
        try:
            with _send(uploads, "POST", headers) as response:
                location = urllib.parse.urljoin(base, response.headers.get("Location", ""))
        except urllib.error.HTTPError as error:
            challenge = error.headers.get("WWW-Authenticate", "")
            if error.code != 401 or headers or not challenge.startswith("Bearer"):
                raise RuntimeError(denied) from error
            try:
                headers = {"Authorization": f"Bearer {_bearer_token(challenge, username, password)}"}
            except urllib.error.HTTPError as login:
                raise RuntimeError(denied) from login
            continue
        try:
            _send(location, "DELETE", headers).close()
        except urllib.error.URLError:
            pass  # The registry drops an abandoned upload by itself.
        return
    raise RuntimeError(denied)


def _available_memory() -> int | None:
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^MemAvailable:\s+(\d+) kB", text, re.MULTILINE)
    return int(match.group(1)) * 1024 if match else None


def default_jobs() -> int:
    cores = os.cpu_count() or 1
    memory = _available_memory()
    return cores if memory is None else max(1, min(cores, memory // MEMORY_PER_JOB))


def _stream(args: list[str], env) -> None:
    # A compiler takes hours; capturing its output would look like a hang.
    subprocess.run(args, check=True, text=True, env=env)


def _output(args: list[str], env) -> str:
    return subprocess.run(args, check=True, text=True, capture_output=True, env=env).stdout


def prepare_here(config: Config, secrets: SecretStore, *, command: list[str], env, work: Path, jobs: int | None = None) -> int:
    """Build the toolchain in this operating system and push it."""
    toolchain, target = _toolchain(config)
    caches, credentials = _session(config, secrets, env)
    if target.name not in caches:
        raise ValueError(f"no credentials for build cache {target.name!r}; provide --secrets-file FILE")
    env = {**env, **credentials}
    check_push_access(target, env)
    system = _output([*command, "arch", "--operating-system"], env).strip()
    if system != toolchain.operating_system:
        raise RuntimeError(
            f"this is {system}, and binaries for {toolchain.operating_system} cannot be built here; "
            "run without --no-container"
        )

    # Every finished package goes out at once, so a failure hours in keeps them.
    resources = {name: replace(cache, autopush=name == target.name) for name, cache in caches.items()}
    configure_buildcaches(replace(config, resources=resources), command=command, env=env)
    subprocess.run([*command, "config", "remove", "packages:all:require"], check=False, capture_output=True, env=env)
    _output([*command, "config", "add", f"packages:all:require:target={toolchain.target}"], env)
    result = bootstrap(toolchain.compiler, command=command, env=env)
    if not result.probe_ok:
        raise RuntimeError(f"Spack does not use {toolchain.compiler}")

    work.mkdir(parents=True, exist_ok=True)
    (work / "spack.yaml").write_text(
        yaml.safe_dump({"spack": {"specs": list(toolchain.packages), "view": False, "concretizer": {"unify": True}}}),
        encoding="utf-8",
    )
    _output([*command, "-e", str(work), "concretize", "--force"], env)
    _stream([*command, "-e", str(work), "install", "--jobs", str(jobs or default_jobs())], env)

    # Also what came from another cache, so that this one is complete by itself.
    specs = _output([*command, "find", "--format", "/{hash}"], env).split()
    _stream([*command, "buildcache", "push", "--update-index", "--only", "package", target.name, *specs], env)
    print(f"the toolchain is in {target.url}")
    return 0
