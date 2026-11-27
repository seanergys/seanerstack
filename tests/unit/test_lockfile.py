# SPDX-License-Identifier: Apache-2.0
import json
import re

import pytest

import seanerstack.lockfile as lockfile
from seanerstack.config import Resource
from seanerstack.registry import RegistryError
from test_registry import USER, PASSWORD, FakeRegistry, cache  # noqa: F401  (the fixture)

LOCK = {"roots": [{"hash": "abc", "spec": "gcc@15 %c,cxx=gcc@15"}], "concrete_specs": {"abc": {"name": "gcc"}}}
WHERE = dict(compiler="gcc@15", target="x86_64_v3", operating_system="rocky10")


def _publish(cache, tmp_path, content=LOCK):
    path = tmp_path / "spack.lock"
    path.write_text(json.dumps(content))
    return lockfile.publish_compiler_lockfile(cache, path, {USER: "user", PASSWORD: "secret"}, **WHERE)


def test_the_tag_names_the_platform_and_changes_with_what_decides_the_hash(monkeypatch):
    tag = lockfile.compiler_lockfile_tag(**WHERE)
    assert re.fullmatch(r"compiler-gcc-15-rocky10-x86_64_v3-[0-9a-f]{12}", tag)
    # Spack takes tags that end in .spack for binaries; this one it never sees.
    assert not tag.endswith(".spack")
    others = {
        lockfile.compiler_lockfile_tag("gcc@16", "x86_64_v3", "rocky10"),
        lockfile.compiler_lockfile_tag("gcc@15", "zen3", "rocky10"),
        lockfile.compiler_lockfile_tag("gcc@15", "x86_64_v3", "fedora45"),
    }
    monkeypatch.setattr(lockfile, "SPACK_COMMIT", "another")
    others.add(lockfile.compiler_lockfile_tag(**WHERE))
    assert tag not in others and len(others) == 4


def test_a_published_lockfile_is_fetched_with_its_content(cache, tmp_path):
    tag, stored = _publish(cache, tmp_path)

    fetched = lockfile.fetch_compiler_lockfile(cache, tag, {}, tmp_path / "fetched")

    assert stored and fetched == tmp_path / "fetched" / f"{tag}.lock"
    assert json.loads(fetched.read_text()) == LOCK
    # The config of the tag says what it was derived from.
    manifest = json.loads(FakeRegistry.manifests[tag])
    config = json.loads(FakeRegistry.blobs[manifest["config"]["digest"]])
    assert (config["compiler"], config["operating_system"], config["target"]) == ("gcc@15", "rocky10", "x86_64_v3")


def test_a_lockfile_that_the_cache_has_is_left_as_it_is(cache, tmp_path):
    tag, _ = _publish(cache, tmp_path)
    again, stored = _publish(cache, tmp_path, {"roots": []})
    assert (again, stored) == (tag, False)
    fetched = lockfile.fetch_compiler_lockfile(cache, tag, {}, tmp_path / "fetched")
    assert json.loads(fetched.read_text()) == LOCK


def test_no_tag_is_no_lockfile(cache, tmp_path):
    assert lockfile.fetch_compiler_lockfile(cache, "compiler-gcc-15-rocky10-x86_64_v3-000000000000", {}, tmp_path) is None


def test_a_cache_outside_a_registry_has_no_lockfile(tmp_path):
    local = Resource(name="local", kind="spack-buildcache", url=(tmp_path / "cache").as_uri(), signed=False)
    assert lockfile.fetch_compiler_lockfile(local, "any", {}, tmp_path) is None


def test_a_tag_with_something_else_is_an_error(cache, tmp_path):
    FakeRegistry.manifests["other"] = json.dumps({"schemaVersion": 2, "layers": [{"mediaType": "application/x-other"}]}).encode()
    with pytest.raises(RegistryError, match="holds no compiler lockfile"):
        lockfile.fetch_compiler_lockfile(cache, "other", {}, tmp_path)


def test_the_lockfile_of_the_toolchain_is_looked_for_in_its_build_cache(cache, tmp_path):
    from seanerstack.config import Config, Toolchain
    tag, _ = _publish(cache, tmp_path)
    toolchain = Toolchain(compiler="gcc@15", packages=(), cache="cache", target="x86_64_v3", platforms={})
    config = Config(path=tmp_path / "config.toml", resources={"cache": cache}, toolchain=toolchain)

    found = lockfile.find_compiler_lockfile(config, {}, **WHERE, directory=tmp_path / "found")

    assert found == tmp_path / "found" / f"{tag}.lock"
    without = Config(path=config.path, resources=config.resources)
    assert lockfile.find_compiler_lockfile(without, {}, **WHERE, directory=tmp_path) is None


def test_a_config_without_the_cache_of_its_toolchain_has_no_lockfile(tmp_path):
    from seanerstack.config import Config, Toolchain
    toolchain = Toolchain(compiler="gcc@15", packages=(), cache="seanerstack-buildcache", target="x86_64_v3", platforms={})
    config = Config(path=tmp_path / "config.toml", resources={}, toolchain=toolchain)
    assert lockfile.find_compiler_lockfile(config, {}, **WHERE, directory=tmp_path) is None


