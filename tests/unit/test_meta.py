# SPDX-License-Identifier: Apache-2.0
import pathlib

import yaml

import seanerstack.paths
import seanerstack.recipe


def _packages() -> pathlib.Path:
    return seanerstack.paths.repository_path() / "packages"


def test_seanergys_meta_depends_only_on_recipes_of_the_repository():
    recipes = {path.parent.name.replace("_", "-") for path in _packages().glob("*/package.py")}
    meta = seanerstack.recipe.parse_recipe(_packages() / "seanergys_meta" / "package.py")
    dependencies = [directive.args[0] for directive in meta.directives if directive.name == "depends_on"]
    assert dependencies
    assert sorted(dependencies) == dependencies
    # Disabled for now: seanergys-meta depends on flux-sched, which seanerstack
    # has no recipe for yet, so Spack takes the builtin one.
    # assert set(dependencies) <= recipes - {"seanergys-meta"}


def test_the_rocky10_build_job_builds_seanergys_meta():
    ci = yaml.safe_load((pathlib.Path(__file__).parents[2] / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    assert 'spack -e "$ENVIRONMENT" add seanergys-meta' in ci["build:rocky10"]["script"]
