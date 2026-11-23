# Glossary

The terms the pages use, each defined once. A term of Spack is defined as Seanerstack uses it.

Bootstrap instance
:   The second Spack instance of a state, below `<state>/bootstrap`, with a configuration, install tree and build cache of its own. It shares the pinned Spack, the recipes and the source cache with the Spack of the stack, and builds only the first stage of the compiler, so that nothing the system compiler built enters the stack. See [Why the compiler is built in two stages](../explanation/compiler-bootstrap.md#why-the-compiler-is-built-in-two-stages).

Build cache
:   A store of binaries that Spack installs instead of building, when the hash of a concretized package matches one it holds. The *project build cache* is the resource `seanerstack-buildcache`, an OCI build cache in the GitLab container registry of the project. The *bootstrap cache*, `seanerstack-buildcache-bootstrap`, holds the first stage of the compiler, and only the bootstrap instance reads it. A *filesystem build cache* is a directory. See [Use the project build cache](../how-to/use-the-build-cache.md).

Builtin recipes
:   Spack's own package repository, `spack-packages`, pinned to one commit and cloned into `package_repos/` of the state. The pin keeps the hashes of every machine equal. See [Pinned builtin recipes](../explanation/isolation.md#pinned-builtin-recipes).

Compiler environment
:   The Spack environment `environments/compiler` of the state. It holds the project compiler and everything the compiler was built with. The concretizer may reuse the compiler from it, and nothing else. See [Why the compiler is reused as an installed package](../explanation/compiler-bootstrap.md#why-the-compiler-is-reused-as-an-installed-package).

Compiler guard
:   The directory `spack/compiler-guard` of the state, with a script under each compiler name that fails and says which language dependency is missing. It is in front of `PATH` for every Spack the state runs, so a package that declares no language cannot compile with the system compiler unnoticed. See [The compiler guard](../explanation/isolation.md#the-compiler-guard).

Compiler lockfile
:   The concretized compiler environment of a platform, kept in the project build cache as a tag of its registry repository, such as `compiler-gcc-15-rocky10-x86_64_v3-2efee779f543`. `toolchain bootstrap` installs the compiler from it, so every machine of the platform gets the compiler with the same hash. See [Why the compiler is installed from a lockfile](../explanation/compiler-bootstrap.md#why-the-compiler-is-installed-from-a-lockfile).

Compiler rule
:   The requirement in `packages.yaml` of the state that a package which takes C, C++ or Fortran from a gcc takes it from the project compiler. See [How the compiler is required](../explanation/compiler-bootstrap.md#how-the-compiler-is-required).

Concretize
:   To turn a spec such as `hdf5+fortran` into a concrete spec, in which every version, variant, dependency, compiler and target is fixed, and which has a hash. A state concretizes fresh, with reuse off except for the compiler, so that every machine computes the same hashes.

Development build
:   A build published from every push to the default branch, versioned as the next patch version with the pipeline number as development release, such as `0.1.4.dev57`. See [Development builds](../explanation/releases.md#development-builds).

External
:   A package that Spack does not build but takes from the machine, registered with its path. An external is hashed by its path, so everything built with one has hashes that match nothing built elsewhere. The system compiler is an external; so is the first stage, for the Spack of the stack. See [Why not an external](../explanation/compiler-bootstrap.md#why-not-an-external).

First stage
:   The first gcc 15, built by the system compiler in the bootstrap instance, for C and C++ only, without GCC's own three-stage bootstrap and without binutils, installed at `<state>/bootstrap/store/gcc-15.3.0`. Its one purpose is to build the second stage.

Hash
:   The identifier of a concrete spec, computed from its recipe, version, variants, target and dependencies, and not from where it is installed. A build cache matches binaries by it. Two machines that concretize the same spec with the same pins get the same hash.

Languages
:   The virtual packages `c`, `cxx` and `fortran`. A recipe depends on them to get a compiler, and a compiler package such as `gcc` provides them. Spack gives a package a compiler wrapper only for the languages it depends on.

Pinned Spack
:   The one commit of Spack that a state uses, fetched into `spack-<commit>/` in the state directory and refused in any other version. The pins of Spack and of the builtin recipes are in `src/seanerstack/pins.py`. See [Pinned Spack](../explanation/isolation.md#pinned-spack).

Platform
:   An operating system and a target for which the toolchain is built, with the image that builds it, such as `rocky10` for Rocky Linux 10 on `x86_64_v3`. A binary of the build cache matches only its platform. The platforms are listed in `[toolchain]` of `config.toml`.

Probe
:   A small concretization that `init`, `toolchain bootstrap` and `buildcache prepare` run after the compiler is installed, to check that Spack uses it. It gives up after 300 seconds; `--probe-timeout` changes that.

Project compiler
:   The compiler of `[toolchain]` in `config.toml`, gcc 15, installed as a package in the compiler environment and reused by its hash. Every package of the stack is compiled by it. Also called the toolchain compiler.

Resource
:   An entry of `config.toml` that names something outside the state, such as a build cache, a registry or a Git host, and the credentials it takes from the secrets file.

Reuse
:   The setting of the concretizer that lets an installed package stand in for a new one. A state has it off, except for the compiler of the compiler environment.

Second stage
:   The project compiler, `gcc@15 %c,cxx=gcc@15`, built by the first stage in the compiler environment, with everything that gcc links against.

Secrets file
:   A TOML, YAML or JSON file with a `[credentials.NAME]` table for each login, whose secret values are encrypted with keyloom. `seanerstack init` reads it once and stores the credentials in the state. See [Create a secrets file](../how-to/create-a-secrets-file.md).

Spack environment
:   A Spack manifest with the specs of one context. Seanerstack ships one per package, for its development, and uses one of its own for the compiler. See [Packages and environments](../explanation/packages-and-environments.md).

State directory
:   The one directory, `/opt/seanergys/state` by default, that holds the complete mutable Spack state of SEANERGYS work: the pinned Spack, the configuration, the store, the stages, the caches, the environments and the stored credentials. See [Spack isolation](../explanation/isolation.md).

State's spack
:   The wrapper `spack/bin/spack` in the state directory, which runs the pinned Spack with the state's configuration and credentials, and passes the command line through. `seanerstack activate` puts it first on `PATH`. See [The state's spack wrapper](../explanation/isolation.md#the-states-spack-wrapper).

System compiler
:   The compiler that the operating system provides, such as GCC 14 on Rocky Linux 10 or GCC 16 on Fedora 45. It is an external, and builds only the first stage.

Target
:   The CPU microarchitecture that the stack is built for, `x86_64_v3` in `[toolchain]`. It is part of every hash, so one binary serves every machine of the platform that has it.

Toolchain
:   The `[toolchain]` section of `config.toml`: the project compiler, the packages that take hours to build, such as Rust and `capnproto`, the target, the platforms and their system packages. `seanerstack toolchain bootstrap` installs it from the build cache.

`seanergys-meta`
:   The package that depends on every recipe that builds with the project toolchain. Installing it installs the SEANERGYS stack.
