# SPDX-License-Identifier: Apache-2.0
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import threading

import pytest

from seanerstack.config import Resource
from seanerstack.registry import Registry, RegistryError

USER, PASSWORD = "SEANERSTACK_RESOURCE_CACHE_USERNAME", "SEANERSTACK_RESOURCE_CACHE_PASSWORD"


class FakeRegistry(BaseHTTPRequestHandler):
    """A repository group/cache that wants a token for everything, as GitLab's does."""

    blobs: dict = {}
    manifests: dict = {}
    logins: list = []
    corrupt = False

    def log_message(self, *args):
        pass

    def answer(self, code, headers=None, body=b""):
        self.send_response(code)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def authorized(self):
        if self.headers.get("Authorization") == "Bearer token":
            return True
        realm = f"http://127.0.0.1:{self.server.server_port}/token"
        self.answer(401, {"WWW-Authenticate": f'Bearer realm="{realm}",service="registry",scope="repository:group/cache:pull"'})
        return False

    def body(self):
        return self.rfile.read(int(self.headers.get("Content-Length") or 0))

    def do_GET(self):
        if self.path.startswith("/token"):
            self.logins.append(self.headers.get("Authorization"))
            return self.answer(200, body=json.dumps({"token": "token"}).encode())
        if not self.authorized():
            return
        kind, _, name = self.path.removeprefix("/v2/group/cache/").partition("/")
        store = self.blobs if kind == "blobs" else self.manifests
        if name not in store:
            return self.answer(404)
        body = store[name]
        self.answer(200, body=body + b"x" if self.corrupt and kind == "blobs" else body)

    def do_HEAD(self):
        if self.authorized():
            self.answer(200 if self.path.rpartition("/")[2] in self.blobs else 404)

    def do_POST(self):
        if self.authorized():
            self.body()
            self.answer(202, {"Location": "/v2/group/cache/blobs/uploads/one?state=abc"})

    def do_PUT(self):
        if not self.authorized():
            return
        data = self.body()
        if self.path.startswith("/v2/group/cache/blobs/uploads/one?state=abc&digest="):
            digest = self.path.rpartition("digest=")[2].replace("%3A", ":")
            assert digest == f"sha256:{hashlib.sha256(data).hexdigest()}"
            self.blobs[digest] = data
        else:
            self.manifests[self.path.rpartition("/")[2]] = data
        self.answer(201)


@pytest.fixture
def cache(monkeypatch):
    for name, value in (("blobs", {}), ("manifests", {}), ("logins", []), ("corrupt", False)):
        monkeypatch.setattr(FakeRegistry, name, value)
    server = HTTPServer(("127.0.0.1", 0), FakeRegistry)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield Resource(name="cache", kind="spack-buildcache", url=f"oci+http://127.0.0.1:{server.server_port}/group/cache", credentials="c", signed=False)
    server.shutdown()


def test_a_manifest_and_its_blob_are_written_and_read_back(cache):
    registry = Registry.of(cache, {USER: "user", PASSWORD: "secret"})

    digest = registry.put_blob(b"content")
    registry.put_manifest("a-tag", {"schemaVersion": 2, "layers": [{"digest": digest}]})

    again = Registry.of(cache, {})
    assert again.manifest("a-tag") == {"schemaVersion": 2, "layers": [{"digest": digest}]}
    assert again.blob(digest) == b"content"


def test_a_missing_tag_is_none(cache):
    assert Registry.of(cache, {}).manifest("no-such-tag") is None


def test_the_credentials_of_the_resource_log_in_and_none_read_anonymously(cache):
    Registry.of(cache, {USER: "user", PASSWORD: "secret"}).manifest("t")
    Registry.of(cache, {}).manifest("t")
    assert FakeRegistry.logins[0].startswith("Basic ") and FakeRegistry.logins[1] is None


def test_a_blob_the_repository_holds_is_not_uploaded_again(cache):
    registry = Registry.of(cache, {})
    digest = registry.put_blob(b"content")
    FakeRegistry.blobs[digest] = b"kept"
    assert registry.put_blob(b"content") == digest
    assert FakeRegistry.blobs[digest] == b"kept"


def test_a_blob_that_does_not_match_its_digest_is_refused(cache):
    registry = Registry.of(cache, {})
    digest = registry.put_blob(b"content")
    FakeRegistry.corrupt = True
    with pytest.raises(RegistryError, match="does not match its digest"):
        registry.blob(digest)


def test_only_an_oci_cache_is_a_registry():
    with pytest.raises(ValueError, match="not in an OCI registry"):
        Registry.of(Resource(name="s3", kind="spack-buildcache", url="s3://builds"), {})


def test_the_https_registry_of_a_resource():
    resource = Resource(name="cache", kind="spack-buildcache", url="oci://registry.example.org/software/seanerstack/buildcache", credentials="c", signed=False)
    registry = Registry.of(resource, {USER: "user", PASSWORD: "secret"})
    assert (registry.base, registry.repository, registry.username) == ("https://registry.example.org", "software/seanerstack/buildcache", "user")
    assert "secret" not in repr(registry)
