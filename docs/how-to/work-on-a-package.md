# Work on a package

Use this procedure for normal development on a SEANERGYS package checkout. It assumes the Spack installation has already been prepared for SEANERGYS.

The example uses `properdocs`.

## Activate the package environment

From the package checkout, activate the environment shipped by Seanstack:

```console
spack env activate "$(seanstack envpath --package properdocs)"
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

After activation, these are normal Spack operations. Seanstack's role is to provide and maintain the recipe and environment used by Spack, not to wrap the installation commands.

When dependencies or recipes change, rerun:

```console
spack concretize -f
spack install
```
