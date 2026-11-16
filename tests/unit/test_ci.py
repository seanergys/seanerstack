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
