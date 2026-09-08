# Set up Spack for SEANERGYS

Use this procedure when preparing a Spack installation for SEANERGYS work. For a completely new machine, follow the tutorial instead; this how-to assumes `uv` and Spack are already installed.

## Install or update Seanstack

For a new installation:

```console
uv tool install seanstack@latest
```

To update an existing installation to the current curated stack:

```console
uv tool upgrade seanstack
```

## Register the Seanstack repository

```console
spack repo add "$(seanstack paths repo)"
```

## Bootstrap the project compiler

```console
seanstack toolchain bootstrap gcc@15
```

## Verify the setup

```console
seanstack validate --compiler gcc@15 --spack
```

Spack is now prepared for SEANERGYS work. From this point onward, use Spack directly for package development, installation, and deployment operations.
