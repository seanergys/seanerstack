# SPDX-License-Identifier: Apache-2.0
"""A compiler already installed outside Spack is used as it is, and never built."""
import json
from pathlib import Path
import subprocess

import pytest

import seanerstack.bootstrap as bootstrap_module
import seanerstack.cli as cli
from seanerstack.bootstrap import BootstrapResult


COMMAND = ["/opt/spack/bin/spack", "-C", "/state/spack/config"]
ENV = {"SPACK_DISABLE_LOCAL_CONFIG": "true"}


def _node(name, version, *, hash, external=None, dependencies=()):
    node = {"name": name, "version": version, "hash": hash, "dependencies": list(dependencies)}
    if external is not None:
        node["external"] = {"path": external, "module": None}
    return node


def _spec(*nodes):
    return json.dumps({"spec": {"_meta": {"version": 5}, "nodes": list(nodes)}})


def _compiled_by(compiler_node):
    """The spec of zlib, compiled by the given compiler node."""
    zlib = _node(
        "zlib", "1.3.2", hash="zlib001",
        dependencies=[
            {"name": compiler_node["name"], "hash": compiler_node["hash"],
             "parameters": {"deptypes": ["build"], "virtuals": ["c", "cxx"]}},
            {"name": "glibc", "hash": "glibc01", "parameters": {"deptypes": ["link"], "virtuals": ["libc"]}},
        ],
    )
    return _spec(zlib, compiler_node, _node("glibc", "2.43", hash="glibc01", external="/usr"))


def _fake_spack(monkeypatch, *, compiler_spec, probe_spec=None):
    """Stand in for spack: `spec --json gcc@…` gives compiler_spec, any other spec probe_spec."""
    calls: list[list[str]] = []

    def fake_run(args, *, check=True, env=None, timeout=None):
        calls.append(args)
        if args[-3:-1] == ["spec", "--json"]:
            text = compiler_spec if args[-1].startswith("gcc") else probe_spec
            return subprocess.CompletedProcess(args, 0, text, "")
        return subprocess.CompletedProcess(args, 0, "", "")

    def fake_run_streaming(args, *, env=None):
        calls.append(args)

    monkeypatch.setattr(bootstrap_module, "_run", fake_run)
    monkeypatch.setattr(bootstrap_module, "_run_streaming", fake_run_streaming)
    return calls


def _external_gcc(prefix, version="16.1.0"):
    return _node("gcc", version, hash="gcc0001", external=str(prefix))


def test_an_external_compiler_is_registered_and_required_without_a_build(monkeypatch, tmp_path: Path):
    gcc = _external_gcc(tmp_path)
    calls = _fake_spack(monkeypatch, compiler_spec=_spec(gcc), probe_spec=_compiled_by(gcc))

    result = bootstrap_module.bootstrap(
        "gcc@16", command=COMMAND, env=ENV, external=str(tmp_path)
    )

    assert result.external == str(tmp_path)
    assert result.registered is True
    assert result.installed is False
    assert result.probe_ok is True
    assert not any("install" in call for call in calls)
    assert [*COMMAND, "compiler", "find"] not in calls
    assert [*COMMAND, "compiler", "find", str(tmp_path)] in calls
    for language in ("c", "cxx", "fortran"):
        assert [*COMMAND, "config", "add", f"packages:{language}:require:gcc@16"] in calls


def test_an_external_compiler_is_checked_before_anything_requires_it(monkeypatch, tmp_path: Path):
    gcc = _external_gcc(tmp_path)
    calls = _fake_spack(monkeypatch, compiler_spec=_spec(gcc), probe_spec=_compiled_by(gcc))

    bootstrap_module.bootstrap("gcc@16", languages=("c",), command=COMMAND, env=ENV, external=str(tmp_path))

    register = calls.index([*COMMAND, "compiler", "find", str(tmp_path)])
    check = calls.index([*COMMAND, "spec", "--json", "gcc@16"])
    require = calls.index([*COMMAND, "config", "add", "packages:c:require:gcc@16"])
    assert register < check < require


def test_a_compiler_spec_spack_would_build_is_refused(monkeypatch, tmp_path: Path):
    # With no gcc@16 in the prefix, Spack plans to build gcc@16 from source;
    # requiring it would start that build on the next install.
    calls = _fake_spack(monkeypatch, compiler_spec=_spec(_node("gcc", "16.2.0", hash="gcc0002")))

    with pytest.raises(RuntimeError, match=r"gcc@16\.2\.0 built from source"):
        bootstrap_module.bootstrap("gcc@16", command=COMMAND, env=ENV, external=str(tmp_path))

    assert not any(call[len(COMMAND):len(COMMAND) + 2] == ["config", "add"] for call in calls)


