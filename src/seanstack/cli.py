# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
import subprocess
import sys

from .bootstrap import DEFAULT_LANGUAGES, DEFAULT_PROBE, DEFAULT_SCOPE, bootstrap
from .paths import environments_path, repository_path, share_path
from .sync import package_paths, sync_many
from .validate import validate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seanstack",
        description="Maintain and use the curated SEANERGYS Spack stack.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser(
        "sync",
        help="Synchronize Spack recipe versions with upstream Git refs.",
        description=(
            "Read each native package.py recipe, infer its release-tag convention "
            "from existing version(..., tag=...) directives, and add missing upstream releases."
        ),
    )
    sync_parser.add_argument("package", nargs="?", help="package to synchronize")
    sync_parser.add_argument("--all", action="store_true", help="synchronize every Seanstack package")
    sync_parser.add_argument("--check", action="store_true", help="report drift without changing files; return non-zero on drift")
    sync_parser.add_argument("--dry-run", action="store_true", help="show what would change without changing files")

    bootstrap_parser = subparsers.add_parser(
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
    bootstrap_parser.add_argument("--scope", default=DEFAULT_SCOPE, help=f"native Spack configuration scope to modify (default: {DEFAULT_SCOPE})")
    bootstrap_parser.add_argument("--force", action="store_true", help="ask Spack to install the compiler even when it is already installed")
    bootstrap_parser.add_argument("--dry-run", action="store_true", help="show the intended operation without changing Spack configuration")

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate recipes, environments, synchronization, and optionally compiler setup.",
        description="Validate native Spack artifacts. Online, compiler, and concretization checks are opt-in.",
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
    validate_parser.add_argument("--scope", default=DEFAULT_SCOPE, help=f"Spack scope used for compiler validation (default: {DEFAULT_SCOPE})")

    subparsers.add_parser("sharepath", help="Print the installed Seanstack share directory.")
    subparsers.add_parser("repopath", help="Print the native Seanstack Spack repository path.")

    envpath_parser = subparsers.add_parser("envpath", help="Print the path of a shipped Spack environment.")
    selector = envpath_parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--package", help="select the unique environment whose root specs contain PACKAGE")
    selector.add_argument("--environment", help="select an environment by directory name")

    return parser


def _run_sync(args: argparse.Namespace) -> int:
    paths = package_paths()
    if args.all:
        packages = list(paths)
    elif args.package:
        packages = [args.package]
    else:
        raise ValueError("provide PACKAGE or --all")

    results = sync_many(packages, check=args.check, dry_run=args.dry_run)
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


def _run_bootstrap(args: argparse.Namespace) -> int:
    languages = tuple(args.language) if args.language else DEFAULT_LANGUAGES
    result = bootstrap(
        args.compiler,
        languages=languages,
        probe=args.probe,
        scope=args.scope,
        force=args.force,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print(f"would bootstrap {result.compiler}")
        print(f"would require it for: {', '.join(result.languages)}")
        print(f"Spack scope: {result.scope}")
        return 0
    print(f"compiler: {result.compiler}")
    print(f"Spack scope: {result.scope}")
    print(f"languages: {', '.join(result.languages)}")
    print(f"compiler probe ({result.probe}): {'ok' if result.probe_ok else 'warning: compiler name not visible in probe output'}")
    return 0 if result.probe_ok else 1


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
            raise ValueError(f"unknown Seanstack environment: {args.environment}")
        print(path)
        return 0

    package = args.package.replace("_", "-")
    matches = [
        path
        for path in sorted(p for p in root.iterdir() if p.is_dir() and (p / "spack.yaml").is_file())
        if package in _environment_packages(path)
    ]
    if not matches:
        raise ValueError(f"no Seanstack environment contains root package {args.package!r}")
    if len(matches) > 1:
        names = ", ".join(path.name for path in matches)
        raise ValueError(
            f"multiple Seanstack environments contain {args.package!r}: {names}; "
            "use --environment"
        )
    print(matches[0])
    return 0


def _run_validate(args: argparse.Namespace) -> int:
    languages = tuple(args.language) if args.language else DEFAULT_LANGUAGES
    findings = validate(
        online=args.online,
        with_spack=args.with_spack,
        compiler=args.compiler,
        languages=languages,
        scope=args.scope,
    )
    failed = False
    for finding in findings:
        marker = {"ok": "OK", "warning": "WARN", "error": "ERROR"}[finding.level]
        print(f"[{marker}] {finding.subject}: {finding.message}")
        failed |= finding.level == "error"
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "sync":
            code = _run_sync(args)
        elif args.command == "bootstrap":
            code = _run_bootstrap(args)
        elif args.command == "validate":
            code = _run_validate(args)
        elif args.command == "sharepath":
            print(share_path())
            code = 0
        elif args.command == "repopath":
            print(repository_path())
            code = 0
        elif args.command == "envpath":
            code = _run_envpath(args)
        else:
            parser.error(f"unknown command: {args.command}")
            return
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as error:
        print(f"seanstack: error: {error}", file=sys.stderr)
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
