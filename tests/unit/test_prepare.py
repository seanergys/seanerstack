# SPDX-License-Identifier: Apache-2.0
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import threading

import pytest
import yaml

from seanerstack import cli as _cli
from seanerstack import prepare as _prepare
from seanerstack.cli import build_parser
from seanerstack.config import Config, Platform, Resource, Toolchain, load_config
from seanerstack.secrets import SecretStore


ROCKY10 = Platform(
    name="rocky10", image="rocky:10", operating_system="rocky10", package_manager="dnf", system_packages=("git", "gcc"),
)
ROCKY9 = Platform(
    name="rocky9", image="rocky:9", operating_system="rocky9", package_manager="dnf",
    system_packages=("git", "python3.12"), python="python3.12",
)
TOOLCHAIN = Toolchain(
    compiler="gcc@15",
    packages=("rust", "capnproto"),
    cache="target",
    target="x86_64_v3",
    platforms={"rocky10": ROCKY10, "rocky9": ROCKY9},
)
USER, TOKEN = "SEANERSTACK_RESOURCE_TARGET_USERNAME", "SEANERSTACK_RESOURCE_TARGET_PASSWORD"


def config(tmp_path: Path, **resources) -> Config:
    target = Resource(name="target", kind="spack-buildcache", url="oci://registry.example.org/group/cache", credentials="c", signed=False)
    return Config(path=tmp_path / "config.toml", resources={"target": target, **resources}, toolchain=TOOLCHAIN)


class Spack:
    """Records the Spack commands of a build."""

    def __init__(self, monkeypatch, system="rocky10"):
        self.calls = []
        self.targets = []
        self.system = system
        monkeypatch.setattr(_prepare, "require_target", lambda spack_config, target: self.targets.append((spack_config, target)))
        monkeypatch.setattr(_prepare, "check_push_access", lambda resource, env: None)
        monkeypatch.setattr(_prepare, "configure_buildcaches", self.configure)
        monkeypatch.setattr(_prepare, "bootstrap", lambda compiler, **kwargs: type("Result", (), {"probe_ok": True}))
        monkeypatch.setattr(_prepare.subprocess, "run", self.run)

    def configure(self, config, **kwargs):
        self.caches = config.resources

    def run(self, args, **kwargs):
        self.calls.append(args)
        stdout = {"arch": f"{self.system}\n", "find": "/aaa\n/bbb\n"}.get(args[1], "")
        return type("Process", (), {"stdout": stdout, "returncode": 0})


def run_here(tmp_path, platform="rocky10", **extra):
    return _prepare.prepare_here(
        config(tmp_path), SecretStore(None), platform=platform, command=["spack"], env={USER: "u", TOKEN: "t"},
        work=tmp_path / "toolchain", **extra,
    )


def test_prepare_builds_the_toolchain_and_then_pushes_it(monkeypatch, tmp_path):
    spack = Spack(monkeypatch)
    assert run_here(tmp_path, jobs=3) == 0
    assert yaml.safe_load((tmp_path / "toolchain/spack.yaml").read_text())["spack"]["specs"] == ["rust", "capnproto"]
    install = ["spack", "-e", str(tmp_path / "toolchain"), "install", "--jobs", "3"]
    (push,) = [call for call in spack.calls if call[1:3] == ["buildcache", "push"]]
    assert push[-3:] == ["target", "/aaa", "/bbb"]
    assert spack.calls.index(install) < spack.calls.index(push)


def test_prepare_requires_the_target_of_the_toolchain(monkeypatch, tmp_path):
    spack = Spack(monkeypatch)
    monkeypatch.setattr(_prepare, "pad_install_tree", lambda path, length, **kwargs: None)

    assert run_here(tmp_path, spack_config=tmp_path / "config") == 0

    assert spack.targets == [(tmp_path / "config", "x86_64_v3")]


def test_prepare_pushes_every_package_as_soon_as_it_is_built(monkeypatch, tmp_path):
    spack = Spack(monkeypatch)
    run_here(tmp_path)
    assert spack.caches["target"].autopush is True


