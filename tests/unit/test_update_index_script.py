# SPDX-License-Identifier: Apache-2.0
"""The index rebuild that `spack python` runs, against a stand-in for Spack."""
import importlib.util
import sys
import types

import pytest

from seanerstack import buildcache


class Registry:
    """A registry whose tags change between two listings, and the Spack that indexes it."""

    def __init__(self, listings: list[list[str]], configs: dict):
        self.listings = list(listings)
        self.configs = configs
        self.indexed: list[str] = []

    def list_tags(self, image) -> list[str]:
        return self.listings.pop(0)

    def config_from_tag(self, image_and_tag):
        return self.configs[image_and_tag[1]]

    def from_dict(self, config):
        if config["spec"] == "unreadable":
            raise ValueError("a newer Spack wrote this")
        return config["spec"]

    def update_index(self, image, tmpdir, pool) -> None:
        # As Spack does: list again, fetch the config of every spec tag, read each.
        distribution = sys.modules["spack.binary_distribution"]
        tags = [tag for tag in distribution.list_tags(image) if distribution.tag_is_spec(tag)]
        configs = pool.map(distribution._oci_config_from_tag, ((image, tag) for tag in tags))
        self.indexed = [distribution.spack.spec.Spec.from_dict(config) for config in configs]


@pytest.fixture
def rebuild(monkeypatch, tmp_path):
    def run(registry: Registry) -> None:
        spack = types.ModuleType("spack")
        names = ("binary_distribution", "config", "error", "mirrors", "mirrors.mirror", "oci", "oci.oci", "spec", "stage")
        modules = {name: types.ModuleType(f"spack.{name}") for name in names}
        for name, module in modules.items():
            parent, _, child = name.rpartition(".")
            setattr(modules[parent] if parent else spack, child, module)
            monkeypatch.setitem(sys.modules, f"spack.{name}", module)
        monkeypatch.setitem(sys.modules, "spack", spack)

        distribution = modules["binary_distribution"]
        distribution.spack = spack
        distribution.tag_is_spec = lambda tag: tag.endswith(".spack")
        distribution.list_tags = registry.list_tags
        distribution._oci_config_from_tag = registry.config_from_tag
        distribution._oci_update_index = registry.update_index
        modules["oci.oci"].list_tags = registry.list_tags
        modules["oci.oci"].image_from_mirror = lambda mirror: "image"
        modules["mirrors.mirror"].MirrorCollection = lambda binary: {"registry": "mirror"}
        modules["spec"].Spec = types.SimpleNamespace(from_dict=registry.from_dict)
        modules["error"].SpackError = type("SpackError", (Exception,), {})
        modules["config"].CONFIG = object()
        modules["stage"].stage_root = lambda config: str(tmp_path)

        spec = importlib.util.spec_from_file_location("update_index_script", buildcache.UPDATE_INDEX_SCRIPT)
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        script.time.sleep = pauses.append
        assert script.main("registry") == 0

    run.pauses = pauses = []
    return run


def test_the_rebuild_indexes_a_binary_that_another_job_pushed_meanwhile(rebuild):
    configs = {"a.spack": {"spec": "a"}, "late.spack": {"spec": "late"}}
    registry = Registry([["a.spack", "index.spack.json"], ["a.spack", "index.spack.json", "late.spack"]], configs)

    rebuild(registry)

    assert registry.indexed == ["a", "late"]


def test_the_rebuild_leaves_out_what_it_cannot_read_also_when_pushed_meanwhile(rebuild, capsys):
    configs = {
        "a.spack": {"spec": "a"}, "old.spack": {"spec": "unreadable"},
        "late.spack": {"spec": "unreadable"}, "image.spack": None,
    }
    registry = Registry([["a.spack", "old.spack", "image.spack"], ["a.spack", "old.spack", "image.spack", "late.spack"]], configs)

    rebuild(registry)

    assert registry.indexed == ["a"]
    output = capsys.readouterr().out
    assert "indexed 1 specs of registry, left out 3" in output
    assert "left out late.spack: a newer Spack wrote this" in output
    assert "left out image.spack: not a spec" in output


class _SlowRegistry(Registry):
    """A registry that lets the first requests for a config time out."""

    def __init__(self, listings, configs, failures):
        super().__init__(listings, configs)
        self.failures = dict(failures)

    def config_from_tag(self, image_and_tag):
        tag = image_and_tag[1]
        if self.failures.get(tag, 0) > 0:
            self.failures[tag] -= 1
            raise TimeoutError("The read operation timed out")
        return super().config_from_tag(image_and_tag)


def test_the_rebuild_asks_again_for_a_config_that_timed_out(rebuild, capsys):
    configs = {"a.spack": {"spec": "a"}, "b.spack": {"spec": "b"}}
    registry = _SlowRegistry([["a.spack", "b.spack"], ["a.spack", "b.spack"]], configs, {"b.spack": 2})

    rebuild(registry)

    assert registry.indexed == ["a", "b"]
    # Later each time.
    assert rebuild.pauses == [2, 4]
    assert "b.spack: The read operation timed out; reading it again" in capsys.readouterr().out


def test_the_rebuild_stops_when_a_config_never_answers(rebuild):
    registry = _SlowRegistry([["a.spack"], ["a.spack"]], {"a.spack": {"spec": "a"}}, {"a.spack": 99})

    with pytest.raises(TimeoutError):
        rebuild(registry)

    assert rebuild.pauses == [2, 4, 8, 16]
