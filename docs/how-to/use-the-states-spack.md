# Use Spack in the Seanerstack state

Use this procedure whenever you want ordinary `spack` commands to use Seanerstack's private configuration, store, stages, caches, and environments. It assumes `seanerstack init` has set up the state (see [Set up Spack for SEANERGYS](set-up-a-workstation.md)).

## Put the state's spack on PATH

`seanerstack init` writes a `spack` wrapper into the state directory and prints the line that puts it on `PATH`. For the default state directory:

```console
export PATH=/opt/seanergys/state/spack/bin:$PATH
```

Add the line to your shell profile, such as `~/.bashrc`, to make it permanent. The wrapper carries the state's settings itself, so no further variables are needed in any shell.

To use the state in one shell only, activate it instead. Activation also exports the state's Spack variables and the stored registry credentials, and `deactivate` restores the shell:

```console
eval "$(seanerstack activate)"
eval "$(seanerstack deactivate)"
```

Use Spack normally:

```console
spack find
spack spec hdf5
spack install hdf5
```

## Credentials

When `init` was given `--secrets-file`, it stored the credentials that the configured resources name in the state directory, readable only by you. The wrapper loads them for every `spack` command, so private build caches work without further steps.

To change the credentials, run `seanerstack init --secrets-file FILE` again.

## Use a Spack environment

The `spack` wrapper is the plain Spack executable without Spack's shell integration. Activate an environment through the shell code that Spack prints:

```console
eval "$(spack env activate --sh "$(seanerstack paths env --package properdocs)")"
```

and leave it with:

```console
eval "$(spack env deactivate --sh)"
```
