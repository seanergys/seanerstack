# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import importlib.metadata
import os
from pathlib import Path
import shlex
import subprocess
import sys

from .auth import spack_resource_environment
from .bootstrap import DEFAULT_LANGUAGES, DEFAULT_PROBE, DEFAULT_PROBE_TIMEOUT, bootstrap, install_packages, require_target, use_external_package
from .buildcache import buildcache_environment, buildcaches, check_buildcaches, configure_buildcaches, require_cache_access, update_index
from .config import Config, load_config
from .discovery import describe, detect_packages, find_compilers, load_detected, matching, registered_compilers, save_detected
from .paths import environments_path, repository_path, share_path
from .pins import SPACK_VERSION
from .prepare import pad_install_tree, prepare_here, prepare_in_container
from .secrets import SecretStore
from .isolation import (
    activation_script, deactivation_script, layout, prepare_isolation, read_record, recorded_find,
    resolve_real_spack, resolve_state_dir, spack_command, spack_env, store_credentials, write_record,
)
from .sync import package_paths, sync_many
from .validate import check_git_access, validate


def _add_secret_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config-file",
        type=Path,
        help="Seanerstack config.toml (default: installed share/seanerstack/config.toml)",
    )
    parser.add_argument(
        "--secrets-file",
        type=Path,
        help="keyloom-encrypted file containing credentials referenced by config.toml",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--secrets-password-file",
        type=Path,
        help="read the vault password from FILE instead of prompting",
    )
    source.add_argument(
        "--secrets-password-stdin",
        action="store_true",
        help="read the vault password from stdin instead of prompting",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seanerstack",
        description="Maintain and use the curated SEANERGYS Spack stack.",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"seanerstack {importlib.metadata.version('seanerstack')} (Spack {SPACK_VERSION.removeprefix('v')})",
    )
    _add_secret_options(parser)
    parser.add_argument("--state-dir", type=Path, help="private Seanerstack state directory (or SEANERSTACK_STATE_DIR; default: /opt/seanergys/state, which the binaries of the project build cache need)")
    parser.add_argument("--spack-executable", type=Path, help="Spack executable to use instead of the one Seanerstack installs in the state directory; it has to be the same version")
    subparsers = parser.add_subparsers(dest="command", required=True)

    package_parser = subparsers.add_parser("package", help="Maintain curated Spack packages.")
    package_sub = package_parser.add_subparsers(dest="package_command", required=True)
    update_parser = package_sub.add_parser(
        "update",
        help="Update Spack recipe versions from upstream Git refs.",
        description=(
            "Read each native package.py recipe, infer its release-tag convention "
            "from existing version(..., tag=...) directives, and add missing upstream releases."
        ),
    )
    update_parser.add_argument("package", nargs="?", help="package to update")
    update_parser.add_argument("--all", action="store_true", help="update every Seanerstack package")
    update_parser.add_argument("--check", action="store_true", help="report drift without changing files; return non-zero on drift")
    update_parser.add_argument("--dry-run", action="store_true", help="show what would change without changing files")

    toolchain_parser = subparsers.add_parser("toolchain", help="Prepare the SEANERGYS build toolchain.")
    toolchain_sub = toolchain_parser.add_subparsers(dest="toolchain_command", required=True)
    bootstrap_parser = toolchain_sub.add_parser(
        "bootstrap",
        help="Install the toolchain: its compiler, then its packages, such as rust.",
        description=(
            "Install the compiler of [toolchain] in config.toml and make it the compiler of every "
            "build in the state, then install the toolchain's packages with it, such as rust. Each "
            "comes from the project build cache where the cache holds it, so the hours that GCC and "
            "Rust take to build are spent once. Run init first: it registers the compilers and "
            "detects the packages that --source-compiler and --external choose from."
        ),
    )
    bootstrap_parser.add_argument(
        "packages", nargs="*", metavar="PACKAGE",
        help="the packages to install after the compiler (default: the packages of [toolchain], such as rust and capnproto)",
    )
    bootstrap_parser.add_argument("--compiler", metavar="SPEC", help="the compiler to build (default: the compiler of [toolchain], such as gcc@15)")
    bootstrap_parser.add_argument(
        "--source-compiler", metavar="SPEC",
        help="the compiler that builds it, one that init found, such as gcc@14 (default: Spack's choice)",
    )
    bootstrap_parser.add_argument("--target", help="the CPU target of every build (default: the target of [toolchain], such as x86_64_v3)")
    bootstrap_parser.add_argument("--os", metavar="NAME", help="fail unless this machine is NAME, as Spack names it, such as rocky10")
    bootstrap_parser.add_argument(
        "--language",
        action="append",
        choices=("c", "cxx", "fortran"),
        help="language provider to configure; repeat as needed (default: c, cxx, fortran)",
    )
    bootstrap_parser.add_argument("--probe", default=DEFAULT_PROBE, help=f"spec used to probe concretization (default: {DEFAULT_PROBE})")
    bootstrap_parser.add_argument("--probe-timeout", type=float, default=DEFAULT_PROBE_TIMEOUT, help=f"seconds to allow the probe before giving up (default: {DEFAULT_PROBE_TIMEOUT:g}); 0 waits indefinitely")
    bootstrap_parser.add_argument("--force", action="store_true", help="ask Spack to install the compiler even when it is already installed")
    bootstrap_parser.add_argument(
        "--external", action="append", metavar="SPEC",
        help="use what init found instead of building it: a compiler, such as gcc@16, or a package, "
        "such as rust; repeat as needed. Its hashes then match nothing in the project build cache",
    )
    bootstrap_parser.add_argument("--dry-run", action="store_true", help="show the intended operation without changing Spack configuration")

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate recipes, environments, resources, and optional online/Spack state.",
    )
    validate_parser.add_argument("--online", action="store_true", help="also compare recipe versions with upstream Git refs")
    validate_parser.add_argument("--access", action="store_true", help="also check that the repository of every recipe with a Git resource can be read")
    validate_parser.add_argument("--spack", action="store_true", dest="with_spack", help="also concretize copies of all environments with Spack")
    validate_parser.add_argument("--compiler", help="verify that this compiler is required for the selected languages")
    validate_parser.add_argument(
        "--language",
        action="append",
        choices=("c", "cxx", "fortran"),
        help="language requirement to validate; repeat as needed (default: c, cxx, fortran)",
    )

    paths_parser = subparsers.add_parser("paths", help="Print installed Seanerstack paths.")
    paths_sub = paths_parser.add_subparsers(dest="paths_command", required=True)
    paths_sub.add_parser("share", help="Print the installed Seanerstack share directory.")
    paths_sub.add_parser("repo", help="Print the native Seanerstack Spack repository path.")
    env_parser = paths_sub.add_parser("env", help="Print the path of a shipped Spack environment.")
    selector = env_parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--package", help="select the unique environment whose root specs contain PACKAGE")
    selector.add_argument("--environment", help="select an environment by directory name")

    cache_parser = subparsers.add_parser("buildcache", help="Configure and verify Spack binary build caches.")
    cache_sub = cache_parser.add_subparsers(dest="buildcache_command", required=True)
    explain_parser = cache_sub.add_parser(
        "explain",
        help="Explain why a spec is built instead of taken from the build caches.",
        description=(
            "Concretize SPEC as `spack install` would, and compare it with the specs of the same name "
            "and version in the configured build caches that are for this operating system. For each, print the nodes whose own fields "
            "differ, such as the CPU target, a variant, the package recipe or the install path of an "
            "external compiler; a node that differs only through a dependency is not repeated."
        ),
    )
    selection = explain_parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--match-target", action="store_const", const="target", dest="match",
        help="compare only with the cached specs for this operating system and this CPU target",
    )
    selection.add_argument(
        "--all", action="store_const", const="all", dest="match",
        help="compare with the cached specs for every operating system and target",
    )
    explain_parser.set_defaults(match="os")
    explain_parser.add_argument("spec", nargs="+", help="the spec, such as gcc@15.3.0 or rust")
    cache_sub.add_parser("configure", help="Install configured build-cache mirrors into the isolated Spack configuration.")
    cache_sub.add_parser("check", help="Check access to configured build caches using session or vault credentials.")
    update_index_parser = cache_sub.add_parser(
        "update-index",
        help="Rebuild the index of a build cache from the binaries it holds.",
        description=(
            "Rebuild the index of a build cache from the binaries it holds, so that Spack finds them. "
            "Binaries that the pinned Spack cannot read, such as those a newer Spack pushed, are left "
            "out and named, where `spack buildcache update-index` would stop. Needs write access."
        ),
    )
    update_index_parser.add_argument("cache", nargs="?", help="the build cache resource (default: the cache of [toolchain])")
    prepare_parser = cache_sub.add_parser(
        "prepare",
        help="Build the toolchain for a platform and push it to the build cache of [toolchain] in config.toml.",
        description=(
            "Build the compiler and the packages of [toolchain] in config.toml for one of its "
            "platforms, or all of them, and push them to its build cache. What a cache already "
            "holds is reused, not rebuilt. Needs write access to that cache, which is checked "
            "before anything is built. The build runs in the image of the platform, so docker "
            "or podman is enough on a desktop."
        ),
    )
    prepare_parser.add_argument(
        "--platform", required=True, metavar="NAME",
        help="a platform of [toolchain], such as rocky10, or all of them one after the other with 'all'",
    )
    prepare_parser.add_argument("--jobs", type=int, help="parallel jobs per package (default: what the free memory allows)")
    prepare_parser.add_argument("--no-container", action="store_true", help="build here, for a CI job that runs in the image of [toolchain]")
    prepare_parser.add_argument(
        "--padded-length", type=int, default=0, metavar="N",
        help="install below a prefix padded to N characters, so that the binaries of the cache install into any "
        "shorter path, such as a state directory of the user's choice (default: 0, no padding)",
    )
    prepare_parser.add_argument("--probe-timeout", type=float, default=DEFAULT_PROBE_TIMEOUT, help=f"seconds to allow the probe before giving up (default: {DEFAULT_PROBE_TIMEOUT:g}); 0 waits indefinitely")

    init_parser = subparsers.add_parser(
        "init",
        help="Set up the state directory once, and check access to every resource.",
        description=(
            "Set up the state directory, by default /opt/seanergys/state, so that no later "
            "command needs another option: the pinned Spack, the config.toml and the "
            "credentials of --secrets-file (stored readable only by you), the build caches, "
            "and the CPU target of [toolchain]. Then check that every build cache and Git "
            "resource can be read. Run it again to change any of these. It installs no "
            "compiler: `seanerstack toolchain bootstrap` does, once init has passed."
        ),
    )
    init_parser.add_argument(
        "--find", action="append", type=Path, metavar="PREFIX",
        help="also look for compilers and packages below PREFIX, an installation off PATH such as "
        "/opt/rh/gcc-toolset-15/root/usr; repeat as needed (default: what init was given before)",
    )

    init_parser.add_argument(
        "--padded-length", type=int, metavar="N",
        help="install below a prefix padded to N characters, for a state that builds a cache: its binaries then "
        "install into any shorter path. 0 removes the padding (default: what the state has)",
    )

    subparsers.add_parser("activate", help="Emit shell code that activates an isolated Seanerstack Spack session.")
    subparsers.add_parser("deactivate", help="Emit shell code that restores the shell state saved by activation.")

    return parser


