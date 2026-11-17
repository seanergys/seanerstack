# Changelog

All notable changes to Seanerstack are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/). See
[Seanerstack releases](docs/explanation/releases.md) for the versioning scheme
and release process.

## [Unreleased]

### Added

- `seanerstack toolchain bootstrap COMPILER --external PREFIX`, and the same
  option of `init`, make a compiler already installed in PREFIX, such as the
  GCC 16 of `/usr`, the project compiler without building one. COMPILER must
  name the compiler there; a spec Spack would build from source is refused
  before anything requires it.
- `SEANERSTACK_BUILTIN_REPO_GIT` overrides the Git location the pinned
  builtin `spack-packages` repository is cloned from, for hosts without
  internet access. The commit pin still applies.
- The `seanerbus-cpp` and `seanerbus-python` packages, with `py-pycapnp`, which
  Spack does not have.
- `seanerbus-msg` and `seanerbus-rs`, the schemas and the Rust crates that the
  other seanerbus packages build from.
- The seanerbus packages and `py-pycapnp` have a test for `spack test run`.
- `seanerbus-cli`, the command-line client of the SeanerBUS.
- `telemetry-collector`, the SEANERGYS Telemetry Collector and its plugins, and the
  `telemetry-collector-dev` environment.
- `seanerstack --version` prints the Seanerstack version and the Spack version
  it pins.
- Seanerstack pins Spack to v1.2.2, in `src/seanerstack/pins.py`. It clones that
  version into the state directory on first use, and refuses a Spack of another
  version given with `--spack-executable` or `SEANERSTACK_REAL_SPACK`, because its
  specs, build-cache indexes and hashes do not match the project build cache.

### Changed

- The `demobus` package is now `seanerbus`, and the `demobus-dev` environment is
  now `seanerbus-dev`. The upstream repository keeps its name.
- `seanerbus` package is now a bundle packages which installs the broker as the
  `seanerbroker` package, the name that upstream gave it on 2026-11-03.
- The seanerbus packages clone no submodules. They depend on `seanerbus-rs`,
  `seanerbus-msg` and the `fmt` of Spack instead.
- The state directory defaults to `/opt/seanergys/state` for every command, the
  directory in which the toolchain of the project build cache is built, because
  the install path of the compiler is part of every hash.

### Fixed

- `seanerbus` declares its build dependency on `capnproto`, without which a clean
  build fails in the build script of `internal_schemas`.
- `seanerstack package update` accepts a recipe without releases, which follows only
  its branches, instead of failing to infer a tag convention.
- `seanerstack validate --online` and `package update --all` leave out recipes
  without a Git URL, such as `py-pycapnp`, instead of stopping at them.
- `buildcache prepare` rebuilds the index of the build cache after pushing.
  Autopush had already pushed every package, and a push that skips everything
  leaves an OCI index unchanged, so the new binaries were invisible.
- `toolchain bootstrap` builds the compiler even when the system compiler has a
  matching version, which Spack took instead, and leaves only the built one
  registered.

## [0.1.3] - 2026-10-28

### Changed

- The builtin `spack-packages` repository is pinned to the `v2026.10.0`
  commit and cloned into `package_repos/` inside the state directory instead
  of `~/.spack/package_repos/`. Seanerstack now rewrites the private
  `repos.yaml` on every activation, so existing state directories follow a new
  pin.
- The version is defined only in `pyproject.toml`, and
  `seanerstack.__version__` reads it from the installed package metadata.
  Before, the version in `src/seanerstack/__init__.py` could disagree with
  it, so the 0.1.1 wheel was labelled 0.1.0.

## [0.1.1] - 2026-10-28

### Changed

- Secrets files are read with `keyloom` instead of `seanervault`. A secret is
  marked `{ __keyloom__ = "secret", value = ... }` and encrypted with
  `keyloom encrypt`; existing Seanervault files must be re-encrypted with
  keyloom. The `--secrets-file`, `--secrets-password-file` and
  `--secrets-password-stdin` options are unchanged.
- `keyloom` is installed from PyPI, so installing Seanerstack from source no
  longer requires access to the SEANERGYS package index.
- Git credentials of a resource are sent with the first request instead of
  after an authentication challenge, so an invalid token is reported even for
  a public repository. This requires Git 2.31 or later; with an older Git,
  commands that use Git credentials fail with an error.

### Added

- Build caches with a `file://` URL, kept in a directory on a local or shared
  filesystem. Such a cache is unsigned unless the resource sets
  `signed = true`, and a resource that names credentials for it is rejected.
- How-to guide on creating, checking and updating the secrets file, and on
  converting a Seanervault file.
- End-to-end tests (`tests/e2e`, CI job `e2e`) that install the wheel of the commit
  and, through a keyloom secrets file and the CI job token, read the demobus
  repository and push a package to a test build cache and install it back.

## [0.1.0] - 2026-10-22

First published release.

### Added

- `seanerstack` CLI: `init` (one-step compiler bootstrap, build-cache/registry
  setup, and validation), `toolchain bootstrap`, `package update`, `validate`,
  `buildcache configure`/`check`, and `paths`.
- Curated Spack package recipes and environments for SEANERGYS, isolated from
  the user's home directory.
- `seanervault` for managing secrets referenced by Seanerstack configuration.
