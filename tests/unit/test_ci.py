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


def test_the_jobs_that_fill_the_cache_build_in_a_long_padded_state_directory():
    ci = yaml.safe_load((Path(__file__).parents[2] / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    for name in ("build:rocky10", "toolchain"):
        variables = ci[name]["variables"]
        # Longer than a user's state directory, and the install prefix padded beyond it.
        assert 120 <= len(variables["STATE"]) < int(variables["PADDED_LENGTH"]) - len("/spack/store")
        assert all(len(part) <= 255 for part in variables["STATE"].split("/"))
    build = _steps(ci["build:rocky10"])
    assert build.index('export SEANERSTACK_STATE_DIR="$STATE"') < next(index for index, step in enumerate(build) if "init" in step)
    assert any('init --padded-length "$PADDED_LENGTH"' in step for step in build)
    assert 'eval "$(seanerstack activate)"' in build
    assert not any("/opt/seanergys/state/spack/bin" in step for step in build)


def test_the_toolchain_job_can_be_started_by_hand_on_any_branch():
    rules = _toolchain_job()["rules"]
    (by_hand,) = [rule for rule in rules if rule.get("when") == "manual" and '"web"' in rule["if"]]
    assert by_hand["if"] == '$CI_COMMIT_BRANCH && $CI_PIPELINE_SOURCE == "web"'
    assert by_hand["allow_failure"] is True
    # The schedule of the default branch starts it by itself, and so does every pipeline while the toolchain is published.
    (scheduled,) = [rule for rule in rules if "when" not in rule]
    assert "$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH" in scheduled["if"] and '"schedule"' in scheduled["if"]


def test_the_rocky10_build_job_pushes_from_every_pipeline():
    job = yaml.safe_load((Path(__file__).parents[2] / ".gitlab-ci.yml").read_text(encoding="utf-8"))["build:rocky10"]
    steps = _steps(job)
    push = steps.index("spack buildcache push --only package seanerstack-buildcache $(spack find --format '/{hash}')")
    # After the install, which keeps its status, and without a condition on the branch.
    install = next(index for index, step in enumerate(steps) if step.startswith('status=0; spack -e "$ENVIRONMENT" install'))
    assert install < push < steps.index("seanerstack buildcache update-index")
    assert not any("CI_DEFAULT_BRANCH" in step for step in steps)


def test_the_rocky10_build_job_publishes_the_toolchain_after_its_push_while_switched_on():
    job = yaml.safe_load((Path(__file__).parents[2] / ".gitlab-ci.yml").read_text(encoding="utf-8"))["build:rocky10"]
    steps = _steps(job)
    publish = next(index for index, step in enumerate(steps) if "seanerstack toolchain publish" in step)
    # The lockfile names the compiler's binaries, which the push before it sent.
    assert steps.index("seanerstack buildcache update-index") < publish < steps.index('exit "$status"')
    assert '[ "$PUBLISH_TOOLCHAIN" = "true" ]' in steps[publish]
    # On by default; a CI/CD variable switches it off without a commit.
    ci = yaml.safe_load((Path(__file__).parents[2] / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    assert ci["variables"]["PUBLISH_TOOLCHAIN"] == "true" and "PUBLISH_TOOLCHAIN" not in job["variables"]


def test_the_toolchain_job_publishes_every_platform_from_every_pipeline_while_switched_on():
    rules = _toolchain_job()["rules"]
    (published,) = [rule for rule in rules if rule.get("when") == "on_success"]
    assert published["if"].startswith('$PUBLISH_TOOLCHAIN == "true" && $CI_PIPELINE_SOURCE =~ /^(push|')
    assert "|web)$/" in published["if"]
    # A platform that fails, such as one whose system compiler Spack cannot use yet, does not fail the pipeline.
    assert published["allow_failure"] is True
    # Before the rule for a pipeline run by hand, which would otherwise make it wait for a click.
    by_hand = next(rule for rule in rules if rule.get("when") == "manual" and '"web"' in rule["if"])
    assert rules.index(published) < rules.index(by_hand)


def test_the_rocky10_build_job_installs_with_the_jobs_the_runner_allows():
    job = yaml.safe_load((Path(__file__).parents[2] / ".gitlab-ci.yml").read_text(encoding="utf-8"))["build:rocky10"]
    (install,) = [step for step in _steps(job) if step.startswith('status=0; spack -e "$ENVIRONMENT" install')]
    # Spack takes 16 jobs whatever the runner has.
    assert '--jobs "$(python -c \'import seanerstack.jobs; print(seanerstack.jobs.default_jobs())\')"' in install
    assert install.endswith("|| status=$?")


def test_a_merge_request_offers_the_toolchain_job_only_by_hand():
    rules = _toolchain_job()["rules"]
    (published,) = [rule for rule in rules if rule.get("when") == "on_success"]
    assert "merge_request_event" not in published["if"]
    (asked,) = [rule for rule in rules if "merge_request_event" in rule["if"]]
    assert (asked["when"], asked["allow_failure"]) == ("manual", True)
    assert asked["if"] == '$PUBLISH_TOOLCHAIN == "true" && $CI_PIPELINE_SOURCE == "merge_request_event"'


def test_no_job_passes_credentials_of_a_resource_in_variables():
    # Every job writes the job token to one secrets file, whose credential names cover every resource.
    ci = yaml.safe_load((Path(__file__).parents[2] / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    for name, job in ci.items():
        variables = job.get("variables", {}) if isinstance(job, dict) else {}
        assert not [key for key in variables if key.startswith("SEANERSTACK_RESOURCE_")], name


def test_the_secrets_file_holds_the_keys_of_the_public_caches_where_the_pipeline_has_them():
    ci = yaml.safe_load((Path(__file__).parents[2] / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    steps = ci[".job-token-secrets"]
    (keys,) = [step for step in steps if "juphoria-s3" in step]
    # Protected variables, which other pipelines lack: the file then holds only the job token.
    assert keys.startswith('[ -z "${JUPHORIA_S3_ACCESS_KEY:-}" ] || cat >> /tmp/secrets.toml <<EOF')
    assert "[credentials.juphoria-s3]" in keys
    assert 'access_key_id = { __keyloom__ = "secret", value = "$JUPHORIA_S3_ACCESS_KEY" }' in keys
    assert 'secret_access_key = { __keyloom__ = "secret", value = "$JUPHORIA_S3_SECRET_KEY" }' in keys
    assert steps.index(keys) < steps.index("keyloom encrypt /tmp/secrets.toml --password-file /tmp/vault-password")


def test_the_toolchain_job_passes_the_job_token_in_a_secrets_file():
    job = _toolchain_job()
    before = []
    for step in job["before_script"]:
        before += step if isinstance(step, list) else [step]
    assert "keyloom encrypt /tmp/secrets.toml --password-file /tmp/vault-password" in before
    for command in ("buildcache prepare", "buildcache explain"):
        (step,) = [step for step in job["script"] if command in step]
        assert "--secrets-file /tmp/secrets.toml --secrets-password-file /tmp/vault-password" in " ".join(step.split()), command
