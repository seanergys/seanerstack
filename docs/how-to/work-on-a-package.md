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
