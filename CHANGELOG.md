# Changelog

All notable changes to Seanerstack are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/). See
[Seanerstack releases](docs/explanation/releases.md) for the versioning scheme
and release process.

## [Unreleased]

### Changed

- Secrets files are read with `keyloom` instead of `seanervault`. A secret is
  marked `{ __keyloom__ = "secret", value = ... }` and encrypted with
  `keyloom encrypt`; existing Seanervault files must be re-encrypted with
  keyloom. The `--secrets-file`, `--secrets-password-file` and
  `--secrets-password-stdin` options are unchanged.
- `keyloom` is installed from PyPI, so installing Seanerstack from source no
  longer requires access to the SEANERGYS package index.

### Added

- How-to guide on creating, checking and updating the secrets file, and on
  converting a Seanervault file.
- End-to-end tests (`e2e/`, CI job `e2e`) that install the wheel of the commit
  and read the private demobus repository and the project build cache through
  a keyloom secrets file, with the CI job token.

## [0.1.0] - 2026-10-22

First published release.

### Added

- `seanerstack` CLI: `init` (one-step compiler bootstrap, build-cache/registry
  setup, and validation), `toolchain bootstrap`, `package update`, `validate`,
  `buildcache configure`/`check`, and `paths`.
- Curated Spack package recipes and environments for SEANERGYS, isolated from
  the user's home directory.
- `seanervault` for managing secrets referenced by Seanerstack configuration.
