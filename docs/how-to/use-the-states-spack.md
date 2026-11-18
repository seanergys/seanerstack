# Use the state's Spack

Use this procedure to run ordinary `spack` commands with Seanerstack's private configuration, store, caches and credentials: in one shell, in every shell, or with a state in a directory of your choice. It assumes `seanerstack init` has set up the state (see [Set up a workstation](set-up-a-workstation.md)).

## Activate the state in a shell

```console
eval "$(seanerstack activate)"
```

In this shell, `spack` is the Spack of the state, and the state's Spack variables and stored registry credentials are set. Other shells are unchanged, so another Spack on the machine keeps working there. Use Spack normally:

```console
spack find
spack spec hdf5
spack install hdf5
```

Restore the shell with:

```console
eval "$(seanerstack deactivate)"
```

## Use the state in every shell

To have the state's Spack without activating, put its `spack` wrapper first on `PATH` in your shell profile, such as `~/.bashrc`. `seanerstack init` prints the line; for the default state directory it is:

```console
export PATH=/opt/seanergys/state/spack/bin:$PATH
```

The wrapper carries the state's settings and credentials itself, so no further variables are needed. It takes the place of any other `spack` on `PATH`; choose activation when the machine has a Spack of its own that you also use.

## Keep the state in another directory

The state can be anywhere you can write. Name the directory before you set the state up:

```console
export SEANERSTACK_STATE_DIR="$HOME/seanergys-state"
seanerstack --secrets-file secrets.toml init
eval "$(seanerstack activate)"
```

`SEANERSTACK_STATE_DIR` names the state directory for every `seanerstack` command; put the line into your shell profile so that later shells name the same state. `--state-dir DIR` before the command does the same for one command.

!!! warning "Another directory builds from source"
    Every binary of the project build cache contains the install path of the compiler that built it, which is below `/opt/seanergys/state`. In any other directory the hashes differ, nothing from the cache matches, and Spack builds the toolchain and the stack from source, which takes hours.

Several states can exist side by side, each in its own directory; activate the one a shell should use.

## Credentials

When `init` was given `--secrets-file`, it stored the credentials that the configured resources name in the state directory, readable only by you. The wrapper loads them for every `spack` command, so private build caches work without further steps.

To change the credentials, run `seanerstack init --secrets-file FILE` again.

## Use a Spack environment

The `spack` wrapper is the plain Spack executable without Spack's shell integration. Activate an environment through the shell code that Spack prints:

```console
eval "$(spack env activate --sh "$(seanerstack paths env --package priorisea)")"
```

and leave it with:

```console
eval "$(spack env deactivate --sh)"
```
