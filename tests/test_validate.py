# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from seanstack.validate import validate


def test_static_validation_needs_no_compiler_state(tmp_path):
    repo = tmp_path / "repo"
    package = repo / "packages" / "demo"
    package.mkdir(parents=True)
    (package / "package.py").write_text("class Demo:\n    pass\n", encoding="utf-8")

    envs = tmp_path / "environments"
    env = envs / "demo-dev"
    env.mkdir(parents=True)
    (env / "spack.yaml").write_text("spack:\n  specs:\n    - demo@develop\n", encoding="utf-8")

    findings = validate(repository=repo, environments=envs)
    assert all(finding.level != "error" for finding in findings)
    assert not any(finding.subject == "compiler" for finding in findings)
