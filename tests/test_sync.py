# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import seanstack.sync as sync


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "spack_repo" / "seanstack"
    package = repo / "packages" / "demo"
    package.mkdir(parents=True)
    (package / "package.py").write_text(
        '''class Demo:\n    git = "https://example.invalid/demo.git"\n    version("develop", branch="main")\n    version("1.2.0", tag="v1.2.0")\n    version("1.1.0", tag="v1.1.0")\n''',
        encoding="utf-8",
    )
    return repo


def test_sync_infers_recipe_tag_convention(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    monkeypatch.setattr(
        sync,
        "read_remote_refs",
        lambda remote: sync.RemoteRefs(
            tags={"v1.3.0": "abc", "nightly": "def"},
            heads={"main": "123"},
        ),
    )

    result = sync.sync_package("demo", repository=repo)

    assert result.missing_versions == ("1.3.0",)
    text = (repo / "packages" / "demo" / "package.py").read_text()
    assert 'version("1.3.0", tag="v1.3.0", commit="abc")' in text


def test_sync_checks_branches_declared_by_recipe(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    monkeypatch.setattr(
        sync,
        "read_remote_refs",
        lambda remote: sync.RemoteRefs(tags={}, heads={}),
    )

    result = sync.sync_package("demo", repository=repo, check=True)
    assert result.missing_branches == ("main",)