def test_prepare_never_pushes_to_a_cache_it_only_reads(monkeypatch, tmp_path):
    spack = Spack(monkeypatch)
    source = Resource(name="source", kind="spack-buildcache", url="file:///cache", autopush=True, signed=False)
    _prepare.prepare_here(
        config(tmp_path, source=source), SecretStore(None), platform="rocky10", command=["spack"],
        env={USER: "u", TOKEN: "t"}, work=tmp_path / "toolchain",
    )
    assert spack.caches["source"].autopush is False


def test_prepare_refuses_another_operating_system(monkeypatch, tmp_path):
    spack = Spack(monkeypatch, system="rocky10")
    with pytest.raises(RuntimeError, match="this is rocky10, and binaries for rocky9"):
        run_here(tmp_path, platform="rocky9")
    assert not any("install" in call for call in spack.calls)


def test_prepare_names_the_platforms_it_knows(monkeypatch, tmp_path):
    Spack(monkeypatch)
    with pytest.raises(ValueError, match="unknown toolchain platform 'plan9'; known: rocky10, rocky9"):
        run_here(tmp_path, platform="plan9")


def test_prepare_needs_credentials_for_its_target(monkeypatch, tmp_path):
    Spack(monkeypatch)
    with pytest.raises(ValueError, match="no credentials for build cache 'target'"):
        _prepare.prepare_here(
            config(tmp_path), SecretStore(None), platform="rocky10", command=["spack"], env={}, work=tmp_path / "w",
        )


def test_jobs_follow_the_free_memory(monkeypatch):
    monkeypatch.setattr(_prepare.os, "cpu_count", lambda: 16)
    monkeypatch.setattr(_prepare, "_available_memory", lambda: 4 * _prepare.GIB)
    assert _prepare.default_jobs() == 2
    monkeypatch.setattr(_prepare, "_available_memory", lambda: _prepare.GIB)
    assert _prepare.default_jobs() == 1
    monkeypatch.setattr(_prepare, "_available_memory", lambda: None)
    assert _prepare.default_jobs() == 16


def test_the_container_reaches_prepare_through_a_checkout_or_a_release():
    arguments = dict(jobs=2, uid=1000, gid=1000, version="1.2.3")
    source = _prepare.container_script(ROCKY10, source=True, **arguments)
    assert "pip install --quiet /opt/seanerstack-input/source" in source
    assert "buildcache prepare --no-container --platform rocky10 --jobs 2" in source
    assert "dnf install -y --setopt=install_weak_deps=False git gcc" in source
    assert "python3 -m venv /opt/seanerstack" in source
    release = _prepare.container_script(ROCKY10, source=False, **arguments)
    assert "pip install --quiet seanerstack==1.2.3" in release


def test_the_container_uses_the_python_of_its_platform():
    script = _prepare.container_script(ROCKY9, jobs=1, source=False, uid=0, gid=0, version="1")
    assert "python3.12 -m venv /opt/seanerstack" in script


def test_the_container_runs_spack_with_the_python_of_its_platform():
    script = _prepare.container_script(ROCKY9, jobs=1, source=False, uid=0, gid=0, version="1").splitlines()
    export = script.index('export SPACK_PYTHON="$(command -v python3.12)"')
    assert export < next(index for index, line in enumerate(script) if "buildcache prepare" in line)


def test_fedora_45_takes_a_python_that_spack_has_a_clingo_binary_for():
    fedora45 = load_config().toolchain.platforms["fedora45"]
    assert fedora45.python == "python3.14"
    assert "python3.14" in fedora45.system_packages


def test_the_container_state_is_where_the_binaries_of_the_caches_relocate_to():
    assert _prepare.CONTAINER_STATE == "/opt/seanergys/state"


