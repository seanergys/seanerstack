# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from seanstack.config import load_config


def test_named_resources_and_credentials(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        '''[resources.gitlab]\nkind = "git"\nurl = "https://gitlab.example.org/"\ncredentials = "gitlab-user"\n\n[resources.cache]\nkind = "spack-buildcache"\nurl = "s3://builds"\nendpoint_url = "https://s3.example.org"\ncredentials = "objectstore"\nautopush = true\nsigned = false\n''',
        encoding="utf-8",
    )

    config = load_config(path)
    assert config.resource("gitlab").credentials == "gitlab-user"
    assert config.resource("cache").env_prefix == "SEANSTACK_RESOURCE_CACHE"
    assert config.resource("cache").autopush is True