def _runtime(args: argparse.Namespace) -> tuple[Config, SecretStore]:
    """The configuration and credentials: those given, or else what init recorded."""
    state_dir = resolve_state_dir(args.state_dir)
    record = read_record(state_dir)
    config = load_config(args.config_file or record["config_file"])
    if args.secrets_file is not None:
        secrets = SecretStore(
            args.secrets_file,
            password_file=args.secrets_password_file,
            password_stdin=args.secrets_password_stdin,
        )
    else:
        secrets = SecretStore.stored(layout(state_dir).credentials)
    return config, secrets


def _run_package_update(args: argparse.Namespace) -> int:
    config, secrets = _runtime(args)
    paths = package_paths()
    if args.all:
        packages = list(paths)
    elif args.package:
        packages = [args.package]
    else:
        raise ValueError("provide PACKAGE or --all")

    results = sync_many(
        packages,
        check=args.check,
        dry_run=args.dry_run,
        config=config,
        secrets=secrets,
    )
    drift = False
    for result in results:
        if not result.changed:
            print(f"{result.package}: up to date")
            continue
        drift = True
        changes = [*(f"version {version}" for version in result.missing_versions)]
        changes.extend(f"missing upstream branch {branch}" for branch in result.missing_branches)
        verb = "would add/report" if (args.check or args.dry_run) else "added/reported"
        print(f"{result.package}: {verb} " + ", ".join(changes))
    return 1 if args.check and drift else 0



