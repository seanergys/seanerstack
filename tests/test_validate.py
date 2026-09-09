# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import subprocess

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


def test_spack_validation_reaches_spack(tmp_path, monkeypatch):
    # `_validate_with_spack` copies each environment to a temporary directory
    # before concretizing it. A missing `shutil` import made that raise
    # NameError, so `validate --spack` failed before running Spack at all.
    import seanstack.validate as validate_module

    environments = tmp_path / "environments"
    (environments / "demo-dev").mkdir(parents=True)
    (environments / "demo-dev" / "spack.yaml").write_text(
        "spack:\n  specs:\n  - demo\n", encoding="utf-8"
    )

    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(validate_module.subprocess, "run", fake_run)

    findings = validate_module._validate_with_spack(environments, ["spack"], None)

    assert calls, "Spack was never invoked"
    assert all(finding.level == "ok" for finding in findings), findings
