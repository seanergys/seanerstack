# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import yaml

from seanerstack.config import load_config


def _toolchain_job() -> dict:
    ci = yaml.safe_load((Path(__file__).parents[2] / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    return ci["toolchain"]


def _steps(job: dict) -> list[str]:
    """The script of a job, with the steps of the anchors it includes."""
    steps: list[str] = []
    for step in job["script"]:
        steps += step if isinstance(step, list) else [step]
    return steps


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


def test_the_nightly_toolchain_job_runs_spack_with_the_python_of_its_platform():
    job = _toolchain_job()
    setup = job["before_script"]
    export = setup.index('export SPACK_PYTHON="$(command -v "$PYTHON")"')
    # Before Spack first runs, and for every step after it, explain included.
    assert setup.index('"$PYTHON" -m venv /opt/seanerstack') < export
    assert not any("SPACK_PYTHON" in step for step in job["script"])


def test_the_nightly_toolchain_job_asks_only_for_the_python_of_its_platform():
    # Not every Python has a pip package of its own, and venv needs none.
    (install,) = [step for step in _toolchain_job()["before_script"] if "dnf install" in step]
    assert 'dnf install -y --setopt=install_weak_deps=False "$PYTHON"\n' in install


HOW_TO = Path(__file__).parents[2] / "tests" / "how-to" / "work-on-a-package.sh"


def test_the_how_to_job_runs_the_script_of_the_guide_in_a_state_set_up_like_a_users():
    ci = yaml.safe_load((Path(__file__).parents[2] / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    job = ci["how-to:work-on-a-package"]
    assert job["before_script"] == ci["build:rocky10"]["before_script"]
    # The state as the tutorial leaves it, then nothing after the script of the guide.
    steps = _steps(job)
    init = next(index for index, step in enumerate(steps) if step.startswith("seanerstack --secrets-file"))
    assert init < steps.index('eval "$(seanerstack activate)"') < steps.index("seanerstack toolchain bootstrap")
    assert steps[-1] == "tests/how-to/work-on-a-package.sh"
    assert HOW_TO.stat().st_mode & 0o111


def test_the_guide_shows_every_section_of_the_script_that_tests_it():
    guide = (Path(__file__).parents[2] / "docs" / "how-to" / "work-on-a-package.md").read_text(encoding="utf-8")
    sections = [line.split("[start:")[1].rstrip("]") for line in HOW_TO.read_text(encoding="utf-8").splitlines() if "[start:" in line]
    assert sections == ["checkout", "activate", "develop", "install", "check", "deactivate"]
    for section in sections:
        assert f'--8<-- "tests/how-to/work-on-a-package.sh:{section}"' in guide


TUTORIAL = Path(__file__).parents[2] / "tests" / "tutorials" / "install-the-stack.sh"


def test_the_tutorial_job_runs_the_script_of_the_tutorial_with_the_seanerstack_of_the_commit():
    ci = yaml.safe_load((Path(__file__).parents[2] / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    job = ci["tutorial:install-the-stack"]
    # The same preparation as build:rocky10, which installs the checkout.
    assert job["before_script"] == ci["build:rocky10"]["before_script"]
    # In the directory of secrets.toml, with the vault password on standard input.
    assert _steps(job)[-2:] == ["cd /tmp", '"$CI_PROJECT_DIR/tests/tutorials/install-the-stack.sh" < /tmp/vault-password']
    assert TUTORIAL.stat().st_mode & 0o111


def test_the_tutorial_shows_every_section_of_the_script_that_tests_it():
    page = (Path(__file__).parents[2] / "docs" / "tutorials" / "getting-started.md").read_text(encoding="utf-8")
    sections = [line.split("[start:")[1].rstrip("]") for line in TUTORIAL.read_text(encoding="utf-8").splitlines() if "[start:" in line]
    assert {"install", "state", "activate", "toolchain", "stack", "find"} <= set(sections)
    for section in sections:
        assert f'--8<-- "tests/tutorials/install-the-stack.sh:{section}"' in page
    # The page types no command of its own.
    assert "```console" not in page


def test_the_jobs_that_install_from_the_cache_use_a_random_state_directory():
    ci = yaml.safe_load((Path(__file__).parents[2] / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    for name in ("tutorial:install-the-stack", "how-to:work-on-a-package"):
        steps = _steps(ci[name])
        (choose,) = [index for index, step in enumerate(steps) if step.startswith("export SEANERSTACK_STATE_DIR=")]
        assert "mktemp -d" in steps[choose] and "$RANDOM" in steps[choose]
        # Before anything sets the state up, and nothing names the default directory after it.
        assert not any("seanerstack" in step.split("=")[0] for step in steps[:choose] if "git config" not in step)
        assert not any("/opt/seanergys/state" in step for step in steps)
    # The tutorial script keeps a directory that is named, and only then chooses the documented one.
    script = TUTORIAL.read_text(encoding="utf-8")
    assert '[ -n "${SEANERSTACK_STATE_DIR:-}" ] || choose_state_directory' in script


def test_the_nightly_toolchain_job_builds_below_a_padded_prefix():
    job = _toolchain_job()
    assert int(job["variables"]["PADDED_LENGTH"]) >= 200
    (prepare,) = [step for step in job["script"] if "buildcache prepare" in step]
    assert '--padded-length "$PADDED_LENGTH"' in prepare
