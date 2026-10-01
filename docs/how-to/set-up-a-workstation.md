# Set up Spack for SEANERGYS

Use this procedure when preparing a Spack installation for SEANERGYS work. For a completely new machine, follow the tutorial instead; this how-to assumes `uv` and a `spack` executable are already available.

## Install or update Seanerstack

For a new installation:

```console
uv tool install seanerstack@latest
```

To update an existing installation to the current curated stack:

```console
uv tool upgrade seanerstack
```

## Choose the private state directory

Select the persistent directory in which Seanerstack will keep Spack configuration and mutable state:

```console
export SEANERSTACK_STATE_DIR=/path/to/seanerstack-state
```

The directory contains Seanerstack's private Spack configuration, install store, stages, caches, and managed environments. Seanerstack does not implicitly use `$HOME` for this state.

There is no `spack repo add` step: Seanerstack installs its curated repository into the private configuration itself.

## Bootstrap the project compiler

```console
seanerstack toolchain bootstrap gcc@15
```

## Verify the setup

```console
seanerstack validate --compiler gcc@15 --spack
```

## Activate the setup

```console
eval "$(seanerstack activate)"
```

Spack is now prepared for SEANERGYS work. Use plain `spack` commands for package development, installation, and deployment. They use the selected Seanerstack state rather than normal user or system Spack configuration.

Leave the session with:

```console
eval "$(seanerstack deactivate)"
```
