# Changelog

All notable changes to Seanerstack are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/). See
[Seanerstack releases](docs/explanation/releases.md) for the versioning scheme
and release process.

## [Unreleased]

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
