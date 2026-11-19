# Changelog

All notable changes to Seanerstack are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/). See
[Seanerstack releases](docs/explanation/releases.md) for the versioning scheme
and release process.

## [Unreleased]

### Added

- The compiler of the stack is built in two stages. The system compiler builds
  a first GCC, for C and C++ only, in a Spack instance of its own below
  `<state>/bootstrap`; the actual instance knows it only as an external at
  `<state>/bootstrap/store/gcc-VERSION`, and it builds the compiler of the
  stack with everything that compiler links against. On Fedora 44 and 45,
  whose system GCC 16 is newer than the compiler, nothing concretized with a
  compiler that GCC 16 had built: Spack's gcc recipe lets whatever gcc@15
  compiles depend only on gcc@:15. The hash of the compiler no longer depends
  on the system compiler, only on the state directory.
- `toolchain bootstrap` takes the compiler of a shipped lockfile from the build
  caches only (`spack install --cache-only`), and stops when they lack it
  instead of building for hours; `--concretize` builds it on the machine.
- Seanerstack ships the lockfile of the compiler environment for Rocky Linux
  10, and `toolchain bootstrap` and `buildcache prepare` install the compiler
  from it without concretizing. A machine with another system compiler, or
  without `gfortran`, then installs the compiler that the build cache holds
  and no longer builds its own. `--concretize` concretizes on the machine, for
  a new lockfile. The other platforms concretize as before.
- `seanerstack buildcache prepare --probe-timeout SECONDS` sets how long the
  compiler probe may take, as `init` and `toolchain bootstrap` already do; 0
  waits indefinitely. In a container, the build inside gets the same limit.
- `seanerstack toolchain bootstrap --external gcc@16` makes a compiler that
  `init` found, such as the GCC 16 of `/usr`, the project compiler without
  building one. Seanerstack checks that the spec resolves to that installation
  before anything requires it, and that the probe is compiled by it.
- `SEANERSTACK_BUILTIN_REPO_GIT` overrides the Git location the pinned
  builtin `spack-packages` repository is cloned from, for hosts without
  internet access. The commit pin still applies.
- `seanerstack buildcache explain SPEC` says why SPEC is built instead of taken
  from the build caches: it compares the local concretization with every cached
  spec of the same name and version, and prints the nodes whose own fields
  differ, such as the target, a variant, the recipe or an external's path.
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
- `seanerstack init --secrets-file FILE` stores the credentials that the
  configured resources name in the state directory, readable only by their
  owner, and records the `config.toml` and Spack it was given. Later commands
  use them without `--secrets-file`, `--config-file` or `--spack-executable`.
- The `spack` wrapper in `<state>/spack/bin` works in any shell: it carries the
  state's settings and loads the stored credentials. Put it on `PATH` once.
- `init` checks that every build cache and every Git resource can be read.
- `seanergys-meta` depends on the packages that build with the project
  toolchain: `flux-core`, `priorisea`, `properdocs`, `pscom`, `py-pycapnp`,
  `seanerbus`, `seanerbus-cli`, `seanerbus-msg` and `seanerbus-rs`. The
  `build:rocky10` job builds it in every pipeline. `psmpi` and
  `telemetry-collector` join it once they build.

### Changed

- The stack reuses the compiler alone from the compiler environment. What the
  compiler was built with, such as `ncurses`, `readline` and `gmake`, was
  compiled by the system compiler, and every package that needed one of them
  took the compiler's. The stack now builds its own with the project
  compiler; only `zlib-ng` and `zstd`, which the compiler links against, are
  shared. Every hash of the toolchain packages and the stack changes.
- `buildcache prepare` pushes the compiler and updates the index of the cache
  as soon as the compiler is built, before the probe and the packages of the
  toolchain. A later failure no longer costs the build of the compiler again.
  When Spack does not use the compiler, the error names the probe and the
  installed compiler.
- The `demobus` package is now `seanerbus`, and the `demobus-dev` environment is
  now `seanerbus-dev`. The upstream repository keeps its name.
- `seanerbus` package is now a bundle packages which installs the broker as the
  `seanerbroker` package, the name that upstream gave it on 2026-11-03.
- The seanerbus packages clone no submodules. They depend on `seanerbus-rs`,
  `seanerbus-msg` and the `fmt` of Spack instead.
- The state directory defaults to `/opt/seanergys/state` for every command, the
  directory in which the toolchain of the project build cache is built, because
  the install path of the compiler is part of every hash.
- `seanerstack init` takes no compiler. It sets up the state, configures the
  build caches and the CPU target of `[toolchain]`, finds the compilers and the
  toolchain's packages installed on the machine and prints them, and checks
  access. `--find PREFIX` adds an installation off `PATH`, such as a
  gcc-toolset.
- `seanerstack toolchain bootstrap` installs the whole toolchain: the compiler,
  then its packages, rust and capnproto by default, or those given as arguments.
  `--compiler`, `--source-compiler`, `--target` and `--os` choose the compiler to
  build, the one that builds it, the CPU target and the operating system to
  expect; `--external` uses a compiler or package that `init` found instead of
  building it.
- `seanerstack activate` takes the credentials from the state, so it asks for no
  vault password.

### Fixed

- `toolchain bootstrap` and `buildcache prepare` no longer stop at a compiler
  probe that never finishes. The compiler was required on the languages `c`,
  `cxx` and `fortran`, which Spack also applies to the compiler's own
  dependencies, built by the system compiler, so nothing could satisfy it. It
  is now required on every package that takes a language from that compiler.
- `seanerstack init` run again keeps the compiler rule that `toolchain
  bootstrap` wrote. Setting the target removed every requirement on all
  packages before.
- A compiler probe that runs out of time reports what Spack printed until then
  and how to tell a slow solve from a requirement without a solution. It no
  longer names the requirement as the cause, which it had not checked.
- `toolchain bootstrap` stops with an error that names the build cache when an
  OCI cache refuses its request, such as a private registry asked with missing
  or expired credentials. Spack reports that as "no binary available" and builds
  from source.
- `toolchain bootstrap` gives Spack the stored credentials of the build caches.
  Without them it asked a private cache anonymously, was refused, and built the
  compiler and Rust from source although the cache held them.
- `buildcache check` and `init` fail on a build cache whose index a newer Spack
  wrote, which the pinned Spack cannot read, instead of reporting it as fine.
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
