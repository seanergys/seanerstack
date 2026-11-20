# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

from seanerstack.recipe import parse_recipe


def test_parse_properdocs_recipe(monkeypatch):
    root = Path(__file__).parents[2]
    recipe = parse_recipe(root / "data/share/seanerstack/spack_repo/seanerstack/packages/properdocs/package.py")
    assert recipe.git == "https://github.com/ProperDocs/properdocs.git"
    versions = [directive for directive in recipe.directives if directive.name == "version"]
    assert any(directive.args[0] == "master" for directive in versions)
    assert any(directive.comment for directive in versions)


def test_recipe_exposes_url(tmp_path):
    path = tmp_path / "package.py"
    path.write_text('class Demo:\n    url = "https://example.invalid/demo-1.0.tar.gz"\n', encoding="utf-8")
    assert parse_recipe(path).url == "https://example.invalid/demo-1.0.tar.gz"


def test_every_compiled_recipe_declares_the_languages_it_is_compiled_from():
    # Without one, Spack gives the package no compiler: the compiler rule does not apply, and the build takes whatever
    # compiler is on PATH, without the include directories of its dependencies.
    import ast

    packages = Path(__file__).parents[2] / "data/share/seanerstack/spack_repo/seanerstack/packages"
    # rustc links with cc, so a Cargo package needs a compiler as well.
    compiled = {"AutotoolsPackage", "CargoPackage", "CMakePackage", "MakefilePackage", "MesonPackage"}
    missing = []
    for path in sorted(packages.glob("*/package.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bases = {base.id for node in tree.body if isinstance(node, ast.ClassDef) for base in node.bases if isinstance(base, ast.Name)}
        if not bases & compiled:
            continue
        languages = {
            directive.args[0] for directive in parse_recipe(path).directives
            if directive.name == "depends_on" and directive.args and directive.args[0] in ("c", "cxx", "fortran")
        }
        if not languages:
            missing.append(path.parent.name)
    assert missing == []