def _caches(tmp_path, *names, cache="public", bootstrap=None):
    from seanerstack.config import Config, Toolchain
    resources = {
        name: Resource(name=name, kind="spack-buildcache", url=f"oci://registry.example.org/{name}", signed=False)
        for name in names
    }
    toolchain = Toolchain(compiler="gcc@15", packages=(), cache=cache, target="x86_64_v3", platforms={}, bootstrap_cache=bootstrap)
    return Config(path=tmp_path / "config.toml", resources=resources, toolchain=toolchain)


def test_the_lockfile_is_looked_for_in_the_cache_of_the_toolchain_first_then_in_the_other_caches(monkeypatch, tmp_path):
    asked = []
    monkeypatch.setattr(lockfile, "fetch_compiler_lockfile", lambda resource, tag, env, directory, **options: asked.append(resource.name))

    assert lockfile.find_compiler_lockfile(_caches(tmp_path, "project", "public", "local"), {}, **WHERE, directory=tmp_path) is None
    assert asked == ["public", "project", "local"]


def test_the_first_cache_with_a_lockfile_gives_it_and_the_bootstrap_cache_is_not_asked(monkeypatch, tmp_path):
    asked = []

    def fetch(resource, tag, env, directory, **options):
        asked.append(resource.name)
        return tmp_path / f"{resource.name}.lock" if resource.name == "project" else None

    monkeypatch.setattr(lockfile, "fetch_compiler_lockfile", fetch)
    config = _caches(tmp_path, "boot", "project", "public", "local", bootstrap="boot")

    assert lockfile.find_compiler_lockfile(config, {}, **WHERE, directory=tmp_path) == tmp_path / "project.lock"
    # The bootstrap cache holds only the first stage of the compiler.
    assert asked == ["public", "project"]


def test_a_cache_without_a_lockfile_takes_the_one_of_the_registry_that_it_is_filled_from(cache, tmp_path):
    from seanerstack.config import Config, Toolchain
    tag, _ = _publish(cache, tmp_path)
    public = Resource(name="public", kind="spack-buildcache", url="s3://bucket", endpoint_url="https://s3.example.org", signed=False)
    toolchain = Toolchain(compiler="gcc@15", packages=(), cache="public", target="x86_64_v3", platforms={})
    config = Config(path=tmp_path / "config.toml", resources={"public": public, "cache": cache}, toolchain=toolchain)

    found = lockfile.find_compiler_lockfile(config, {}, **WHERE, directory=tmp_path / "found")

    assert found == tmp_path / "found" / f"{tag}.lock"


def test_the_lockfile_is_an_ordinary_image_of_one_layer(cache, tmp_path):
    # A registry that checks media types, such as GitLab's, refuses types of its own.
    import gzip
    import hashlib
    import io
    import tarfile
    tag, _ = _publish(cache, tmp_path)

    manifest = json.loads(FakeRegistry.manifests[tag])
    assert manifest["mediaType"] == "application/vnd.oci.image.manifest.v1+json"
    assert manifest["config"]["mediaType"] == "application/vnd.oci.image.config.v1+json"
    (layer,) = manifest["layers"]
    assert layer["mediaType"] == "application/vnd.oci.image.layer.v1.tar+gzip"

    blob = FakeRegistry.blobs[layer["digest"]]
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        assert archive.getnames() == ["spack.lock"]
        assert json.loads(archive.extractfile("spack.lock").read()) == LOCK
    config = json.loads(FakeRegistry.blobs[manifest["config"]["digest"]])
    assert config["rootfs"]["diff_ids"] == [f"sha256:{hashlib.sha256(gzip.decompress(blob)).hexdigest()}"]
    assert (config["architecture"], config["os"]) == ("amd64", "linux")


def test_the_same_lockfile_is_the_same_layer():
    assert lockfile._layer(b"same") == lockfile._layer(b"same")
    assert lockfile._layer(b"same") != lockfile._layer(b"other")


def test_a_layer_without_a_lockfile_is_an_error(cache, tmp_path):
    import gzip
    import io
    import tarfile
    from seanerstack.registry import Registry
    registry = Registry.of(cache, {})
    other = io.BytesIO()
    with tarfile.open(fileobj=other, mode="w") as archive:
        archive.addfile(tarfile.TarInfo("README"), io.BytesIO(b""))
    digest = registry.put_blob(gzip.compress(other.getvalue()))
    FakeRegistry.manifests["other-layer"] = json.dumps(
        {"schemaVersion": 2, "layers": [{"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip", "digest": digest}]}
    ).encode()
    with pytest.raises(RegistryError, match="holds no compiler lockfile"):
        lockfile.fetch_compiler_lockfile(cache, "other-layer", {}, tmp_path)
