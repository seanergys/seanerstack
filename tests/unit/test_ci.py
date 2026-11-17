# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import yaml

from seanerstack.config import load_config


def _toolchain_job() -> dict:
    ci = yaml.safe_load((Path(__file__).parents[2] / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    return ci["toolchain"]


def _matrix_platforms(job: dict) -> list[str]:
    # An entry names one platform, or several that share everything else.
    names: list[str] = []
    for entry in job["parallel"]["matrix"]:
        value = entry["PLATFORM"]
        names += value if isinstance(value, list) else [value]
    return names


def test_the_nightly_toolchain_job_builds_every_shipped_platform():
    assert _matrix_platforms(_toolchain_job()) == list(load_config().toolchain.platforms)


def test_each_nightly_toolchain_job_runs_in_the_image_of_its_platform():
    platforms = load_config().toolchain.platforms
    for entry in _toolchain_job()["parallel"]["matrix"]:
        platform = platforms[entry["PLATFORM"]]
        assert entry["IMAGE"] == platform.image
        assert entry.get("PYTHON", "python3") == platform.python


def test_the_nightly_toolchain_job_needs_no_docker_daemon():
    job = _toolchain_job()
    assert job["tags"] == ["docker", "seanerstack"]
    assert "services" not in job
    assert any("buildcache prepare --no-container" in step for step in job["script"])


def test_the_nightly_toolchain_job_explains_after_it_prepared_and_keeps_the_status():
    script = _toolchain_job()["script"]
    prepare = next(index for index, step in enumerate(script) if "buildcache prepare" in step)
    explain = next(index for index, step in enumerate(script) if "buildcache explain" in step)
    assert prepare < explain
    assert "|| status=$?" in script[prepare]
    assert "|| true" in script[explain]
    assert script[-1] == 'exit "$status"'


def test_the_rocky10_build_job_explains_after_bootstrap_and_before_it_installs():
    ci = yaml.safe_load((Path(__file__).parents[2] / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    script = ci["build:rocky10"]["script"]
    bootstrap = next(index for index, step in enumerate(script) if "toolchain bootstrap" in step)
    explain = next(index for index, step in enumerate(script) if "buildcache explain" in step)
    install = next(index for index, step in enumerate(script) if 'spack -e "$ENVIRONMENT" install' in step)
    assert bootstrap < explain < install
    assert "seanergys-meta" in script[explain - 1]
    assert "|| true" in script[explain]
