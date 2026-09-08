# Set up Spack for SEANERGYS

Use this procedure when preparing a Spack installation for SEANERGYS work. For a completely new machine, follow the tutorial instead; this how-to assumes `uv` and a `spack` executable are already available.

## Install or update Seanstack

For a new installation:

```console
uv tool install seanstack@latest
```

To update an existing installation to the current curated stack:

```console
uv tool upgrade seanstack
```

## Choose the private state directory

Select the persistent directory in which Seanstack will keep Spack configuration and mutable state:

```console
export SEANSTACK_STATE_DIR=/path/to/seanstack-state
```

The directory contains Seanstack's private Spack configuration, install store, stages, caches, and managed environments. Seanstack does not implicitly use `$HOME` for this state.

There is no `spack repo add` step: Seanstack installs its curated repository into the private configuration itself.

## Bootstrap the project compiler

```console
seanstack toolchain bootstrap gcc@15
```

## Verify the setup

```console
seanstack validate --compiler gcc@15 --spack
```

## Activate the setup

```console
eval "$(seanstack activate)"
```

Spack is now prepared for SEANERGYS work. Use plain `spack` commands for package development, installation, and deployment. They use the selected Seanstack state rather than normal user or system Spack configuration.

Leave the session with:

```console
eval "$(seanstack deactivate)"
```
