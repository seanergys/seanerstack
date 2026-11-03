# SPDX-License-Identifier: Apache-2.0
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import threading

import pytest
import yaml

from seanerstack import prepare as _prepare
from seanerstack.config import Config, Resource, Toolchain, load_config
from seanerstack.secrets import SecretStore


TOOLCHAIN = Toolchain(
    compiler="gcc@15",
    packages=("rust", "capnproto"),
    cache="target",
    image="rocky:10",
    operating_system="rocky10",
    target="x86_64_v3",
    system_packages=("git", "gcc"),
)
USER, TOKEN = "SEANERSTACK_RESOURCE_TARGET_USERNAME", "SEANERSTACK_RESOURCE_TARGET_PASSWORD"


def config(tmp_path: Path, **resources) -> Config:
    target = Resource(name="target", kind="spack-buildcache", url="oci://registry.example.org/group/cache", credentials="c", signed=False)
    return Config(path=tmp_path / "config.toml", resources={"target": target, **resources}, toolchain=TOOLCHAIN)


class Spack:
    """Records the Spack commands of a build."""

    def __init__(self, monkeypatch, system="rocky10"):
        self.calls = []
        self.system = system
        monkeypatch.setattr(_prepare, "check_push_access", lambda resource, env: None)
        monkeypatch.setattr(_prepare, "configure_buildcaches", self.configure)
        monkeypatch.setattr(_prepare, "bootstrap", lambda compiler, **kwargs: type("Result", (), {"probe_ok": True}))
        monkeypatch.setattr(_prepare.subprocess, "run", self.run)

    def configure(self, config, **kwargs):
        self.caches = config.resources

    def run(self, args, **kwargs):
        self.calls.append(args)
        stdout = {"arch": f"{self.system}\n", "find": "/aaa\n/bbb\n"}.get(args[1], "")
        return type("Process", (), {"stdout": stdout, "returncode": 0})


def run_here(tmp_path, **extra):
    return _prepare.prepare_here(
        config(tmp_path), SecretStore(None), command=["spack"], env={USER: "u", TOKEN: "t"},
        work=tmp_path / "toolchain", **extra,
    )


def test_prepare_builds_the_toolchain_and_then_pushes_it(monkeypatch, tmp_path):
    spack = Spack(monkeypatch)
    assert run_here(tmp_path, jobs=3) == 0
    assert ["spack", "config", "add", "packages:all:require:target=x86_64_v3"] in spack.calls
    assert yaml.safe_load((tmp_path / "toolchain/spack.yaml").read_text())["spack"]["specs"] == ["rust", "capnproto"]
    install = ["spack", "-e", str(tmp_path / "toolchain"), "install", "--jobs", "3"]
    push = ["spack", "buildcache", "push", "--update-index", "--only", "package", "target", "/aaa", "/bbb"]
    assert spack.calls.index(install) < spack.calls.index(push)


def test_prepare_pushes_every_package_as_soon_as_it_is_built(monkeypatch, tmp_path):
    spack = Spack(monkeypatch)
    run_here(tmp_path)
    assert spack.caches["target"].autopush is True


def test_prepare_never_pushes_to_a_cache_it_only_reads(monkeypatch, tmp_path):
    spack = Spack(monkeypatch)
    source = Resource(name="source", kind="spack-buildcache", url="file:///cache", autopush=True, signed=False)
    _prepare.prepare_here(
        config(tmp_path, source=source), SecretStore(None), command=["spack"], env={USER: "u", TOKEN: "t"},
        work=tmp_path / "toolchain",
    )
    assert spack.caches["source"].autopush is False


def test_prepare_refuses_another_operating_system(monkeypatch, tmp_path):
    spack = Spack(monkeypatch, system="ubuntu26.04")
    with pytest.raises(RuntimeError, match="this is ubuntu26.04"):
        run_here(tmp_path)
    assert not any("install" in call for call in spack.calls)


def test_prepare_needs_credentials_for_its_target(monkeypatch, tmp_path):
    Spack(monkeypatch)
    with pytest.raises(ValueError, match="no credentials for build cache 'target'"):
        _prepare.prepare_here(config(tmp_path), SecretStore(None), command=["spack"], env={}, work=tmp_path / "w")