def test_a_compiler_spec_naming_another_external_is_refused(monkeypatch, tmp_path: Path):
    other = tmp_path / "other"
    other.mkdir()
    _fake_spack(monkeypatch, compiler_spec=_spec(_external_gcc(other)))

    with pytest.raises(RuntimeError, match=f"in {other}"):
        bootstrap_module.bootstrap("gcc@16", command=COMMAND, env=ENV, external=str(tmp_path))


def test_the_same_prefix_written_differently_is_accepted(monkeypatch, tmp_path: Path):
    gcc = _external_gcc(f"{tmp_path}/.")
    _fake_spack(monkeypatch, compiler_spec=_spec(gcc), probe_spec=_compiled_by(gcc))

    result = bootstrap_module.bootstrap("gcc@16", command=COMMAND, env=ENV, external=str(tmp_path))

    assert result.probe_ok is True


def test_a_probe_compiled_by_another_compiler_is_reported(monkeypatch, tmp_path: Path):
    built = _node("gcc", "16.2.0", hash="gcc0002")
    _fake_spack(monkeypatch, compiler_spec=_spec(_external_gcc(tmp_path)), probe_spec=_compiled_by(built))

    result = bootstrap_module.bootstrap("gcc@16", command=COMMAND, env=ENV, external=str(tmp_path))

    assert result.probe_ok is False


def test_spack_bootstrapping_itself_before_the_spec_is_skipped(monkeypatch, tmp_path: Path):
    # On a fresh state directory, Spack installs clingo first and says so on stdout.
    gcc = _external_gcc(tmp_path)
    noise = '==> Installing "clingo-bootstrap@=spack"\n==> Fetching from buildcache\n'
    _fake_spack(monkeypatch, compiler_spec=noise + _spec(gcc), probe_spec=noise + _compiled_by(gcc))

    result = bootstrap_module.bootstrap("gcc@16", command=COMMAND, env=ENV, external=str(tmp_path))

    assert result.probe_ok is True


def test_an_external_compiler_is_not_built_by_force(tmp_path: Path):
    with pytest.raises(ValueError, match="--force"):
        bootstrap_module.bootstrap("gcc@16", command=COMMAND, external=str(tmp_path), force=True)


def test_an_external_prefix_must_be_a_directory(tmp_path: Path):
    with pytest.raises(ValueError, match="not a directory"):
        bootstrap_module.bootstrap("gcc@16", command=COMMAND, external=str(tmp_path / "missing"))


def test_an_external_dry_run_changes_nothing(monkeypatch, tmp_path: Path):
    calls = _fake_spack(monkeypatch, compiler_spec=_spec(_external_gcc(tmp_path)))

    result = bootstrap_module.bootstrap(
        "gcc@16", command=COMMAND, env=ENV, external=str(tmp_path), dry_run=True
    )

    assert calls == []
    assert result.external == str(tmp_path)


@pytest.mark.parametrize("command", [["toolchain", "bootstrap"], ["init"]])
def test_the_commands_take_an_external_prefix(command):
    args = cli.build_parser().parse_args([*command, "gcc@16", "--external", "/usr"])

    assert (args.compiler, args.external) == ("gcc@16", "/usr")


def test_bootstrap_passes_the_external_prefix_on_and_names_it(monkeypatch, capsys):
    seen = {}

    def fake_bootstrap(compiler, **kwargs):
        seen.update(kwargs)
        return BootstrapResult(
            compiler=compiler, installed=False, registered=True, languages=("c",),
            probe="zlib", probe_ok=True, external=kwargs["external"],
        )

    monkeypatch.setattr(cli, "_spack_runtime", lambda args: (None, None, ["spack"], {}))
    monkeypatch.setattr(cli, "bootstrap", fake_bootstrap)
    args = cli.build_parser().parse_args(["toolchain", "bootstrap", "gcc@16", "--external", "/usr"])

    code = cli._run_bootstrap(args)

    assert code == 0
    assert seen["external"] == "/usr"
    assert "compiler: gcc@16 in /usr" in capsys.readouterr().out


@pytest.mark.parametrize("command", [["toolchain", "bootstrap"], ["init"]])
def test_without_an_external_prefix_the_compiler_is_built(monkeypatch, command):
    args = cli.build_parser().parse_args([*command, "gcc@15"])
    assert args.external is None

    calls = _fake_spack(monkeypatch, compiler_spec=_spec())
    built = "/state/spack/opt/gcc-15.3.0-abcdef"
    monkeypatch.setattr(
        bootstrap_module, "_compiler_prefix",
        lambda command, compiler, env: built if [*COMMAND, "install", "gcc@15"] in calls else None,
    )

    result = bootstrap_module.bootstrap("gcc@15", command=COMMAND, env=ENV, external=args.external)

    assert [*COMMAND, "install", "gcc@15"] in calls
    assert [*COMMAND, "compiler", "find", built] in calls
    assert result.external is None
