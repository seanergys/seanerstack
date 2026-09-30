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
