# SPDX-License-Identifier: Apache-2.0
from email.message import Message
import gzip
import hashlib
import io
from pathlib import Path

import pytest

import seanerstack.sync as sync
from seanerstack.recipe import parse_recipe


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "spack_repo" / "seanerstack"
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


ARCHIVE_URL = "https://example.invalid/demo/-/archive/v0.2.1/demo-v0.2.1.tar.gz"


def _archive_repo(tmp_path: Path, extra: str = "") -> Path:
    repo = tmp_path / "spack_repo" / "seanerstack"
    package = repo / "packages" / "demo"
    package.mkdir(parents=True)
    (package / "package.py").write_text(
        "class Demo:\n"
        f'    url = "{ARCHIVE_URL}"\n'
        '    git = "https://example.invalid/demo.git"\n'
        '    version("develop", branch="main")\n'
        '    version("0.2.1", sha256="aaa")\n'
        '    version("0.2", sha256="bbb")\n'
        f"{extra}",
        encoding="utf-8",
    )
    return repo


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, content_type: str):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type


TARBALL = gzip.compress(b"demo release")


def _refs(tags):
    return lambda remote: sync.RemoteRefs(tags={tag: "abc" for tag in tags}, heads={"main": "123"})


def test_sync_infers_tag_convention_from_archive_url(monkeypatch, tmp_path):
    repo = _archive_repo(tmp_path)
    monkeypatch.setattr(sync, "read_remote_refs", _refs(["v0.2", "v0.2.1", "v0.3.0", "demo-v0.4"]))

    result = sync.sync_package("demo", repository=repo, check=True)

    assert result.missing_versions == ("0.3.0",)


def test_sync_inserts_archive_release_with_sha256(monkeypatch, tmp_path):
    repo = _archive_repo(tmp_path)
    monkeypatch.setattr(sync, "read_remote_refs", _refs(["v0.2", "v0.2.1", "v0.3.0"]))
    requested = []

    def fake_urlopen(request):
        requested.append(request.full_url)
        return FakeResponse(TARBALL, "application/octet-stream")

    monkeypatch.setattr(sync, "_urlopen", fake_urlopen)

    result = sync.sync_package("demo", repository=repo)

    assert result.missing_versions == ("0.3.0",)
    assert requested == ["https://example.invalid/demo/-/archive/v0.3.0/demo-v0.3.0.tar.gz"]
    text = (repo / "packages" / "demo" / "package.py").read_text()
    assert f'    version("0.3.0", sha256="{hashlib.sha256(TARBALL).hexdigest()}")\n' in text
    assert "tag=" not in text
    assert text.index('"0.3.0"') < text.index('"0.2.1"')


def test_sync_rejects_html_sign_in_page(monkeypatch, tmp_path):
    repo = _archive_repo(tmp_path)
    recipe = repo / "packages" / "demo" / "package.py"
    before = recipe.read_text()
    monkeypatch.setattr(sync, "read_remote_refs", _refs(["v0.2.1", "v0.3.0"]))
    monkeypatch.setattr(
        sync,
        "_urlopen",
        lambda request: FakeResponse(b"<!DOCTYPE html><html>Sign in</html>", "text/html; charset=utf-8"),
    )

    with pytest.raises(ValueError, match="not a gzip archive"):
        sync.sync_package("demo", repository=repo)
    assert recipe.read_text() == before


def test_sync_check_does_not_download_archives(monkeypatch, tmp_path):
    repo = _archive_repo(tmp_path)
    monkeypatch.setattr(sync, "read_remote_refs", _refs(["v0.2.1", "v0.3.0"]))
    monkeypatch.setattr(sync, "_urlopen", lambda request: pytest.fail("check must not download"))

    assert sync.sync_package("demo", repository=repo, check=True).missing_versions == ("0.3.0",)


def test_sync_rejects_mixed_tag_and_sha256_releases(monkeypatch, tmp_path):
    repo = _archive_repo(tmp_path, extra='    version("0.1", tag="v0.1")\n')
    monkeypatch.setattr(sync, "read_remote_refs", _refs(["v0.1"]))

    with pytest.raises(ValueError, match="mixes tag= releases"):
        sync.sync_package("demo", repository=repo, check=True)


def test_archive_url_substitutes_whole_versions_only(tmp_path):
    repo = _archive_repo(tmp_path)
    recipe = parse_recipe(repo / "packages" / "demo" / "package.py")

    assert sync.archive_url(recipe, "1.0") == "https://example.invalid/demo/-/archive/v1.0/demo-v1.0.tar.gz"


def _branch_only_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "spack_repo" / "seanerstack"
    package = repo / "packages" / "demo"
    package.mkdir(parents=True)
    (package / "package.py").write_text(
        'class Demo:\n    git = "https://example.invalid/demo.git"\n    version("main", branch="main")\n',
        encoding="utf-8",
    )
    return repo


def test_a_recipe_without_releases_follows_its_branch_and_takes_no_tags(monkeypatch, tmp_path):
    repo = _branch_only_repo(tmp_path)
    before = (repo / "packages" / "demo" / "package.py").read_text()
    monkeypatch.setattr(sync, "read_remote_refs", lambda remote: sync.RemoteRefs(tags={"v0.2.1": "abc"}, heads={"main": "123"}))

    result = sync.sync_package("demo", repository=repo)

    assert (result.changed, result.missing_versions, result.missing_branches) == (False, (), ())
    assert (repo / "packages" / "demo" / "package.py").read_text() == before


def test_a_recipe_without_releases_still_reports_a_missing_branch(monkeypatch, tmp_path):
    repo = _branch_only_repo(tmp_path)
    monkeypatch.setattr(sync, "read_remote_refs", lambda remote: sync.RemoteRefs(tags={}, heads={"master": "123"}))

    result = sync.sync_package("demo", repository=repo, check=True)

    assert result.changed and result.missing_branches == ("main",)


def test_recipes_without_a_git_url_are_left_out_of_synchronizing_all(monkeypatch, tmp_path):
    repo = _repo(tmp_path)
    extended = repo / "packages" / "extended"
    extended.mkdir()
    (extended / "package.py").write_text(
        "from spack_repo.builtin.packages.extended.package import Extended as Builtin\n\n"
        "class Extended(Builtin):\n    get_full_repo = True\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sync, "read_remote_refs", lambda remote: sync.RemoteRefs(tags={}, heads={"main": "123"}))

    pypi = repo / "packages" / "from-pypi"
    pypi.mkdir()
    (pypi / "package.py").write_text(
        'class FromPypi:\n    pypi = "from-pypi/from-pypi-1.0.tar.gz"\n    version("1.0", sha256="abc")\n',
        encoding="utf-8",
    )

    results = sync.sync_many(["demo", "extended", "from-pypi"], repository=repo, check=True)

    assert [result.package for result in results] == ["demo"]
    for package in ("extended", "from-pypi"):
        with pytest.raises(ValueError, match="no git URL"):
            sync.sync_package(package, repository=repo)
