# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from seanerstack.recipe import parse_recipe


def test_parse_properdocs_recipe(monkeypatch):
    root = Path(__file__).parents[1]
    recipe = parse_recipe(root / "data/share/seanerstack/spack_repo/seanerstack/packages/properdocs/package.py")
    assert recipe.git == "https://github.com/ProperDocs/properdocs.git"
    versions = [directive for directive in recipe.directives if directive.name == "version"]
    assert any(directive.args[0] == "master" for directive in versions)
    assert any(directive.comment for directive in versions)


def test_recipe_exposes_url(tmp_path):
    path = tmp_path / "package.py"
    path.write_text('class Demo:\n    url = "https://example.invalid/demo-1.0.tar.gz"\n', encoding="utf-8")
    assert parse_recipe(path).url == "https://example.invalid/demo-1.0.tar.gz"
