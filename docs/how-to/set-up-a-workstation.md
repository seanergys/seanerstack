# Set up Spack for SEANERGYS

Use this procedure when preparing a Spack installation for SEANERGYS work. For a completely new machine, follow the tutorial instead; this how-to assumes a `spack` executable is already available.

## 1. Configure pipx for the SEANERGYS package registry

Seanerstack is published to the SEANERGYS GitLab group's PyPI registry, which requires authentication even for read access. Create a GitLab personal, project, or group access token with at least the `read_api` scope, then point the installer at the registry as an extra index. [pipx](https://pipx.pypa.io/) uses `uv` or `pip` as its installer backend depending on its version, and they read different variables, so set both:

```console
export PIP_EXTRA_INDEX_URL="https://<token-name>:<token>@gitlab.seanergys.fz-juelich.de/api/v4/groups/158/-/packages/pypi/simple"
export UV_EXTRA_INDEX_URL="$PIP_EXTRA_INDEX_URL"
```

Persist it instead of exporting it in every shell by adding the same assignments to your shell profile.

## 2. Install or update Seanerstack

```console
pipx install --python python3.12 seanerstack
```

To update an existing installation, run `pipx upgrade seanerstack`.

Seanerstack requires Python 3.12 or newer. Pass `--python` explicitly: without it, pipx uses the system `python3`, which may be older.

Use pipx rather than a plain `pip install`. Without a virtual environment, pip silently falls back to a `--user` installation on hosts where you cannot write to the system site-packages, and Seanerstack cannot find its shared data in that layout. pipx installs into an isolated virtual environment and needs no root access. Inside a virtual environment that you manage yourself, `pip install --upgrade seanerstack` works as well.

Its dependencies, including `keyloom` for the secrets file, come from PyPI.

## 3. Initialize Seanerstack

Choose the persistent directory in which Seanerstack will keep Spack configuration and mutable state, then bootstrap the compiler, configure build-cache/OCI registry access, and validate the result in one step:

```console
export SEANERSTACK_STATE_DIR=/path/to/seanerstack-state
seanerstack --secrets-file secrets.toml init gcc@15
```

The directory contains Seanerstack's private Spack configuration, install store, stages, caches, and managed environments. Seanerstack does not implicitly use `$HOME` for this state, and there is no `spack repo add` step: Seanerstack installs its curated repository into the private configuration itself.

`--secrets-file` is only required when `config.toml` declares build caches that need credentials (see [Create a secrets file](create-a-secrets-file.md)). Omit it, or pass `--skip-buildcache-check`, when none do.

## Activate the setup

```console
eval "$(seanerstack activate)"
```

Spack is now prepared for SEANERGYS work. Use plain `spack` commands for package development, installation, and deployment. They use the selected Seanerstack state rather than normal user or system Spack configuration.

Leave the session with:

```console
eval "$(seanerstack deactivate)"
```
