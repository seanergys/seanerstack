# Spack isolation

Seanerstack treats one state directory, by default `/opt/seanergys/state`, as the complete mutable Spack state for SEANERGYS work. This prevents an existing user or system Spack setup from changing concretization or causing packages to be reused accidentally.

There are two separate isolation guarantees.

## Configuration isolation

Seanerstack does not use the normal user or system Spack configuration for managed operations. In particular, configuration from locations such as `~/.spack` and `/etc/spack` is not part of the Seanerstack session.

The private configuration starts with Seanerstack-controlled package repositories, no inherited mirrors or upstream stores, and no inherited package configuration or externals. Compiler requirements and build-cache configuration written by Seanerstack are stored in this private configuration.

```text
normal user/system Spack configuration       Seanerstack configuration

~/.spack/                         X          <state-dir>/spack/config/
/etc/spack/                       X                    |
user mirrors                     X                    +-- config.yaml
user packages.yaml               X                    +-- packages.yaml
user upstreams                   X                    +-- mirrors.yaml
                                                      +-- upstreams.yaml
                                                      +-- concretizer.yaml
                                                      +-- repos.yaml
```

Seanerstack points Spack's user configuration scope (`SPACK_USER_CONFIG_PATH`) at its private configuration directory and the system scope (`SPACK_SYSTEM_CONFIG_PATH`) at a directory that does not exist, and supplies its private configuration explicitly to Spack. The generated configuration uses replacement sections where necessary so lower-precedence configuration is not merged into the Seanerstack view.

Seanerstack deliberately does not set `SPACK_DISABLE_LOCAL_CONFIG`, and the state's `spack` wrapper unsets it. That variable switches the user scope off entirely, including `SPACK_USER_CONFIG_PATH`, which would leave no writable scope: `spack config add` and `spack compiler find` would write to the site scope inside the Spack checkout, where the replacement sections override them.

## State and store isolation

All mutable Spack state controlled by Seanerstack is redirected below the selected state directory:

```text
<state-dir>/
├── seanerstack.json        what init recorded: config.toml, Spack
├── credentials.json        stored credentials, mode 0600
├── spack-7188f9d6e0f3/     the pinned Spack, named by its commit
└── spack/
    ├── bin/
    │   └── spack           the wrapper
    ├── credentials.sh      the same credentials as Spack's variables, mode 0600
    ├── config/
    ├── store/
    ├── stage/
    ├── cache/
    ├── source-cache/
    ├── environments/
    └── package_repos/
```

The install tree, build stages, source cache, miscellaneous cache, test stage, and managed-environment root therefore do not reuse corresponding state from another Spack setup.

## Pinned builtin recipes

Seanerstack pins the builtin `spack-packages` repository to one commit and clones it into `package_repos/` inside the state directory, not into `~/.spack/package_repos/`. The pinned commit is the release `v2026.10.0`.

The pin makes build caches usable across sessions. A binary in a build cache is used only when its hash matches exactly, and the hash depends on the package recipes. Without a pin, two sessions set up at different times could load different recipes and fail to share binaries.

The clone directory is named after the commit. When Seanerstack moves to a new pin, the next Seanerstack command writes the new commit into the private configuration and Spack clones that commit into a new directory, so no `spack repo update` is needed. Older clones remain in `package_repos/` and can be deleted.

On a host without internet access, set `SEANERSTACK_BUILTIN_REPO_GIT` to a mirror or a local clone of `spack-packages` that the host can reach, for example a bare repository on a shared filesystem. Seanerstack clones the same pinned commit from there, so build-cache hashes do not change. The mirror has to contain that commit.

Seanerstack also initializes the concretizer with reuse disabled. Packages are not selected merely because a matching installation exists in another store or build cache. Build caches used by the stack must be configured explicitly as Seanerstack resources.

## Pinned Spack

Spack is pinned too, to commit `7188f9d6e0` of its develop branch, which reports version `1.3.0.dev0`. Spack 1.2.2 hangs when it concretizes with a gcc that Spack built with a newer gcc, such as gcc 15 built by the gcc 16 of Fedora; the fixes are on develop and in no release yet (see [Compiler as a package](compiler-as-a-package.md#known-problems-of-spack-that-were-not-met-here)). Both pins live in `src/seanerstack/pins.py`, the one place to change them. On first use, Seanerstack fetches that commit into `spack-<commit>/` in the state directory and uses it from then on. Every commit of develop reports the same version, so a Spack given with `--spack-executable` or `SEANERSTACK_REAL_SPACK` has to report the pinned commit as well as the version, or Seanerstack refuses it: another Spack writes specs and build-cache indexes that the pinned one cannot read, and its hashes match nothing in the project build cache. `seanerstack --version` prints both.

## The state's spack wrapper

A command such as `seanerstack toolchain bootstrap` can pass the isolation settings to the Spack subprocess it starts. Normal development is different: users should be able to invoke the native `spack` CLI directly.

The state directory therefore contains a small Seanerstack-generated `spack` wrapper in `spack/bin/`. It sets the variables that redirect Spack's user configuration and data into the state, removes `SPACK_DISABLE_LOCAL_CONFIG`, loads the stored credentials, and runs the state's Spack with the private configuration, passing the complete native command line through. `seanerstack activate` puts it first on `PATH` in the shell that runs it:

```console
eval "$(seanerstack activate)"
```

Consequently these remain ordinary Spack commands in that shell:

```console
spack spec hdf5
spack install hdf5
spack find
```

They do not need to be written as `seanerstack spack ...`, and nothing has to be activated first.

## Credentials

Spack reads the credentials of a build cache only from environment variables, and its mirror configuration names those variables, never the values. `seanerstack init --secrets-file FILE` decrypts the secrets file once and stores the credentials that the configured resources name in the state directory, readable only by their owner: as a secrets mapping in `credentials.json` for Seanerstack's own commands, and as the variables in `spack/credentials.sh`, which the wrapper loads. Later commands need neither the secrets file nor its password. Variables that are already set, as in CI, take precedence.

## State-directory selection

The state directory defaults to `/opt/seanergys/state` for every command. Another directory can be selected with `--state-dir DIR` or `SEANERSTACK_STATE_DIR`. The hash of a package does not depend on where it is installed, and the compiler is reused as an installed package (see [Compiler bootstrap](compiler-bootstrap.md#why-the-compiler-is-reused-as-an-installed-package)), so a state in any directory takes the same binaries from the project build cache.

`seanerstack init` records what it was given, the `config.toml` and a Spack executable, in `seanerstack.json` in the state directory. Every later command reads it, so options given to `init` are not repeated; run `init` again to change them.
