# Work on a package

Use this procedure for normal development on a SEANERGYS package checkout. It assumes the Seanerstack state directory and project compiler have already been prepared.

The example uses `properdocs`.

## Activate the isolated Spack session

Select the prepared state directory and activate Seanerstack:

```console
export SEANERSTACK_STATE_DIR=/path/to/seanerstack-state
eval "$(seanerstack activate)"
```

## Activate the package environment

From the package checkout, activate the environment shipped by Seanerstack:

```console
spack env activate "$(seanerstack paths env --package properdocs)"
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

These are normal Spack operations. The activated Seanerstack session supplies the isolation boundary; it does not replace the Spack CLI.

When dependencies or recipes change, rerun:

```console
spack concretize -f
spack install
```

When the shell no longer needs Seanerstack's Spack state, deactivate it:

```console
eval "$(seanerstack deactivate)"
```