def _spack_runtime(args: argparse.Namespace):
    state_dir = resolve_state_dir(args.state_dir)
    real_spack = resolve_real_spack(args.spack_executable or read_record(state_dir)["spack_executable"], state_dir)
    x = prepare_isolation(state_dir, real_spack)
    env = dict(__import__("os").environ)
    env.update(spack_env(x))
    return x, real_spack, spack_command(x, real_spack), env

def _probe_warning(result) -> str:
    if result.external:
        return f"warning: the probe is not compiled by the compiler in {result.external}"
    return f"warning: the probe is not compiled by the installed compiler /{(result.hash or '')[:7]}"


def _only(found: list, wanted: str, option: str, kind: str, among: list) -> object:
    """The one entry that `wanted` names, or an error that lists what there is."""
    if len(found) == 1:
        return found[0]
    listed = "\n".join(f"  {line}" for line in describe(among)) or "  none"
    problem = "matches more than one" if found else "matches none"
    raise ValueError(f"{option} {wanted} {problem} of the {kind} that init found; run init again to look again:\n{listed}")


def _run_bootstrap(args: argparse.Namespace) -> int:
    languages = tuple(args.language) if args.language else DEFAULT_LANGUAGES
    config, secrets = _runtime(args)
    toolchain = config.toolchain
    compiler = args.compiler or (toolchain.compiler if toolchain else None)
    packages = list(args.packages) if args.packages else list(toolchain.packages if toolchain else ())
    target = args.target or (toolchain.target if toolchain else None)
    x, _, command, env = _spack_runtime(args)
    # Without them Spack asks a private build cache anonymously, is refused,
    # and builds from source what the cache holds, saying only "no binary available".
    env = buildcache_environment(config, secrets, env)
    if not args.dry_run:
        require_cache_access(command, env)

    if args.os is not None:
        system = subprocess.run(
            [*command, "arch", "--operating-system"], check=True, capture_output=True, text=True, env=env
        ).stdout.strip()
        if system != args.os:
            raise ValueError(f"this machine is {system}, not {args.os}")

    compilers = registered_compilers(x)
    detected = load_detected(x)
    external_compiler = None
    external_packages = []
    for wanted in args.external or []:
        if matching(compilers, wanted):
            external_compiler = _only(matching(compilers, wanted), wanted, "--external", "compilers", compilers)
            continue
        candidates = matching(detected.get(wanted.partition("@")[0], []), wanted)
        everything = [item for items in detected.values() for item in items]
        if candidates:
            external_packages.append(_only(candidates, wanted, "--external", "packages", everything))
        else:
            _only([], wanted, "--external", "compilers and packages", compilers + everything)
    if external_compiler is not None and (args.compiler or args.source_compiler):
        raise ValueError("--external names the compiler to use, so --compiler and --source-compiler do not apply")
    source = None
    if args.source_compiler:
        source = _only(matching(compilers, args.source_compiler), args.source_compiler, "--source-compiler", "compilers", compilers).spec
    if external_compiler is not None:
        compiler = external_compiler.spec
    if compiler is None:
        raise ValueError(f"{config.path}: [toolchain] is missing; give --compiler")

    if target and not args.dry_run:
        require_target(command, target, env)
    result = bootstrap(
        compiler,
        languages=languages,
        probe=args.probe,
        command=command,
        env=env,
        force=args.force,
        dry_run=args.dry_run,
        probe_timeout=args.probe_timeout or None,
        external=external_compiler.prefix if external_compiler else None,
        source_compiler=source,
        environment=x.environments / "compiler",
        spack_config=x.config,
    )
    if args.dry_run:
        if result.external:
            print(f"would use the {result.compiler} in {result.external}, building nothing")
        else:
            print(f"would bootstrap {result.compiler}" + (f", built with {source}" if source else ""))
        print(f"would require it for: {', '.join(result.languages)}")
        print(f"would install: {', '.join(packages) or 'nothing more'}")
        return 0
    built = f" in {result.external}" if result.external else f", built with {source}" if source else ""
    print(f"compiler: {result.compiler}{built}")
    if result.external:
        print("used as: an external of this machine")
    else:
        print(f"used as: the installed package /{(result.hash or '')[:7]}")
    print(f"languages: {', '.join(result.languages)}")
    print(f"compiler probe ({result.probe}): {'ok' if result.probe_ok else _probe_warning(result)}")
    if not result.probe_ok:
        return 1

    for found in external_packages:
        use_external_package(command, found.name, found.prefix, env)
        print(f"package: {found.spec} (external, {found.prefix})")
    install_packages(command, [package for package in packages if package not in {found.name for found in external_packages}], env)

    externals = ([external_compiler] if external_compiler else []) + external_packages
    if externals:
        print()
        print(
            f"warning: {', '.join(found.spec for found in externals)} came from this machine, so the hashes "
            "of everything built with them match nothing in the project build cache. Keep what you build "
            "in a filesystem build cache to reuse it: see 'Use a filesystem build cache' in the docs."
        )
    return 0