def test_no_token_is_on_the_command_line_of_the_container(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(_prepare, "check_push_access", lambda resource, env: None)
    monkeypatch.setattr(_prepare, "_container_runtime", lambda: "docker")
    monkeypatch.setattr(_prepare, "_available_memory", lambda: 8 * _prepare.GIB)
    monkeypatch.setattr(_prepare, "_stream", lambda args, env: calls.append((args, env)))
    monkeypatch.setattr(_prepare.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(_prepare, "_session", lambda *a: ({"target": config(tmp_path).resources["target"]}, {TOKEN: "secret"}))
    (tmp_path / "config.toml").write_text("", encoding="utf-8")
    _prepare.prepare_in_container(config(tmp_path), SecretStore(None), platform="rocky9", state_dir=tmp_path, jobs=2)
    argv, env = calls[0]
    assert "secret" not in " ".join(argv)
    assert env[TOKEN] == "secret"
    assert argv[argv.index("-e") + 1] == TOKEN
    assert argv[argv.index("--memory") + 1] == argv[argv.index("--memory-swap") + 1] == str(int(8 * _prepare.GIB * 0.85))
    assert (tmp_path / "buildcache-prepare/rocky9").is_dir()
    assert "rocky:9" in argv


def test_prepare_needs_a_container_runtime(monkeypatch):
    monkeypatch.setattr(_prepare.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="neither docker nor podman"):
        _prepare._container_runtime()


def test_the_shipped_toolchain_applies_to_a_config_without_one(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[toolchain]\ncache = "elsewhere"\n', encoding="utf-8")
    toolchain = load_config(path).toolchain
    assert toolchain.cache == "elsewhere"
    assert toolchain.compiler == "gcc@15"
    assert "rust" in toolchain.packages and "capnproto" in toolchain.packages
    assert "rocky10" in toolchain.platforms


def test_a_config_changes_one_platform_and_keeps_the_others(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[toolchain.platforms.rocky10]\nimage = "mirror.example.org/rocky:10"\n'
        'operating_system = "rocky10"\npackage_manager = "dnf"\n',
        encoding="utf-8",
    )
    platforms = load_config(path).toolchain.platforms
    assert platforms["rocky10"].image == "mirror.example.org/rocky:10"
    assert "rocky9" in platforms


def test_a_platform_adds_to_the_packages_of_its_package_manager(tmp_path):
    rocky9 = load_config().toolchain.platforms["rocky9"]
    assert rocky9.python == "python3.12"
    assert "git" in rocky9.system_packages and "python3.12" in rocky9.system_packages


def test_a_platform_needs_a_known_package_manager(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[toolchain.platforms.solaris]\nimage = "solaris"\noperating_system = "solaris11"\npackage_manager = "pkg"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="toolchain.platforms.solaris: package_manager must be one of"):
        load_config(path)


def test_the_toolchain_cache_has_to_be_a_build_cache(tmp_path):
    git = Resource(name="target", kind="git", url="https://example.org/")
    with pytest.raises(ValueError, match="not a spack-buildcache"):
        _prepare._toolchain(replace(config(tmp_path), resources={"target": git}))


def test_prepare_parses():
    args = build_parser().parse_args(
        ["--config-file", "c", "--secrets-file", "s", "buildcache", "prepare", "--platform", "rocky9", "--jobs", "2", "--no-container"]
    )
    assert (args.platform, args.jobs, args.no_container) == ("rocky9", 2, True)


def test_prepare_needs_a_platform():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["buildcache", "prepare"])


class Registry(BaseHTTPRequestHandler):
    """A registry with token authentication, in which only one token may write."""

    uploads, deleted = [], []
    writable = True

    def log_message(self, *args):
        pass

    def answer(self, code, headers=None, body=b""):
        self.send_response(code)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.answer(200, body=json.dumps({"token": "t"}).encode())

    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer t":
            realm = f"http://127.0.0.1:{self.server.server_port}/token"
            challenge = f'Bearer realm="{realm}",service="registry",scope="repository:group/cache:pull,push"'
            self.answer(401, {"WWW-Authenticate": challenge})
        elif self.writable:
            self.uploads.append(self.path)
            self.answer(202, {"Location": "/v2/group/cache/blobs/uploads/one"})
        else:
            self.answer(403)

    def do_DELETE(self):
        self.deleted.append(self.path)
        self.answer(204)


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(Registry, "uploads", [])
    monkeypatch.setattr(Registry, "deleted", [])
    server = HTTPServer(("127.0.0.1", 0), Registry)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield Resource(name="target", kind="spack-buildcache", url=f"oci+http://127.0.0.1:{server.server_port}/group/cache", credentials="c", signed=False)
    server.shutdown()


def test_push_access_starts_an_upload_and_abandons_it(registry):
    _prepare.check_push_access(registry, {USER: "u", TOKEN: "t"})
    assert Registry.uploads == ["/v2/group/cache/blobs/uploads/"]
    assert Registry.deleted == ["/v2/group/cache/blobs/uploads/one"]


def test_a_token_that_may_only_read_fails_before_the_build(registry, monkeypatch):
    monkeypatch.setattr(Registry, "writable", False)
    with pytest.raises(RuntimeError, match="write_registry"):
        _prepare.check_push_access(registry, {USER: "u", TOKEN: "t"})


def run_cli(monkeypatch, tmp_path, *argv):
    built = []
    monkeypatch.setattr(_cli, "_runtime", lambda args: (config(tmp_path), SecretStore(None)))
    monkeypatch.setattr(_cli, "prepare_in_container", lambda config, secrets, *, platform, **kwargs: built.append(platform))
    return _cli._run_buildcache(build_parser().parse_args(["buildcache", "prepare", *argv])), built


def test_all_builds_every_platform_one_after_the_other(monkeypatch, tmp_path):
    assert run_cli(monkeypatch, tmp_path, "--platform", "all") == (0, ["rocky10", "rocky9"])


def test_all_needs_a_container(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="name it with --platform"):
        run_cli(monkeypatch, tmp_path, "--platform", "all", "--no-container")


@pytest.mark.parametrize(
    ("manager", "command"),
    [
        ("dnf", "dnf install -y --setopt=install_weak_deps=False git gcc"),
        ("apt", "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends git gcc"),
        ("pacman", "pacman -Syu --noconfirm --needed git gcc"),
    ],
)
def test_each_package_manager_installs_the_system_packages(manager, command):
    assert _prepare.install_command(replace(ROCKY10, package_manager=manager)) == command


def test_the_container_names_its_system_as_an_installed_one_does():
    # The archlinux image has its own /etc/os-release, whose version is the image date.
    script = _prepare.container_script(ROCKY10, jobs=1, source=False, uid=0, gid=0, version="1")
    link = "ln -sf ../usr/lib/os-release /etc/os-release"
    assert script.index(link) < script.index("buildcache prepare")


def test_the_shipped_platforms():
    platforms = load_config().toolchain.platforms
    assert set(platforms) == {
        "rocky10", "rocky9", "fedora45", "fedora44", "debian13", "debian14", "ubuntu26.04", "ubuntu24.04", "arch",
    }
    assert {platform.package_manager for platform in platforms.values()} == {"dnf", "apt", "pacman"}


def test_the_container_gets_its_input_by_copy_not_by_mount(monkeypatch, tmp_path):
    calls, removed, staged = [], [], {}

    def stream(args, env):
        calls.append(args)
        if args[1] == "cp":
            stage = Path(args[2])  # pathlib drops the trailing "/."
            staged.update({str(path.relative_to(stage)): path.is_file() for path in stage.rglob("*")})

    monkeypatch.setattr(_prepare, "check_push_access", lambda resource, env: None)
    monkeypatch.setattr(_prepare, "_container_runtime", lambda: "docker")
    monkeypatch.setattr(_prepare, "_available_memory", lambda: None)
    monkeypatch.setattr(_prepare, "_stream", stream)
    monkeypatch.setattr(_prepare.subprocess, "run", lambda args, **kwargs: removed.append(args))
    monkeypatch.setattr(_prepare, "_session", lambda *a: ({"target": config(tmp_path).resources["target"]}, {}))
    (tmp_path / "config.toml").write_text("[toolchain]\n", encoding="utf-8")
    _prepare.prepare_in_container(config(tmp_path), SecretStore(None), platform="rocky10", state_dir=tmp_path, jobs=1)

    create, copy, start = calls
    assert create[:2] == ["docker", "create"]
    mounts = [create[index + 1] for index, value in enumerate(create) if value == "-v"]
    assert mounts == [f"{tmp_path.resolve()}/buildcache-prepare/rocky10:/opt/seanergys/state"]
    name = create[create.index("--name") + 1]
    assert copy[3] == f"{name}:/opt/seanerstack-input"
    assert staged["config.toml"] is True
    assert staged["source/pyproject.toml"] is True
    assert staged["source/src/seanerstack/prepare.py"] is True
    assert not any("__pycache__" in path for path in staged)
    assert start == ["docker", "start", "--attach", name]
    assert removed == [["docker", "rm", "--force", name]]


def test_credentials_from_the_environment_reach_the_container(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(_prepare, "check_push_access", lambda resource, env: None)
    monkeypatch.setattr(_prepare, "_container_runtime", lambda: "docker")
    monkeypatch.setattr(_prepare, "_available_memory", lambda: None)
    monkeypatch.setattr(_prepare, "_stream", lambda args, env: calls.append(args))
    monkeypatch.setattr(_prepare.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setenv(USER, "gitlab-ci-token")
    monkeypatch.setenv(TOKEN, "job-token")
    (tmp_path / "config.toml").write_text("", encoding="utf-8")
    _prepare.prepare_in_container(config(tmp_path), SecretStore(None), platform="rocky10", state_dir=tmp_path, jobs=1)
    create = calls[0]
    forwarded = [create[index + 1] for index, value in enumerate(create) if value == "-e"]
    assert forwarded == [USER, TOKEN]
    assert "job-token" not in " ".join(create)



def test_prepare_always_updates_the_index_after_the_push(monkeypatch, tmp_path):
    # Autopush has pushed everything already, and a push that skips every spec
    # leaves the index of an OCI cache as it was.
    spack = Spack(monkeypatch)
    run_here(tmp_path)
    (push,) = [call for call in spack.calls if call[1:3] == ["buildcache", "push"]]
    assert "--update-index" not in push
    # Spack's own update-index, or Seanerstack's script run by `spack python`.
    (update,) = [call for call in spack.calls if call[-1] == "target" and ("update-index" in call or call[1] == "python")]
    assert spack.calls.index(push) < spack.calls.index(update)


def test_prepare_pushes_and_indexes_the_compiler_before_it_is_probed(monkeypatch, tmp_path):
    spack = Spack(monkeypatch)

    def bootstrap(compiler, *, installed_compiler, **kwargs):
        spack.calls.append(["spack", "installed the compiler"])
        installed_compiler()
        spack.calls.append(["spack", "probe"])
        return type("Result", (), {"probe_ok": True})

    monkeypatch.setattr(_prepare, "bootstrap", bootstrap)
    run_here(tmp_path)

    steps = [
        "push" if call[1:3] == ["buildcache", "push"]
        else "index" if call[-1] == "target" and ("update-index" in call or call[1] == "python")
        else call[1] if call[1] in ("installed the compiler", "probe") else "install" if call[-3:-2] == ["install"] else None
        for call in spack.calls
    ]
    assert [step for step in steps if step] == ["installed the compiler", "push", "index", "probe", "install", "push", "index"]


def test_a_probe_that_fails_keeps_the_compiler_in_the_cache(monkeypatch, tmp_path):
    spack = Spack(monkeypatch)

    def bootstrap(compiler, *, installed_compiler, **kwargs):
        installed_compiler()
        raise RuntimeError("Spack did not concretize compiler probe")

    monkeypatch.setattr(_prepare, "bootstrap", bootstrap)
    with pytest.raises(RuntimeError, match="did not concretize"):
        run_here(tmp_path)
    assert [call[-3:] for call in spack.calls if call[1:3] == ["buildcache", "push"]] == [["target", "/aaa", "/bbb"]]


def test_prepare_names_the_probe_and_the_compiler_that_spack_does_not_use(monkeypatch, tmp_path):
    Spack(monkeypatch)
    result = type("Result", (), {"probe_ok": False, "probe": "zlib", "hash": "abcdefabcdef"})
    monkeypatch.setattr(_prepare, "bootstrap", lambda compiler, **kwargs: result)
    with pytest.raises(RuntimeError, match="Spack does not use gcc@15: the probe zlib is not compiled by the installed compiler /abcdefa"):
        run_here(tmp_path)


def test_prepare_gives_the_probe_the_time_it_was_given(monkeypatch, tmp_path):
    Spack(monkeypatch)
    given = []
    monkeypatch.setattr(_prepare, "bootstrap", lambda compiler, **kwargs: given.append(kwargs["probe_timeout"]) or type("Result", (), {"probe_ok": True}))

    run_here(tmp_path)
    run_here(tmp_path, probe_timeout=900)
    run_here(tmp_path, probe_timeout=None)

    assert given == [300, 900, None]


def test_prepare_takes_a_probe_timeout_and_waits_indefinitely_for_zero(monkeypatch, tmp_path):
    arguments = ["buildcache", "prepare", "--platform", "rocky10"]
    assert build_parser().parse_args(arguments).probe_timeout == 300
    assert build_parser().parse_args([*arguments, "--probe-timeout", "0"]).probe_timeout == 0


def test_the_container_builds_with_the_probe_timeout_it_was_given():
    script = lambda **extra: _prepare.container_script(ROCKY10, jobs=1, source=False, uid=0, gid=0, version="1", **extra)
    assert "--probe-timeout" not in script()
    assert "--platform rocky10 --jobs 1 --probe-timeout 900" in script(probe_timeout=900)
    # 0 waits indefinitely, and is not the default.
    assert "--jobs 1 --padded-length 200 --probe-timeout 0" in script(padded_length=200, probe_timeout=0)


def test_prepare_installs_the_compiler_of_the_lockfile_of_the_platform(monkeypatch, tmp_path):
    Spack(monkeypatch)
    given = []
    monkeypatch.setattr(_prepare, "toolchain_lockfile", lambda system: tmp_path / f"{system}.lock")
    monkeypatch.setattr(_prepare, "bootstrap", lambda compiler, **kwargs: given.append(kwargs["lockfile"]) or type("Result", (), {"probe_ok": True}))

    run_here(tmp_path)
    # For a new lockfile, after the pinned Spack, the recipes or the compiler changed.
    run_here(tmp_path, concretize=True)

    assert given == [tmp_path / "rocky10.lock", None]


def test_prepare_hands_the_bootstrap_instance_to_bootstrap(monkeypatch, tmp_path):
    # Where the caches lack the compiler, prepare builds it, in two stages.
    Spack(monkeypatch)
    given = []
    monkeypatch.setattr(_prepare, "bootstrap", lambda compiler, **kwargs: given.append(kwargs) or type("Result", (), {"probe_ok": True}))
    instance = object()

    run_here(tmp_path, bootstrap_instance=instance)

    assert given[0]["bootstrap_instance"] is instance
    assert given[0].get("cache_only", False) is False


def test_the_container_concretizes_when_told_to():
    script = lambda **extra: _prepare.container_script(ROCKY10, jobs=1, source=False, uid=0, gid=0, version="1", **extra)
    assert "--concretize" not in script()
    assert script(concretize=True).splitlines()[-1].endswith("--platform rocky10 --jobs 1 --concretize")
    assert build_parser().parse_args(["buildcache", "prepare", "--platform", "rocky10", "--concretize"]).concretize is True


CONFIG_YAML = "config::\n  install_tree:\n    root: /state/spack/store\n  build_stage:\n  - /state/spack/stage\n"


def _state_config(tmp_path, text=CONFIG_YAML):
    (tmp_path / "config.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def test_padding_goes_below_the_install_root_and_keeps_the_override(monkeypatch, tmp_path):
    monkeypatch.setattr(_prepare, "_output", lambda args, env: "")

    _prepare.pad_install_tree(_state_config(tmp_path), 200, command=["spack"], env={})

    text = (tmp_path / "config.yaml").read_text()
    assert text.startswith("config::\n  install_tree:\n    root: /state/spack/store\n    padded_length: 200\n  build_stage:")
    # Again with the same length, and back to none.
    _prepare.pad_install_tree(tmp_path, 200, command=["spack"], env={})
    assert (tmp_path / "config.yaml").read_text() == text
    _prepare.pad_install_tree(tmp_path, 0, command=["spack"], env={})
    assert (tmp_path / "config.yaml").read_text() == CONFIG_YAML


def test_a_state_with_installations_keeps_its_padding(monkeypatch, tmp_path):
    monkeypatch.setattr(_prepare, "_output", lambda args, env: "/aaa\n/bbb\n")

    with pytest.raises(RuntimeError, match="holds installations with a padded length of 0, and cannot change to 200"):
        _prepare.pad_install_tree(_state_config(tmp_path), 200, command=["spack"], env={})
    assert (tmp_path / "config.yaml").read_text() == CONFIG_YAML
    # The same padding as before is no change, whatever is installed.
    padded = CONFIG_YAML.replace("store\n", "store\n    padded_length: 128\n")
    _prepare.pad_install_tree(_state_config(tmp_path, padded), 128, command=["spack"], env={})
    with pytest.raises(RuntimeError, match="padded length of 128, and cannot change to 0"):
        _prepare.pad_install_tree(tmp_path, 0, command=["spack"], env={})


def test_prepare_pads_before_anything_is_installed(monkeypatch, tmp_path):
    spack = Spack(monkeypatch)
    order = []
    monkeypatch.setattr(_prepare, "pad_install_tree", lambda path, length, **kwargs: order.append(("pad", path, length)))
    monkeypatch.setattr(_prepare, "bootstrap", lambda compiler, **kwargs: order.append("bootstrap") or type("Result", (), {"probe_ok": True}))

    assert run_here(tmp_path, padded_length=200, spack_config=tmp_path / "config") == 0

    assert order == [("pad", tmp_path / "config", 200), "bootstrap"]
    assert spack.calls


def test_the_container_builds_with_the_padding_it_was_given():
    plain = _prepare.container_script(ROCKY10, jobs=1, source=False, uid=0, gid=0, version="1")
    padded = _prepare.container_script(ROCKY10, jobs=1, source=False, uid=0, gid=0, version="1", padded_length=200)
    assert "--padded-length" not in plain
    assert "buildcache prepare --no-container --platform rocky10 --jobs 1 --padded-length 200" in padded


def test_prepare_takes_a_padded_length_and_pads_nothing_without_it():
    arguments = ["buildcache", "prepare", "--platform", "rocky10"]
    assert build_parser().parse_args(arguments).padded_length == 0
    assert build_parser().parse_args([*arguments, "--padded-length", "200"]).padded_length == 200


def test_prepare_builds_the_compiler_in_the_environment_next_to_the_toolchain(monkeypatch, tmp_path):
    Spack(monkeypatch)
    given = {}
    monkeypatch.setattr(_prepare, "pad_install_tree", lambda path, length, **kwargs: None)
    monkeypatch.setattr(_prepare, "bootstrap", lambda compiler, **kwargs: given.update(kwargs) or type("Result", (), {"probe_ok": True}))

    assert run_here(tmp_path, spack_config=tmp_path / "config") == 0

    assert given["environment"] == tmp_path / "compiler"
    assert given["spack_config"] == tmp_path / "config"
