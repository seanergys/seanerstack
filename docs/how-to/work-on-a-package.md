# Work on a package

Use this procedure for normal development on a SEANERGYS package checkout. It assumes the Seanerstack state and the project compiler have already been prepared, and that the state's `spack` is on `PATH` (see [Set up Spack for SEANERGYS](set-up-a-workstation.md)).

The `spack` wrapper of the state applies the isolation in every shell; nothing has to be activated for Seanerstack itself.

The example uses `properdocs`.

## Activate the package environment

From the package checkout, activate the environment shipped by Seanerstack. The state's `spack` has no Spack shell integration, so use the shell code that Spack prints:

```console
eval "$(spack env activate --sh "$(seanerstack paths env --package properdocs)")"
```

## Bind the checkout

```console
spack develop --path "$PWD" properdocs@master
```

## Install the environment

```console
spack concretize -f
spack install
```

These are normal Spack operations. The state's `spack` wrapper supplies the isolation boundary; it does not replace the Spack CLI.

When dependencies or recipes change, rerun:

```console
spack concretize -f
spack install
```

When the shell no longer needs the environment, leave it:

```console
eval "$(spack env deactivate --sh)"
```

## Add the package to seanergys-meta

`seanergys-meta` is the package that brings in the SEANERGYS software stack, and the `build:rocky10` job builds it in every pipeline. A new recipe is not part of it at first, so a recipe that does not build yet does not fail the pipelines of everyone else. Once the package builds with the project toolchain on Rocky Linux 10, add it to `packages/seanergys_meta/package.py`, in alphabetical order:

```python
    depends_on("properdocs", type="run")
```

From then on every pipeline builds it, and the default branch puts it into the project build cache.
