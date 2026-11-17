# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import importlib.metadata
import os
from pathlib import Path
import subprocess
import sys

from .bootstrap import DEFAULT_LANGUAGES, DEFAULT_PROBE, DEFAULT_PROBE_TIMEOUT, bootstrap
from .buildcache import buildcaches, check_buildcaches, configure_buildcaches
from .config import Config, load_config
from .paths import environments_path, repository_path, share_path
from .pins import SPACK_VERSION
from .prepare import prepare_here, prepare_in_container
from .secrets import SecretStore
from .isolation import (
    activation_script, deactivation_script, layout, prepare_isolation,
    resolve_real_spack, resolve_state_dir, spack_command, spack_env,
)
from .sync import package_paths, sync_many
from .validate import validate


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
        help="Bootstrap a Spack-installed production compiler.",
        description=(
            "Install COMPILER through Spack if needed, then configure native Spack "
            "language-provider requirements so subsequent environment concretization uses it."
        ),
    )
    bootstrap_parser.add_argument("compiler", help="Spack compiler spec, for example gcc@15")
    bootstrap_parser.add_argument(
        "--language",
        action="append",
        choices=("c", "cxx", "fortran"),
        help="language provider to configure; repeat as needed (default: c, cxx, fortran)",
    )
    bootstrap_parser.add_argument("--probe", default=DEFAULT_PROBE, help=f"spec used to probe concretization (default: {DEFAULT_PROBE})")
    bootstrap_parser.add_argument("--probe-timeout", type=float, default=DEFAULT_PROBE_TIMEOUT, help=f"seconds to allow the probe before giving up (default: {DEFAULT_PROBE_TIMEOUT:g}); 0 waits indefinitely")
    bootstrap_parser.add_argument("--force", action="store_true", help="ask Spack to install the compiler even when it is already installed")
    bootstrap_parser.add_argument("--external", metavar="PREFIX", help="use the compiler already in PREFIX, such as /usr or a gcc-toolset, instead of building COMPILER; COMPILER must name it, for example gcc@16")
    bootstrap_parser.add_argument("--dry-run", action="store_true", help="show the intended operation without changing Spack configuration")

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate recipes, environments, resources, and optional online/Spack state.",
    )
    validate_parser.add_argument("--online", action="store_true", help="also compare recipe versions with upstream Git refs")
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
    cache_sub.add_parser("configure", help="Install configured build-cache mirrors into the isolated Spack configuration.")
    cache_sub.add_parser("check", help="Check access to configured build caches using session or vault credentials.")
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

    init_parser = subparsers.add_parser(
        "init",
        help="Bootstrap the compiler, configure build-cache/OCI registry access, and validate, in one step.",
        description=(
            "Prepare a complete Seanerstack setup in one command: bootstrap COMPILER "
            "through Spack, configure the build caches declared in config.toml "
            "(including OCI registry access, using --secrets-file), and validate "
            "the result."
        ),
    )
    init_parser.add_argument("compiler", help="Spack compiler spec, for example gcc@15")
    init_parser.add_argument(
        "--language",
        action="append",
        choices=("c", "cxx", "fortran"),
        help="language provider to configure; repeat as needed (default: c, cxx, fortran)",
    )
    init_parser.add_argument("--probe", default=DEFAULT_PROBE, help=f"spec used to probe concretization (default: {DEFAULT_PROBE})")
    init_parser.add_argument("--probe-timeout", type=float, default=DEFAULT_PROBE_TIMEOUT, help=f"seconds to allow the probe before giving up (default: {DEFAULT_PROBE_TIMEOUT:g}); 0 waits indefinitely")
    init_parser.add_argument("--force", action="store_true", help="ask Spack to install the compiler even when it is already installed")
    init_parser.add_argument("--external", metavar="PREFIX", help="use the compiler already in PREFIX, such as /usr or a gcc-toolset, instead of building COMPILER; COMPILER must name it, for example gcc@16")
    init_parser.add_argument("--skip-buildcache-check", action="store_true", help="configure build-cache mirrors without verifying access")
    init_parser.add_argument("--skip-validate", action="store_true", help="skip the final validation pass")

    subparsers.add_parser("activate", help="Emit shell code that activates an isolated Seanerstack Spack session.")
    subparsers.add_parser("deactivate", help="Emit shell code that restores the shell state saved by activation.")

    return parser


