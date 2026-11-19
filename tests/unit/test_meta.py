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
    assert set(dependencies) <= recipes - {"seanergys-meta"}


def test_each_shipped_lockfile_is_the_compiler_of_the_toolchain_for_a_platform():
    import json

    import seanerstack.bootstrap
    import seanerstack.config

    toolchain = seanerstack.config.load_config().toolchain
    systems = {platform.operating_system for platform in toolchain.platforms.values()}
    lockfiles = sorted((seanerstack.paths.share_path() / "toolchain").glob("*/spack.lock"))
    for path in lockfiles:
        assert path.parent.name in systems
        assert seanerstack.paths.toolchain_lockfile(path.parent.name) == path
        # A lockfile for another compiler would be ignored, and every machine would concretize.
        assert seanerstack.bootstrap.lockfile_for(path, toolchain.compiler) == path
        lock = json.loads(path.read_text(encoding="utf-8"))
        (root,) = lock["roots"]
        compiler = lock["concrete_specs"][root["hash"]]
        assert compiler["arch"]["platform_os"] == path.parent.name
        assert compiler["arch"]["target"] == toolchain.target
        assert "external" not in compiler
    assert seanerstack.paths.toolchain_lockfile("no-such-system") is None


def test_the_rocky10_build_job_builds_seanergys_meta():
    ci = yaml.safe_load((pathlib.Path(__file__).parents[2] / ".gitlab-ci.yml").read_text(encoding="utf-8"))
    assert 'spack -e "$ENVIRONMENT" add seanergys-meta' in ci["build:rocky10"]["script"]