def _run_init(args: argparse.Namespace) -> int:
    state_dir = resolve_state_dir(args.state_dir)
    record = read_record(state_dir)
    config_file = args.config_file or record["config_file"]
    config = load_config(config_file)
    x, real_spack, command, env = _spack_runtime(args)
    find = args.find if args.find is not None else recorded_find(state_dir)
    write_record(x, config_file=config_file, spack_executable=args.spack_executable or record["spack_executable"], find=find)
    padded_length = getattr(args, "padded_length", None)
    if padded_length is not None:
        pad_install_tree(x.config, padded_length, command=command, env=env)
    print(f"state: {x.state}")
    print(f"spack: {real_spack}")
    print(f"config: {config.path}")

    if args.secrets_file is not None:
        secrets = SecretStore(
            args.secrets_file,
            password_file=args.secrets_password_file,
            password_stdin=args.secrets_password_stdin,
        )
        stored = store_credentials(x, config, secrets)
        print(f"credentials: stored {', '.join(stored) if stored else 'none'} in {x.credentials}")
    else:
        secrets = SecretStore.stored(x.credentials)

    configure_buildcaches(config, command=command, env=env)
    print(f"build caches: {', '.join(cache.name for cache in buildcaches(config)) or 'none'}")
    if config.toolchain is not None:
        require_target(command, config.toolchain.target, env)
        print(f"target: {config.toolchain.target}")

    find_compilers(command, env, find)
    compilers = registered_compilers(x)
    detected = detect_packages(command, env, list(config.toolchain.packages) if config.toolchain else [], find)
    save_detected(x, detected)
    print("compilers found:")
    for line in describe(compilers) or ["none"]:
        print(f"  {line}")
    print("packages found:")
    for line in describe([item for items in detected.values() for item in items]) or ["none"]:
        print(f"  {line}")

    failed = False
    for kind, results in (
        ("buildcache", check_buildcaches(config, secrets, command=command, base_env=env)),
        ("git", check_git_access(config, secrets)),
    ):
        for name, ok, message in results:
            print(f"[{'OK' if ok else 'ERROR'}] {kind}:{name}: {message or 'accessible'}")
            failed |= not ok
    if failed:
        print()
        print("Fix the access above, for example with --secrets-file, and run init again.")
        return 1

    print()
    # The default state and one named by SEANERSTACK_STATE_DIR need no option.
    named = resolve_state_dir(None) == x.state
    activate = "seanerstack activate" if named else f"seanerstack --state-dir {shlex.quote(str(x.state))} activate"
    print("Setup complete. Use the Spack of this state in a shell with:")
    print(f'    eval "$({activate})"')
    print("Then install the compiler of [toolchain], from the build cache where it holds it:")
    print("    seanerstack toolchain bootstrap")
    return 0


