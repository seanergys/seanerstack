# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import yaml

from seanerstack.config import load_config


def test_the_nightly_toolchain_job_builds_every_shipped_platform():
    ci = yaml.safe_load((Path(__file__).parents[2] / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    (matrix,) = ci["toolchain"]["parallel"]["matrix"]
    assert matrix["PLATFORM"] == list(load_config().toolchain.platforms)