def _runtime(args: argparse.Namespace) -> tuple[Config, SecretStore]:
    config = load_config(args.config_file)
    secrets = SecretStore(
        args.secrets_file,
        password_file=args.secrets_password_file,
        password_stdin=args.secrets_password_stdin,
    )
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
    real_spack = resolve_real_spack(args.spack_executable, state_dir)
    x = prepare_isolation(state_dir, real_spack)
    env = dict(__import__("os").environ)
    env.update(spack_env(x))
    return x, real_spack, spack_command(x, real_spack), env

def _probe_warning(result) -> str:
    if result.external:
        return f"warning: the probe is not compiled by the compiler in {result.external}"
    return "warning: compiler name not visible in probe output"


def _run_bootstrap(args: argparse.Namespace) -> int:
    languages = tuple(args.language) if args.language else DEFAULT_LANGUAGES
    _, _, command, env = _spack_runtime(args)
    result = bootstrap(
        args.compiler,
        languages=languages,
        probe=args.probe,
        command=command,
        env=env,
        force=args.force,
        dry_run=args.dry_run,
        probe_timeout=args.probe_timeout or None,
        external=args.external,
    )
    if args.dry_run:
        if result.external:
            print(f"would use the {result.compiler} in {result.external}, building nothing")
        else:
            print(f"would bootstrap {result.compiler}")
        print(f"would require it for: {', '.join(result.languages)}")
        return 0
    print(f"compiler: {result.compiler}{f' in {result.external}' if result.external else ''}")
    print(f"registered as external: {'yes' if result.registered else 'no'}")
    print(f"languages: {', '.join(result.languages)}")
    print(f"compiler probe ({result.probe}): {'ok' if result.probe_ok else _probe_warning(result)}")
    return 0 if result.probe_ok else 1


def _run_init(args: argparse.Namespace) -> int:
    config, secrets = _runtime(args)
    languages = tuple(args.language) if args.language else DEFAULT_LANGUAGES
    _, _, command, env = _spack_runtime(args)

    result = bootstrap(
        args.compiler,
        languages=languages,
        probe=args.probe,
        command=command,
        env=env,
        force=args.force,
        probe_timeout=args.probe_timeout or None,
        external=args.external,
    )
    print(f"compiler: {result.compiler}{f' in {result.external}' if result.external else ''}")
    print(f"registered as external: {'yes' if result.registered else 'no'}")
    print(f"languages: {', '.join(result.languages)}")
    print(f"compiler probe ({result.probe}): {'ok' if result.probe_ok else _probe_warning(result)}")
    failed = not result.probe_ok

    configure_buildcaches(config, command=command, env=env)
    print(f"build caches: configured {len(buildcaches(config))} resource(s)")

    if not args.skip_buildcache_check:
        for name, ok, message in check_buildcaches(config, secrets, command=command, base_env=env):
            print(f"[{'OK' if ok else 'ERROR'}] buildcache:{name}: {message or 'accessible'}")
            failed |= not ok

    if not args.skip_validate:
        findings = validate(
            with_spack=True,
            compiler=args.compiler,
            languages=languages,
            spack_command=command,
            spack_env=env,
            config=config,
            secrets=secrets,
        )
        for finding in findings:
            marker = {"ok": "OK", "warning": "WARN", "error": "ERROR"}[finding.level]
            print(f"[{marker}] {finding.subject}: {finding.message}")
            failed |= finding.level == "error"

    if not failed:
        print()
        print("Setup complete. Activate with:")
        print('  eval "$(seanerstack activate)"')
    return 1 if failed else 0


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
    if args.buildcache_command == "prepare":
        if args.no_container:
            if args.platform == "all":
                raise ValueError("--no-container builds for the platform it runs on; name it with --platform")
            x, _, command, env = _spack_runtime(args)
            return prepare_here(
                config, secrets, platform=args.platform, command=command, env=env,
                work=x.environments / "toolchain", jobs=args.jobs,
            )
        state_dir = args.state_dir or Path(os.environ.get("SEANERSTACK_STATE_DIR", "~/.cache/seanerstack"))
        toolchain = config.toolchain
        platforms = list(toolchain.platforms) if args.platform == "all" and toolchain else [args.platform]
        for platform in platforms:
            prepare_in_container(config, secrets, platform=platform, state_dir=state_dir, jobs=args.jobs)
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
            real_spack = resolve_real_spack(args.spack_executable, state_dir)
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
