# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from seanstack.config import Config, Resource
from seanstack.isolation import (
    BUILTIN_REPO_GIT,
    activation_script,
    deactivation_script,
    layout,
    prepare_isolation,
    spack_env,
)


def test_isolation_paths_never_default_to_home(tmp_path: Path):
    state = tmp_path / "state"
    real_spack = tmp_path / "real-spack"
    real_spack.write_text("#!/bin/sh\n", encoding="utf-8")
    x = prepare_isolation(state, real_spack)

    env = spack_env(x)
    assert env["SPACK_USER_CONFIG_PATH"] == str(state / "spack" / "config")
    assert env["SPACK_SYSTEM_CONFIG_PATH"].startswith(str(state))
    assert env["SPACK_USER_CACHE_PATH"] == str(state / "spack" / "cache")

    config_yaml = (x.config / "config.yaml").read_text(encoding="utf-8")
    for directory in (x.store, x.stage, x.cache, x.source_cache, x.environments):
        assert str(directory) in config_yaml
    assert "~/" not in config_yaml
    assert "/home/" not in config_yaml


def test_private_scope_replaces_external_configuration(tmp_path: Path):
    state = tmp_path / "state"
    real_spack = tmp_path / "real-spack"
    real_spack.write_text("#!/bin/sh\n", encoding="utf-8")
    x = prepare_isolation(state, real_spack)

    assert (x.config / "config.yaml").read_text().startswith("config::")
    assert (x.config / "packages.yaml").read_text() == "packages:: {}\n"
    assert (x.config / "mirrors.yaml").read_text() == "mirrors:: {}\n"
    assert (x.config / "upstreams.yaml").read_text() == "upstreams:: {}\n"
    # concretizer is merged rather than replaced, so Spack keeps its own
    # structured defaults underneath.
    concretizer = (x.config / "concretizer.yaml").read_text()
    assert concretizer.startswith("concretizer:\n")
    assert "reuse: false" in concretizer


def test_activation_makes_isolated_spack_default_and_deactivation_restores(tmp_path: Path):
    state = tmp_path / "state"
    real_spack = tmp_path / "spack-src" / "bin" / "spack"
    real_spack.parent.mkdir(parents=True)
    real_spack.write_text("#!/bin/sh\n", encoding="utf-8")
    cfg = Config(path=tmp_path / "config.toml", resources={})
    original = {
        "PATH": "/usr/bin:/bin",
        "SPACK_USER_CACHE_PATH": "/hostile/home/.spack",
    }

    script = activation_script(
        state_dir=state,
        real_spack=real_spack,
        config=cfg,
        environ=original,
    )
    x = layout(state)
    assert f"export PATH={x.bin}:/usr/bin:/bin" in script
    assert f"export SPACK_USER_CONFIG_PATH={x.config}" in script
    assert f"export SEANSTACK_REAL_SPACK={real_spack}" in script

    shim = (x.bin / "spack").read_text(encoding="utf-8")
    assert 'exec "$SEANSTACK_REAL_SPACK" -C "$SEANSTACK_SPACK_CONFIG_DIR" "$@"' in shim

    active = {
        "SEANSTACK_ACTIVE": "1",
        "PATH": f"{x.bin}:/usr/bin:/bin",
        "SEANSTACK_SAVED_PATH_SET": "1",
        "SEANSTACK_SAVED_PATH": "/usr/bin:/bin",
        "SPACK_USER_CACHE_PATH": str(x.cache),
        "SEANSTACK_SAVED_SPACK_USER_CACHE_PATH_SET": "1",
        "SEANSTACK_SAVED_SPACK_USER_CACHE_PATH": "/hostile/home/.spack",
    }
    deactivate = deactivation_script(active)
    assert "export PATH=/usr/bin:/bin" in deactivate
    assert "export SPACK_USER_CACHE_PATH=/hostile/home/.spack" in deactivate


def test_prepare_isolation_preserves_managed_spack_configuration(tmp_path: Path):
    state = tmp_path / "state"
    real_spack = tmp_path / "real-spack"
    real_spack.write_text("#!/bin/sh\n", encoding="utf-8")
    x = prepare_isolation(state, real_spack)
    (x.config / "packages.yaml").write_text("packages::\n  c:\n    require: [gcc@15]\n", encoding="utf-8")
    (x.config / "mirrors.yaml").write_text("mirrors::\n  cache: s3://builds\n", encoding="utf-8")

    prepare_isolation(state, real_spack)

    assert "gcc@15" in (x.config / "packages.yaml").read_text(encoding="utf-8")
    assert "s3://builds" in (x.config / "mirrors.yaml").read_text(encoding="utf-8")


def test_user_scope_stays_writable(tmp_path: Path):
    # SPACK_DISABLE_LOCAL_CONFIG switches the user scope off, and that scope is
    # the only writable one in the isolated setup: `-C` scopes are read-only.
    # Leaving it set sends `spack config add` to the site scope instead, where
    # the private `::` keys override it and it has no effect.
    state = tmp_path / "state"
    real_spack = tmp_path / "real-spack"
    real_spack.write_text("#!/bin/sh\n", encoding="utf-8")
    x = prepare_isolation(state, real_spack)

    assert "SPACK_DISABLE_LOCAL_CONFIG" not in spack_env(x)


def test_activation_clears_an_inherited_disable_local_config(tmp_path: Path):
    # Spack tests for the presence of the variable, not its value, so one
    # inherited from the caller has to be removed, not overridden.
    state = tmp_path / "state"
    real_spack = tmp_path / "spack-src" / "bin" / "spack"
    real_spack.parent.mkdir(parents=True)
    real_spack.write_text("#!/bin/sh\n", encoding="utf-8")
    cfg = Config(path=tmp_path / "config.toml", resources={})

    script = activation_script(
        state_dir=state,
        real_spack=real_spack,
        config=cfg,
        environ={"PATH": "/usr/bin", "SPACK_DISABLE_LOCAL_CONFIG": "true"},
    )

    assert "unset SPACK_DISABLE_LOCAL_CONFIG" in script
    # Saved, so deactivation can put it back.
    assert "export SEANSTACK_SAVED_SPACK_DISABLE_LOCAL_CONFIG=true" in script
    assert "export SEANSTACK_SAVED_SPACK_DISABLE_LOCAL_CONFIG_SET=1" in script


def test_private_scope_carries_the_builtin_repository(tmp_path: Path):
    # `repos::` replaces Spack's defaults, which is where builtin is declared.
    # Without it no package loads: every recipe imports from spack_repo.builtin.
    state = tmp_path / "state"
    real_spack = tmp_path / "real-spack"
    real_spack.write_text("#!/bin/sh\n", encoding="utf-8")
    x = prepare_isolation(state, real_spack)

    repos = (x.config / "repos.yaml").read_text(encoding="utf-8")
    assert repos.startswith("repos::")
    assert BUILTIN_REPO_GIT in repos
    assert "seanstack:" in repos
    # Seanstack is listed first so its own recipes take precedence.
    assert repos.index("seanstack:") < repos.index("builtin:")
