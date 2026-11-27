# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

from seanerstack.config import load_config


def test_named_resources_and_credentials(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        '''[resources.gitlab]\nkind = "git"\nurl = "https://gitlab.example.org/"\ncredentials = "gitlab-user"\n\n[resources.cache]\nkind = "spack-buildcache"\nurl = "s3://builds"\nendpoint_url = "https://s3.example.org"\ncredentials = "objectstore"\nautopush = true\nsigned = false\n''',
        encoding="utf-8",
    )

    config = load_config(path)
    assert config.resource("gitlab").credentials == "gitlab-user"
    assert config.resource("cache").env_prefix == "SEANERSTACK_RESOURCE_CACHE"
    assert config.resource("cache").autopush is True


def test_oci_build_cache_must_be_unsigned(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[resources.registry]\nkind = "spack-buildcache"\nurl = "oci://registry.example.org/cache"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cannot be signed"):
        load_config(path)


def test_shipped_config_names_the_project_registry_cache():
    cache = load_config().resource("seanerstack-buildcache")

    assert cache.oci and not cache.signed
    assert cache.credential_variables == (
        "SEANERSTACK_RESOURCE_SEANERSTACK_BUILDCACHE_USERNAME",
        "SEANERSTACK_RESOURCE_SEANERSTACK_BUILDCACHE_PASSWORD",
    )


def test_filesystem_build_cache_defaults_to_unsigned(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[resources.local]\nkind = "spack-buildcache"\nurl = "file:///scratch/buildcache"\n',
        encoding="utf-8",
    )

    cache = load_config(path).resource("local")
    assert cache.filesystem and not cache.oci
    assert cache.signed is False
    assert cache.credentials is None


def test_filesystem_build_cache_can_be_signed(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[resources.local]\nkind = "spack-buildcache"\nurl = "file:///scratch/buildcache"\nsigned = true\n',
        encoding="utf-8",
    )

    assert load_config(path).resource("local").signed is True


def test_filesystem_build_cache_takes_no_credentials(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[resources.local]\nkind = "spack-buildcache"\nurl = "file:///scratch/buildcache"\ncredentials = "objectstore"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="take no credentials"):
        load_config(path)


def test_s3_build_cache_still_defaults_to_signed(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[resources.cache]\nkind = "spack-buildcache"\nurl = "s3://builds"\n',
        encoding="utf-8",
    )

    assert load_config(path).resource("cache").signed is True


def test_shipped_config_names_the_bootstrap_cache_beside_the_project_cache():
    config = load_config()
    cache = config.resource(config.toolchain.bootstrap_cache)

    assert cache.name == "seanerstack-buildcache-bootstrap"
    assert cache.url == "oci://registry.seanergys.fz-juelich.de/software/seanerstack/buildcache-bootstrap"
    assert cache.oci and not cache.signed
    # The registry of the project cache, with its credentials.
    assert cache.credentials == config.resource(config.toolchain.cache).credentials


def test_a_config_without_a_bootstrap_cache_keeps_the_shipped_one(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text('[toolchain]\ncompiler = "gcc@14"\n', encoding="utf-8")
    assert load_config(path).toolchain.bootstrap_cache == "seanerstack-buildcache-bootstrap"


def test_the_scheme_of_a_resource_is_that_of_its_url():
    from seanerstack.config import Resource

    def resource(url):
        return Resource(name="cache", kind="spack-buildcache", url=url, signed=False)

    assert [resource(url).scheme for url in ("oci://r/c", "oci+http://r/c", "s3://b", "file:///c", "https://h/", "c")] == [
        "oci", "oci+http", "s3", "file", "https", "",
    ]
    assert resource("oci+http://r/c").oci and not resource("oci+http://r/c").s3
    assert resource("s3://b").s3 and not resource("s3://b").oci and not resource("s3://b").filesystem
    assert resource("file:///c").filesystem and not resource("https://h/").s3
    # As before, a scheme is matched as written.
    assert not resource("OCI://r/c").oci
