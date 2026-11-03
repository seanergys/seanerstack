# SPDX-License-Identifier: Apache-2.0
from seanerstack.config import load_config


def test_the_shipped_toolchain_applies_to_a_config_without_one(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[toolchain]\ncache = "elsewhere"\n', encoding="utf-8")
    toolchain = load_config(path).toolchain
    assert toolchain.cache == "elsewhere"
    assert toolchain.compiler == "gcc@15"
    assert "rust" in toolchain.packages and "capnproto" in toolchain.packages
