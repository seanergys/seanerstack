# SPDX-License-Identifier: Apache-2.0
"""A package pushed to a build cache in the project registry and installed back from it."""

from __future__ import annotations

from pathlib import Path
import shlex

from conftest import E2E_SPEC, Commands, environment, files_containing

# The build cache of the round-trip test, declared in its own config.toml.
E2E_BUILDCACHE = "e2e-buildcache"
E2E_VARIABLES = (
    "SEANERSTACK_RESOURCE_E2E_BUILDCACHE_USERNAME",
    "SEANERSTACK_RESOURCE_E2E_BUILDCACHE_PASSWORD",
)



def _write_e2e_config(path: Path, url: str) -> Path:
    path.write_text(
        f"""[resources.{E2E_BUILDCACHE}]
kind = "spack-buildcache"
url = "{url}"
credentials = "seanergys-registry"
signed = false
""",
        encoding="utf-8",
    )
    return path


def test_buildcache_round_trip(commands: Commands, secrets_file: Path, password_file: Path, spack: Path, buildcache_url: str, tmp_path: Path):
    """Build a package, push it to the test cache, and install it back from there."""
    state = tmp_path / "state"
    options = " ".join(
        shlex.quote(str(value))
        for value in (
            "--config-file", _write_e2e_config(tmp_path / "config.toml", buildcache_url),
            "--state-dir", state,
            "--spack-executable", spack,
            "--secrets-file", secrets_file,
            "--secrets-password-file", password_file,
        )
    )

    # The test cache may not exist before the first push, so only the setup
    # matters here; the second init below has to pass.
    commands.shell(f"seanerstack {options} init || true", env=environment())
    wrapper = shlex.quote(str(state / "spack" / "bin"))

    # Build from source even if an earlier pipeline pushed the same spec, and
    # replace it in the cache. The system make spares building make itself.
    # Spack is the state's wrapper, with no activation.
    push = commands.shell(
        f"""
        export PATH={wrapper}:$PATH
        spack compiler find
        spack external find gmake
        spack install --no-cache {E2E_SPEC}
        spack buildcache push --force --unsigned --update-index {E2E_BUILDCACHE} {E2E_SPEC}
        """,
        env=environment(),
    )
    assert push.returncode == 0, push.stdout[-4000:] + push.stderr[-4000:]

    # Everything init needs is in the state now: no config, Spack or secrets file.
    check = commands.shell(f"seanerstack --state-dir {shlex.quote(str(state))} init", env=environment())
    assert check.returncode == 0, check.stdout + check.stderr
    assert f"[OK] buildcache:{E2E_BUILDCACHE}" in check.stdout, check.stdout
    assert f"{E2E_SPEC.partition('@')[0]}@" in check.stdout, check.stdout

    # With nothing installed any more, the spec can only come from the cache.
    pull = commands.shell(
        f"""
        export PATH={wrapper}:$PATH
        spack uninstall --all --yes-to-all
        spack install --use-buildcache only {E2E_SPEC}
        spack find {E2E_SPEC}
        """,
        env=environment(),
    )
    assert pull.returncode == 0, pull.stdout[-4000:] + pull.stderr[-4000:]

    assert not any(result.leaked for result in (push, check, pull))
    # Spack's mirror configuration names the variables, never the token, which
    # is only in the two credentials files.
    mirrors = (state / "spack" / "config" / "mirrors.yaml").read_text(encoding="utf-8")
    assert all(name in mirrors for name in E2E_VARIABLES), mirrors
    assert set(files_containing(state, commands.token)) == {state / "credentials.json", state / "spack" / "credentials.sh"}
