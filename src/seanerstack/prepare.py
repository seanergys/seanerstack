# SPDX-License-Identifier: Apache-2.0
"""Build the SEANERGYS toolchain and push it to a build cache.

Binaries match by hash, and the hash contains the operating system. The
toolchain is therefore built once per platform of `[toolchain]`, in that
platform's image, not on the host. Inside that image Seanerstack calls itself
with `--no-container`.
"""
from __future__ import annotations

import base64
from dataclasses import replace
from importlib import metadata
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request

import yaml

from .auth import spack_resource_environment
from .bootstrap import bootstrap
from .buildcache import buildcaches, configure_buildcaches
from .config import Config, Platform, Resource, Toolchain
from .isolation import DEFAULT_STATE_DIR, SPACK_GIT, SPACK_VERSION
from .paths import source_checkout
from .secrets import SecretStore


GIB = 1024**3

# Rust with four jobs ran a desktop with 4 GiB free out of memory, and the kernel
# then also killed what else was running there. Two jobs finished.
MEMORY_PER_JOB = 2 * GIB

# Keeps the desktop usable, and makes running out of memory end the build rather
# than the services next to it.
MEMORY_SHARE = 0.85

# Survives between runs, so that an interrupted build only repeats its last
# package. The default state directory, so that the binaries match those of every
# machine set up with `seanerstack init`.
CONTAINER_STATE = str(DEFAULT_STATE_DIR)
# Copied in, not mounted: the daemon of Docker in Docker sees none of the files of
# the CI job that talks to it.
CONTAINER_INPUT = "/opt/seanerstack-input"
CONTAINER_CONFIG = f"{CONTAINER_INPUT}/config.toml"
CONTAINER_SOURCE = f"{CONTAINER_INPUT}/source"
# What pip needs to install Seanerstack from a checkout.
SOURCE_FILES = ("pyproject.toml", "README.md", "LICENSE", "src", "data")
PIP_VARIABLES = ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL")


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