def _environment_packages(path) -> set[str]:
    import re
    import yaml

    data = yaml.safe_load((path / "spack.yaml").read_text(encoding="utf-8")) or {}
    specs = data.get("spack", {}).get("specs", [])
    packages: set[str] = set()
    for spec in specs:
        if not isinstance(spec, str):
            continue
        match = re.match(r"\s*([A-Za-z0-9_.-]+)", spec)
        if match:
            packages.add(match.group(1).split(".")[-1].replace("_", "-"))
    return packages


def _run_envpath(args: argparse.Namespace) -> int:
    root = environments_path()
    if args.environment:
        path = root / args.environment
        if not (path / "spack.yaml").is_file():
            raise ValueError(f"unknown Seanerstack environment: {args.environment}")
        print(path)
        return 0

    package = args.package.replace("_", "-")
    matches = [
        path
        for path in sorted(p for p in root.iterdir() if p.is_dir() and (p / "spack.yaml").is_file())
        if package in _environment_packages(path)
    ]
    if not matches:
        raise ValueError(f"no Seanerstack environment contains root package {args.package!r}")
    if len(matches) > 1:
        names = ", ".join(path.name for path in matches)
        raise ValueError(f"multiple Seanerstack environments contain {args.package!r}: {names}; use --environment")
    print(matches[0])
    return 0


