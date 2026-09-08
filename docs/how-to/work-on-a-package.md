# Work on a package

Use this procedure for normal development on a SEANERGYS package checkout. It assumes the Seanstack state directory and project compiler have already been prepared.

The example uses `properdocs`.

## Activate the isolated Spack session

Select the prepared state directory and activate Seanstack:

```console
export SEANSTACK_STATE_DIR=/path/to/seanstack-state
eval "$(seanstack activate)"
```

## Activate the package environment

From the package checkout, activate the environment shipped by Seanstack:

```console
spack env activate "$(seanstack paths env --package properdocs)"
```

## Bind the checkout

```console
spack develop --path "$PWD" properdocs@develop
```

## Install the environment

```console
spack concretize -f
spack install
```

These are normal Spack operations. The activated Seanstack session supplies the isolation boundary; it does not replace the Spack CLI.

When dependencies or recipes change, rerun:

```console
spack concretize -f
spack install
```

When the shell no longer needs Seanstack's Spack state, deactivate it:

```console
eval "$(seanstack deactivate)"
```