def prepare_here(
    config: Config, secrets: SecretStore, *, platform: str, command: list[str], env, work: Path, jobs: int | None = None
) -> int:
    """Build the toolchain in this operating system, which has to be `platform`, and push it."""
    toolchain, target = _toolchain(config)
    wanted = toolchain.platform(platform)
    caches, credentials = _session(config, secrets, env)
    if target.name not in caches:
        raise ValueError(f"no credentials for build cache {target.name!r}; provide --secrets-file FILE")
    env = {**env, **credentials}
    check_push_access(target, env)
    system = _output([*command, "arch", "--operating-system"], env).strip()
    if system != wanted.operating_system:
        raise RuntimeError(
            f"this is {system}, and binaries for {wanted.operating_system} cannot be built here; "
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
    _stream([*command, "buildcache", "push", "--only", "package", target.name, *specs], env)
    # Concretization finds binaries through the index alone. Autopush has
    # already pushed what was built, and `push --update-index` updates an OCI
    # index only when it pushed something itself, so the new binaries would
    # stay invisible. This also replaces an index that a newer Spack wrote
    # and this one cannot read.
    _stream([*command, "buildcache", "update-index", target.name], env)
    print(f"the toolchain for {wanted.name} is in {target.url}")
    return 0


def install_command(platform: Platform) -> str:
    """The shell command that installs the system packages of `platform`."""
    packages = shlex.join(platform.system_packages)
    if platform.package_manager == "dnf":
        return f"dnf install -y --setopt=install_weak_deps=False {packages}"
    if platform.package_manager == "apt":
        return f"apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends {packages}"
    if platform.package_manager == "pacman":
        return f"pacman -Syu --noconfirm --needed {packages}"
    raise ValueError(f"unknown package manager {platform.package_manager!r}")


def container_script(platform: Platform, *, jobs: int, source: bool, uid: int, gid: int, version: str) -> str:
    spack = f"{CONTAINER_STATE}/spack-{SPACK_VERSION}"
    package = CONTAINER_SOURCE if source else f"seanerstack=={version}"
    seanerstack = (
        f"/opt/seanerstack/bin/seanerstack --config-file {CONTAINER_CONFIG} --state-dir {CONTAINER_STATE} "
        f"--spack-executable {spack}/bin/spack buildcache prepare --no-container "
        f"--platform {shlex.quote(platform.name)} --jobs {jobs}"
    )
    return "\n".join(
        [
            "set -euo pipefail",
            "# The container runs as root. Return what it wrote to the calling user.",
            f"trap 'chown -R {uid}:{gid} {CONTAINER_STATE} || true' EXIT",
            install_command(platform),
            # Spack names the operating system after /etc/os-release. An installed
            # system links it to /usr/lib/os-release, but the archlinux image writes
            # its own with the date of the image as version, which no machine has.
            "if [ -e /usr/lib/os-release ]; then ln -sf ../usr/lib/os-release /etc/os-release; fi",
            f"if [ ! -x {spack}/bin/spack ]; then",
            f"  rm -rf {spack}.partial",
            f"  git clone --depth 1 --branch {SPACK_VERSION} {SPACK_GIT} {spack}.partial",
            f"  mv {spack}.partial {spack}",
            "fi",
            f"{platform.python} -m venv /opt/seanerstack",
            f"/opt/seanerstack/bin/pip install --quiet {shlex.quote(package)}",
            seanerstack,
            "",
        ]
    )


def _container_runtime() -> str:
    for name in ("docker", "podman"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("neither docker nor podman found; in the toolchain image, run with --no-container")


def _stage_input(config: Config, checkout: Path | None, stage: Path) -> None:
    """Gather what the container reads into `stage`, laid out as CONTAINER_INPUT."""
    shutil.copyfile(config.path, stage / "config.toml")
    if checkout is None:
        return
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in SOURCE_FILES:
        source = checkout / name
        if source.is_dir():
            shutil.copytree(source, stage / "source" / name, ignore=ignore)
        else:
            (stage / "source").mkdir(exist_ok=True)
            shutil.copyfile(source, stage / "source" / name)


def prepare_in_container(
    config: Config, secrets: SecretStore, *, platform: str, state_dir: Path, jobs: int | None = None
) -> int:
    """Build the toolchain in the image of `platform`, so that any desktop can do it."""
    toolchain, target = _toolchain(config)
    wanted = toolchain.platform(platform)
    caches, credentials = _session(config, secrets, os.environ)
    if target.name not in caches:
        raise ValueError(f"no credentials for build cache {target.name!r}; provide --secrets-file FILE")
    env = {**os.environ, **credentials}
    check_push_access(target, env)

    runtime = _container_runtime()
    state = state_dir.expanduser().resolve() / "buildcache-prepare" / wanted.name
    state.mkdir(parents=True, exist_ok=True)
    checkout = source_checkout()
    name = f"seanerstack-prepare-{os.getpid()}"
    # The state is mounted, so that the next run continues where this one stopped.
    # Under Docker in Docker it lives with the daemon, and goes when the job ends.
    argv = [runtime, "create", "--name", name, "-v", f"{state}:{CONTAINER_STATE}"]
    memory = _available_memory()
    if memory is not None:
        limit = str(int(memory * MEMORY_SHARE))
        argv += ["--memory", limit, "--memory-swap", limit]
    # -e NAME takes the value from this process, so no token is on a command line.
    # The credentials of a cache come from the vault or, as in CI, from the
    # environment, and the build inside needs them either way.
    variables = dict.fromkeys(credentials)
    for cache in caches.values():
        if cache.credentials:
            variables.update(dict.fromkeys(name for name in cache.credential_variables if name in env))
    variables.update(dict.fromkeys(name for name in PIP_VARIABLES if name in env))
    for variable in variables:
        argv += ["-e", variable]
    script = container_script(
        wanted, jobs=jobs or default_jobs(), source=checkout is not None,
        uid=os.getuid(), gid=os.getgid(), version=metadata.version("seanerstack"),
    )
    try:
        _stream([*argv, wanted.image, "/bin/bash", "-c", script], env)
        with tempfile.TemporaryDirectory(prefix="seanerstack-prepare-") as stage:
            _stage_input(config, checkout, Path(stage))
            _stream([runtime, "cp", f"{stage}/.", f"{name}:{CONTAINER_INPUT}"], env)
        _stream([runtime, "start", "--attach", name], env)
    finally:
        # The container outlives its client, and is kept after it stops.
        subprocess.run([runtime, "rm", "--force", name], check=False, capture_output=True, env=env)
    return 0
