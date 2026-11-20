# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import re

import pytest
import yaml

from seanerstack.config import Config, Resource
from seanerstack.isolation import (
    BUILTIN_REPO_COMMIT,
    BUILTIN_REPO_GIT,
    GUARDED_COMPILERS,
    activation_script,
    deactivation_script,
    guarded_path,
    layout,
    prepare_bootstrap_instance,
    prepare_isolation,
    spack_env,
)
from seanerstack.pins import SPACK_COMMIT, SPACK_VERSION
from seanerstack.secrets import SecretStore

PINNED = SPACK_VERSION


def test_activation_skips_build_caches_without_vault_credentials(tmp_path: Path):
    real_spack = tmp_path / "spack-src" / "bin" / "spack"
    real_spack.parent.mkdir(parents=True)
    real_spack.write_text("#!/bin/sh\n", encoding="utf-8")
    resources = {
        name: Resource(
            name=name,
            kind="spack-buildcache",
            url=f"oci://registry.example.org/{name}",
            credentials=name,
            signed=False,
        )
        for name in ("present", "absent")
    }
    secrets = SecretStore(tmp_path / "vault", _data={"credentials": {"present": {"token": "glpat"}}})

    script = activation_script(
        state_dir=tmp_path / "state",
        real_spack=real_spack,
        config=Config(path=tmp_path / "config.toml", resources=resources),
        secrets=secrets,
        environ={"PATH": "/usr/bin"},
    )

    assert "export SEANERSTACK_RESOURCE_PRESENT_PASSWORD=glpat" in script
    assert "SEANERSTACK_RESOURCE_ABSENT_PASSWORD" not in script


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
    assert f"export SEANERSTACK_REAL_SPACK={real_spack}" in script

    active = {
        "SEANERSTACK_ACTIVE": "1",
        "PATH": f"{x.bin}:/usr/bin:/bin",
        "SEANERSTACK_SAVED_PATH_SET": "1",
        "SEANERSTACK_SAVED_PATH": "/usr/bin:/bin",
        "SPACK_USER_CACHE_PATH": str(x.cache),
        "SEANERSTACK_SAVED_SPACK_USER_CACHE_PATH_SET": "1",
        "SEANERSTACK_SAVED_SPACK_USER_CACHE_PATH": "/hostile/home/.spack",
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
    assert "export SEANERSTACK_SAVED_SPACK_DISABLE_LOCAL_CONFIG=true" in script
    assert "export SEANERSTACK_SAVED_SPACK_DISABLE_LOCAL_CONFIG_SET=1" in script


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
    assert "seanerstack:" in repos
    # Seanerstack is listed first so its own recipes take precedence.
    assert repos.index("seanerstack:") < repos.index("builtin:")


def test_builtin_repository_location_can_be_overridden(tmp_path: Path, monkeypatch):
    real_spack = tmp_path / "real-spack"
    real_spack.write_text("#!/bin/sh\n", encoding="utf-8")
    mirror = tmp_path / "mirror" / "spack-packages.git"
    monkeypatch.setenv("SEANERSTACK_BUILTIN_REPO_GIT", str(mirror))
    x = prepare_isolation(tmp_path / "state", real_spack)

    builtin = yaml.safe_load((x.config / "repos.yaml").read_text(encoding="utf-8"))["repos:"]["builtin"]
    assert builtin["git"] == str(mirror)
    # The pin is not affected, so build-cache hashes stay the same.
    assert builtin["commit"] == BUILTIN_REPO_COMMIT


def test_builtin_repository_is_pinned_and_cloned_inside_the_state(tmp_path: Path):
    real_spack = tmp_path / "real-spack"
    real_spack.write_text("#!/bin/sh\n", encoding="utf-8")
    x = prepare_isolation(tmp_path / "state", real_spack)

    builtin = yaml.safe_load((x.config / "repos.yaml").read_text(encoding="utf-8"))["repos:"]["builtin"]
    assert builtin["git"] == BUILTIN_REPO_GIT
    assert builtin["commit"] == BUILTIN_REPO_COMMIT
    assert re.fullmatch(r"[0-9a-f]{40}", BUILTIN_REPO_COMMIT)
    # Inside the state, not ~/.spack/package_repos, and named after the commit
    # so that a new pin gets its own clone.
    destination = Path(builtin["destination"])
    assert destination.parent == x.package_repos
    assert destination.name == f"builtin-{BUILTIN_REPO_COMMIT[:12]}"


def test_existing_state_follows_a_new_pin(tmp_path: Path):
    real_spack = tmp_path / "real-spack"
    real_spack.write_text("#!/bin/sh\n", encoding="utf-8")
    x = prepare_isolation(tmp_path / "state", real_spack)
    (x.config / "repos.yaml").write_text(
        f"repos::\n  builtin:\n    git: {BUILTIN_REPO_GIT}\n    commit: {'0' * 40}\n", encoding="utf-8"
    )

    prepare_isolation(tmp_path / "state", real_spack)

    repos = (x.config / "repos.yaml").read_text(encoding="utf-8")
    assert BUILTIN_REPO_COMMIT in repos
    assert "0" * 40 not in repos


def test_the_state_directory_defaults_to_where_the_cached_binaries_were_built(monkeypatch):
    import seanerstack.isolation
    monkeypatch.delenv("SEANERSTACK_STATE_DIR", raising=False)
    assert seanerstack.isolation.resolve_state_dir(None) == Path("/opt/seanergys/state")


def test_the_state_directory_variable_overrides_the_default(monkeypatch, tmp_path):
    import seanerstack.isolation
    monkeypatch.setenv("SEANERSTACK_STATE_DIR", str(tmp_path))
    assert seanerstack.isolation.resolve_state_dir(None) == tmp_path.resolve()


def test_the_toolchain_is_built_in_the_default_state_directory():
    import seanerstack.prepare
    assert seanerstack.prepare.CONTAINER_STATE == "/opt/seanergys/state"


def _fake_spack_executable(path: Path, version: str, commit: str | None = SPACK_COMMIT) -> Path:
    """A `spack` that reports `version`, and `commit` as a Git checkout does."""
    path.parent.mkdir(parents=True, exist_ok=True)
    reported = f"{version} ({commit})" if commit else version
    path.write_text(f"#!/bin/sh\necho '{reported}'\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_the_pinned_spack_is_installed_into_the_state_directory(monkeypatch, tmp_path):
    import seanerstack.isolation
    clones = []

    def fake_run(args, **kwargs):
        clones.append(args)
        # `git init DIR`, then `git -C DIR fetch` and `git -C DIR checkout`.
        destination = Path(args[-1] if args[1] == "init" else args[2])
        _fake_spack_executable(destination / "bin" / "spack", PINNED)

    monkeypatch.delenv("SEANERSTACK_REAL_SPACK", raising=False)
    monkeypatch.setattr(seanerstack.isolation.subprocess, "run", fake_run)
    spack = seanerstack.isolation.resolve_real_spack(None, tmp_path)
    partial = str(tmp_path / f"spack-{SPACK_COMMIT[:12]}.partial")
    assert spack == tmp_path / f"spack-{SPACK_COMMIT[:12]}" / "bin" / "spack"
    # A commit of develop is no branch or tag, so it is fetched by itself.
    assert clones == [
        ["git", "init", "--quiet", partial],
        ["git", "-C", partial, "fetch", "--quiet", "--depth", "1", "https://github.com/spack/spack.git", SPACK_COMMIT],
        ["git", "-C", partial, "-c", "advice.detachedHead=false", "checkout", "--quiet", "FETCH_HEAD"],
    ]

    # The next command finds it and clones nothing.
    assert seanerstack.isolation.resolve_real_spack(None, tmp_path) == spack
    assert len(clones) == 3


def test_another_spack_of_the_pinned_version_is_used(monkeypatch, tmp_path):
    import seanerstack.isolation
    monkeypatch.delenv("SEANERSTACK_REAL_SPACK", raising=False)
    spack = _fake_spack_executable(tmp_path / "spack", PINNED)
    assert seanerstack.isolation.resolve_real_spack(spack, tmp_path / "state") == spack.resolve()


def test_another_spack_version_is_refused(monkeypatch, tmp_path):
    import seanerstack.isolation
    monkeypatch.delenv("SEANERSTACK_REAL_SPACK", raising=False)
    spack = _fake_spack_executable(tmp_path / "spack", "1.2.2", None)
    with pytest.raises(RuntimeError, match=f"is Spack 1.2.2 without a commit, and Seanerstack needs Spack {PINNED} at commit {SPACK_COMMIT[:10]}"):
        seanerstack.isolation.resolve_real_spack(spack, tmp_path / "state")


def test_another_commit_of_the_pinned_version_is_refused(monkeypatch, tmp_path):
    # Every commit of develop reports the same development version.
    import seanerstack.isolation
    monkeypatch.delenv("SEANERSTACK_REAL_SPACK", raising=False)
    for name, commit in (("other", "0123456789abcdef"), ("none", None)):
        spack = _fake_spack_executable(tmp_path / name / "spack", PINNED, commit)
        with pytest.raises(RuntimeError, match=f"is Spack {PINNED} (at commit 0123456789|without a commit), and"):
            seanerstack.isolation.resolve_real_spack(spack, tmp_path / "state")


def test_the_spack_variable_is_held_to_the_pinned_version_too(monkeypatch, tmp_path):
    import seanerstack.isolation
    monkeypatch.setenv("SEANERSTACK_REAL_SPACK", str(_fake_spack_executable(tmp_path / "spack", "1.2.2")))
    with pytest.raises(RuntimeError, match="is Spack 1.2.2"):
        seanerstack.isolation.resolve_real_spack(None, tmp_path / "state")


def _recording_spack(path: Path) -> Path:
    """A stand-in for Spack that prints its arguments and the variables it got."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        'echo "args=$*"\n'
        'echo "user=${SPACK_USER_CONFIG_PATH:-}"\n'
        'echo "cache=${SPACK_USER_CACHE_PATH:-}"\n'
        'echo "disable=${SPACK_DISABLE_LOCAL_CONFIG-unset}"\n'
        'echo "token=${SEANERSTACK_RESOURCE_CACHE_PASSWORD:-}"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_the_spack_wrapper_runs_the_state_without_activation(tmp_path: Path):
    import subprocess
    real_spack = _recording_spack(tmp_path / "real spack" / "bin" / "spack")
    x = prepare_isolation(tmp_path / "state", real_spack)

    result = subprocess.run(
        [str(x.bin / "spack"), "find", "zlib"], check=True, capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "SPACK_DISABLE_LOCAL_CONFIG": "true"},
    )

    assert result.stdout.splitlines() == [
        f"args=-C {x.config} find zlib",
        f"user={x.config}",
        f"cache={x.cache}",
        "disable=unset",
        "token=",
    ]


def test_the_spack_wrapper_loads_the_stored_credentials(tmp_path: Path):
    import subprocess
    real_spack = _recording_spack(tmp_path / "spack")
    x = prepare_isolation(tmp_path / "state", real_spack)
    x.credentials_env.write_text("export SEANERSTACK_RESOURCE_CACHE_PASSWORD='s3cret'\n", encoding="utf-8")

    result = subprocess.run([str(x.bin / "spack")], check=True, capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})

    assert "token=s3cret" in result.stdout.splitlines()


def _caches(*names: str) -> dict[str, Resource]:
    return {
        name: Resource(name=name, kind="spack-buildcache", url=f"oci://registry.example.org/{name}", credentials=name, signed=False)
        for name in names
    }


def test_stored_credentials_are_readable_only_by_their_owner(tmp_path: Path):
    import seanerstack.isolation
    x = prepare_isolation(tmp_path / "state", tmp_path / "spack")
    secrets = SecretStore(tmp_path / "vault", _data={"credentials": {"present": {"token": "glpat"}}})

    stored = seanerstack.isolation.store_credentials(x, Config(path=tmp_path / "config.toml", resources=_caches("present", "absent")), secrets)

    assert stored == ["present"]
    assert x.credentials.stat().st_mode & 0o777 == 0o600
    assert x.credentials_env.stat().st_mode & 0o777 == 0o600
    assert SecretStore.stored(x.credentials).credentials("present") == {"token": "glpat"}
    exports = x.credentials_env.read_text(encoding="utf-8")
    assert "export SEANERSTACK_RESOURCE_PRESENT_PASSWORD=glpat\n" in exports
    assert "ABSENT" not in exports


def test_no_stored_credentials_reads_as_no_secrets_file(tmp_path: Path):
    assert SecretStore.stored(tmp_path / "credentials.json").path is None


def test_the_record_remembers_what_init_was_given(tmp_path: Path):
    import seanerstack.isolation
    state = tmp_path / "state"
    assert seanerstack.isolation.read_record(state) == {"config_file": None, "spack_executable": None}
    x = prepare_isolation(state, tmp_path / "spack")
    seanerstack.isolation.write_record(x, config_file=tmp_path / "config.toml", spack_executable=None)
    assert seanerstack.isolation.read_record(state) == {"config_file": tmp_path / "config.toml", "spack_executable": None}


def _bootstrap_instance(tmp_path: Path):
    real_spack = tmp_path / "real-spack"
    real_spack.write_text("#!/bin/sh\n", encoding="utf-8")
    x = prepare_isolation(tmp_path / "state", real_spack)
    env = {"PATH": "/usr/bin", **spack_env(x)}
    return x, real_spack, env, prepare_bootstrap_instance(x, real_spack, env)


def test_the_bootstrap_instance_has_its_own_configuration_and_installations(tmp_path: Path):
    x, real_spack, env, (command, bootstrap_env, b) = _bootstrap_instance(tmp_path)

    assert b.config == x.state / "bootstrap" / "config" and b.store == x.state / "bootstrap" / "store"
    assert command == [str(real_spack), "-C", str(b.config)]
    assert bootstrap_env["SPACK_USER_CONFIG_PATH"] == str(b.config)
    # Spack's own bootstrap, such as clingo, is shared.
    assert bootstrap_env["SPACK_USER_CACHE_PATH"] == env["SPACK_USER_CACHE_PATH"]
    config = yaml.safe_load((b.config / "config.yaml").read_text(encoding="utf-8"))["config:"]
    assert config["install_tree"]["root"] == str(b.store)
    assert config["source_cache"] == str(x.source_cache)
    # Nothing of the actual instance: no compilers, caches or reuse.
    for name, empty in (("packages", {}), ("mirrors", {}), ("upstreams", {})):
        assert yaml.safe_load((b.config / f"{name}.yaml").read_text(encoding="utf-8")) == {f"{name}:": empty}
    assert yaml.safe_load((b.config / "concretizer.yaml").read_text(encoding="utf-8")) == {"concretizer": {"reuse": False}}


def test_the_bootstrap_instance_installs_gcc_at_a_path_without_a_hash(tmp_path: Path):
    # The actual instance hashes the first stage, an external, by its path.
    _, _, _, (_, _, b) = _bootstrap_instance(tmp_path)
    projections = yaml.safe_load((b.config / "config.yaml").read_text(encoding="utf-8"))["config:"]["install_tree"]["projections"]
    assert projections == {"gcc": "{name}-{version}", "all": "{name}-{version}-{hash}"}


def test_the_bootstrap_instance_loads_the_recipes_of_the_actual_one(tmp_path: Path):
    x, _, _, (_, _, b) = _bootstrap_instance(tmp_path)
    assert (b.config / "repos.yaml").read_text(encoding="utf-8") == (x.config / "repos.yaml").read_text(encoding="utf-8")


def test_the_compiler_guard_stops_every_compiler_a_build_finds_on_path(tmp_path: Path):
    import subprocess
    x = prepare_isolation(tmp_path / "state", tmp_path / "spack")
    for name in GUARDED_COMPILERS:
        result = subprocess.run([str(x.guard / name), "--version"], capture_output=True, text=True)
        assert result.returncode == 1, name
        assert f"called {name} from PATH" in result.stderr and 'depends_on("c")' in result.stderr


def test_the_spack_wrapper_puts_the_compiler_guard_in_front_of_path_once(tmp_path: Path):
    import os
    import subprocess
    real_spack = tmp_path / "spack"
    real_spack.write_text('#!/bin/sh\necho "$PATH"\n', encoding="utf-8")
    real_spack.chmod(0o755)
    x = prepare_isolation(tmp_path / "state", real_spack)
    for path in ("/usr/bin:/bin", f"{x.guard}:/usr/bin:/bin"):
        result = subprocess.run([str(x.bin / "spack")], capture_output=True, text=True, env={**os.environ, "PATH": path})
        assert result.stdout.strip() == f"{x.guard}:/usr/bin:/bin"


def test_guarded_path_puts_the_compiler_guard_first_once(tmp_path: Path):
    x = layout(tmp_path / "state")
    assert guarded_path(x, "/usr/bin") == f"{x.guard}:/usr/bin"
    assert guarded_path(x, f"/usr/bin:{x.guard}") == f"{x.guard}:/usr/bin"
    assert guarded_path(x, "") == str(x.guard)


def test_an_activated_shell_keeps_its_compilers(tmp_path: Path):
    # Only Spack runs behind the guard; the user's shell still compiles with what it has.
    real_spack = tmp_path / "spack"
    real_spack.write_text("#!/bin/sh\n", encoding="utf-8")
    script = activation_script(state_dir=tmp_path / "state", real_spack=real_spack, config=Config(path=tmp_path / "config.toml", resources={}), environ={"PATH": "/usr/bin"})
    assert "compiler-guard" not in script
