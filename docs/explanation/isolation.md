# Spack isolation

Seanerstack treats a selected state directory as the complete mutable Spack state for a SEANERGYS session. This prevents an existing user or system Spack setup from changing concretization or causing packages to be reused accidentally.

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

Seanerstack sets `SPACK_DISABLE_LOCAL_CONFIG` and supplies its private configuration explicitly to Spack. The generated configuration uses replacement sections where necessary so lower-precedence configuration is not merged into the Seanerstack view.

## State and store isolation

All mutable Spack state controlled by Seanerstack is redirected below the selected state directory:

```text
<state-dir>/
└── spack/
    ├── bin/
    │   └── spack
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

The clone directory is named after the commit. When Seanerstack moves to a new pin, the next activation writes the new commit into the private configuration and Spack clones that commit into a new directory, so no `spack repo update` is needed. Older clones remain in `package_repos/` and can be deleted.

Seanerstack also initializes the concretizer with reuse disabled. Packages are not selected merely because a matching installation exists in another store or build cache. Build caches used by the stack must be configured explicitly as Seanerstack resources.

The Spack executable itself can live outside the state directory. It is executable code, not mutable package state. Seanerstack records the selected executable and invokes it with the isolated configuration and state paths.

## Why activation exists

A command such as `seanerstack toolchain bootstrap` can inject the isolation settings into the Spack subprocess it starts. Normal development is different: users should be able to invoke the native `spack` CLI directly.

Activation bridges that boundary:

```console
eval "$(seanerstack --state-dir /path/to/seanerstack-state activate)"
```

The activated shell places a small Seanerstack-generated `spack` launcher first on `PATH`. The launcher preserves the complete native Spack command line while always supplying the private configuration. Environment variables redirect the remaining user state into the selected state directory.

Consequently these remain ordinary Spack commands:

```console
spack spec hdf5
spack install hdf5
spack find
```

They do not need to be written as `seanerstack spack ...`.

## State-directory selection

Seanerstack deliberately has no implicit home-directory state location. Select the state directory explicitly:

```console
seanerstack --state-dir /path/to/seanerstack-state toolchain bootstrap gcc@15
```

or set it for the shell:

```console
export SEANERSTACK_STATE_DIR=/path/to/seanerstack-state
```

After that, commands that need Spack can omit `--state-dir`:

```console
seanerstack toolchain bootstrap gcc@15
seanerstack validate --compiler gcc@15 --spack
```

This makes the isolation boundary visible and prevents Seanerstack from silently falling back to `$HOME`.

## Deactivation

Leave the isolated session with:

```console
eval "$(seanerstack deactivate)"
```

Seanerstack restores the values that were present before activation, including `PATH` and the Spack-related environment variables it manages.

Only one Seanerstack session may be active in a shell at a time. Deactivate the current session before activating a different state directory.