def _run_validate(args: argparse.Namespace) -> int:
    config, secrets = _runtime(args)
    languages = tuple(args.language) if args.language else DEFAULT_LANGUAGES
    command = env = None
    if args.with_spack or args.compiler:
        _, _, command, env = _spack_runtime(args)
    findings = validate(
        online=args.online,
        access=args.access,
        with_spack=args.with_spack,
        compiler=args.compiler,
        languages=languages,
        spack_command=command,
        spack_env=env,
        config=config,
        secrets=secrets,
    )
    failed = False
    for finding in findings:
        marker = {"ok": "OK", "warning": "WARN", "error": "ERROR"}[finding.level]
        print(f"[{marker}] {finding.subject}: {finding.message}")
        failed |= finding.level == "error"
    return 1 if failed else 0


def _run_buildcache(args: argparse.Namespace) -> int:
    config, secrets = _runtime(args)
    if args.buildcache_command == "explain":
        from .buildcache import buildcache_environment, explain
        _, _, command, env = _spack_runtime(args)
        return explain(
            " ".join(args.spec), command=command, env=buildcache_environment(config, secrets, env),
            match=getattr(args, "match", "os"),
        )
    if args.buildcache_command == "configure":
        _, _, command, env = _spack_runtime(args)
        configure_buildcaches(config, command=command, env=env)
        return 0
    if args.buildcache_command == "check":
        _, _, command, env = _spack_runtime(args)
        failed = False
        for name, ok, message in check_buildcaches(config, secrets, command=command, base_env=env):
            print(f"[{'OK' if ok else 'ERROR'}] buildcache:{name}: {message or 'accessible'}")
            failed |= not ok
        return 1 if failed else 0
    if args.buildcache_command == "update-index":
        name = args.cache or (config.toolchain.cache if config.toolchain else None)
        if name is None:
            raise ValueError("name the build cache; config.toml has no [toolchain]")
        resource = config.resource(name)
        if resource.kind != "spack-buildcache":
            raise ValueError(f"resource {name!r} is not a spack-buildcache")
        _, _, command, env = _spack_runtime(args)
        if resource.credentials and not all(variable in env for variable in resource.credential_variables):
            env.update(spack_resource_environment(resource, secrets))
        update_index(resource, command=command, env=env)
        return 0
    if args.buildcache_command == "prepare":
        if args.no_container:
            if args.platform == "all":
                raise ValueError("--no-container builds for the platform it runs on; name it with --platform")
            x, _, command, env = _spack_runtime(args)
            return prepare_here(
                config, secrets, platform=args.platform, command=command, env=env,
                work=x.environments / "toolchain", jobs=args.jobs,
                padded_length=args.padded_length, spack_config=x.config, probe_timeout=args.probe_timeout or None,
            )
        state_dir = args.state_dir or Path(os.environ.get("SEANERSTACK_STATE_DIR", "~/.cache/seanerstack"))
        toolchain = config.toolchain
        platforms = list(toolchain.platforms) if args.platform == "all" and toolchain else [args.platform]
        for platform in platforms:
            prepare_in_container(
                config, secrets, platform=platform, state_dir=state_dir, jobs=args.jobs, padded_length=args.padded_length,
                probe_timeout=args.probe_timeout,
            )
        return 0
    raise ValueError(f"unknown buildcache command: {args.buildcache_command}")


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "package" and args.package_command == "update":
            code = _run_package_update(args)
        elif args.command == "toolchain" and args.toolchain_command == "bootstrap":
            code = _run_bootstrap(args)
        elif args.command == "validate":
            code = _run_validate(args)
        elif args.command == "paths":
            if args.paths_command == "share":
                print(share_path())
                code = 0
            elif args.paths_command == "repo":
                print(repository_path())
                code = 0
            elif args.paths_command == "env":
                code = _run_envpath(args)
            else:
                raise ValueError(f"unknown paths command: {args.paths_command}")
        elif args.command == "buildcache":
            code = _run_buildcache(args)
        elif args.command == "init":
            code = _run_init(args)
        elif args.command == "activate":
            config, secrets = _runtime(args)
            state_dir = resolve_state_dir(args.state_dir)
            real_spack = resolve_real_spack(args.spack_executable or read_record(state_dir)["spack_executable"], state_dir)
            print(activation_script(state_dir=state_dir, real_spack=real_spack, config=config, secrets=secrets), end="")
            code = 0
        elif args.command == "deactivate":
            print(deactivation_script(), end="")
            code = 0
        else:
            parser.error(f"unknown command: {args.command}")
            return
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"seanerstack: error: {error}", file=sys.stderr)
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
