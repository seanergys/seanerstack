# SPDX-License-Identifier: Apache-2.0
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading

import pytest

from seanerstack import prepare as _prepare
from seanerstack.config import Resource, load_config


USER, TOKEN = "SEANERSTACK_RESOURCE_TARGET_USERNAME", "SEANERSTACK_RESOURCE_TARGET_PASSWORD"


def test_the_shipped_toolchain_applies_to_a_config_without_one(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[toolchain]\ncache = "elsewhere"\n', encoding="utf-8")
    toolchain = load_config(path).toolchain
    assert toolchain.cache == "elsewhere"
    assert toolchain.compiler == "gcc@15"
    assert "rust" in toolchain.packages and "capnproto" in toolchain.packages


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