def test_jobs_follow_the_free_memory(monkeypatch):
    monkeypatch.setattr(_prepare.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(_prepare, "_available_memory", lambda: 4 * _prepare.GIB)
    assert _prepare.default_jobs() == 2
    monkeypatch.setattr(_prepare, "_available_memory", lambda: _prepare.GIB)
    assert _prepare.default_jobs() == 1
    monkeypatch.setattr(_prepare, "_available_memory", lambda: None)
    assert _prepare.default_jobs() == 16


def test_the_container_reaches_prepare_through_a_checkout_or_a_release():
    arguments = dict(jobs=2, uid=1000, gid=1000, version="1.2.3")
    source = _prepare.container_script(TOOLCHAIN, source=True, **arguments)
    assert "pip install --quiet /src/seanerstack" in source
    assert "buildcache prepare --no-container --jobs 2" in source
    assert "dnf install -y --setopt=install_weak_deps=False git gcc" in source
    release = _prepare.container_script(TOOLCHAIN, source=False, **arguments)
    assert "pip install --quiet seanerstack==1.2.3" in release


def test_the_container_state_is_where_the_binaries_of_the_caches_relocate_to():
    assert _prepare.CONTAINER_STATE == "/opt/seanergys/state"


def test_no_token_is_on_the_command_line_of_the_container(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(_prepare, "check_push_access", lambda resource, env: None)
    monkeypatch.setattr(_prepare, "_container_runtime", lambda: "docker")
    monkeypatch.setattr(_prepare, "_available_memory", lambda: 8 * _prepare.GIB)
    monkeypatch.setattr(_prepare, "_stream", lambda args, env: calls.append((args, env)))
    monkeypatch.setattr(_prepare, "_session", lambda *a: ({"target": config(tmp_path).resources["target"]}, {TOKEN: "secret"}))
    _prepare.prepare_in_container(config(tmp_path), SecretStore(None), state_dir=tmp_path, jobs=2)
    argv, env = calls[0]
    assert "secret" not in " ".join(argv)
    assert env[TOKEN] == "secret"
    assert argv[argv.index("-e") + 1] == TOKEN
    assert argv[argv.index("--memory") + 1] == argv[argv.index("--memory-swap") + 1] == str(int(8 * _prepare.GIB * 0.85))
    assert (tmp_path / "buildcache-prepare/rocky10").is_dir()


def test_prepare_needs_a_container_runtime(monkeypatch):
    monkeypatch.setattr(_prepare.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="neither docker nor podman"):
        _prepare._container_runtime()


def test_the_shipped_toolchain_applies_to_a_config_without_one(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[toolchain]\ncache = "elsewhere"\n', encoding="utf-8")
    toolchain = load_config(path).toolchain
    assert toolchain.cache == "elsewhere"
    assert toolchain.compiler == "gcc@15"
    assert "rust" in toolchain.packages and "capnproto" in toolchain.packages


def test_the_toolchain_cache_has_to_be_a_build_cache(tmp_path):
    git = Resource(name="target", kind="git", url="https://example.org/")
    with pytest.raises(ValueError, match="not a spack-buildcache"):
        _prepare._toolchain(replace(config(tmp_path), resources={"target": git}))


class Registry(BaseHTTPRequestHandler):
    """A registry with token authentication, in which only one token may write."""

    uploads, deleted = [], []
    writable = True

    def log_message(self, *args):
        pass

    def answer(self, code, headers=None, body=b""):
        self.send_response(code)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.answer(200, body=json.dumps({"token": "t"}).encode())

    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer t":
            realm = f"http://127.0.0.1:{self.server.server_port}/token"
            challenge = f'Bearer realm="{realm}",service="registry",scope="repository:group/cache:pull,push"'
            self.answer(401, {"WWW-Authenticate": challenge})
        elif self.writable:
            self.uploads.append(self.path)
            self.answer(202, {"Location": "/v2/group/cache/blobs/uploads/one"})
        else:
            self.answer(403)

    def do_DELETE(self):
        self.deleted.append(self.path)
        self.answer(204)


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(Registry, "uploads", [])
    monkeypatch.setattr(Registry, "deleted", [])
    server = HTTPServer(("127.0.0.1", 0), Registry)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield Resource(name="target", kind="spack-buildcache", url=f"oci+http://127.0.0.1:{server.server_port}/group/cache", credentials="c", signed=False)
    server.shutdown()


def test_push_access_starts_an_upload_and_abandons_it(registry):
    _prepare.check_push_access(registry, {USER: "u", TOKEN: "t"})
    assert Registry.uploads == ["/v2/group/cache/blobs/uploads/"]
    assert Registry.deleted == ["/v2/group/cache/blobs/uploads/one"]


def test_a_token_that_may_only_read_fails_before_the_build(registry, monkeypatch):
    monkeypatch.setattr(Registry, "writable", False)
    with pytest.raises(RuntimeError, match="write_registry"):
        _prepare.check_push_access(registry, {USER: "u", TOKEN: "t"})
