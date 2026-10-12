# Set up Spack for SEANERGYS

Use this procedure when preparing a Spack installation for SEANERGYS work. For a completely new machine, follow the tutorial instead; this how-to assumes a `spack` executable is already available.

## 1. Configure pip for the SEANERGYS package registry

Seanerstack and its `seanervault` dependency are published to the SEANERGYS GitLab group's PyPI registry, which requires authentication even for read access. Create a GitLab personal, project, or group access token with at least the `read_api` scope, then point pip at the registry as an extra index:

```console
export PIP_EXTRA_INDEX_URL="https://<token-name>:<token>@gitlab.seanergys.fz-juelich.de/api/v4/groups/158/-/packages/pypi/simple"
```

Persist it instead of exporting it in every shell by adding the same assignment to `pip.conf` (`extra-index-url`) or your shell profile.

## 2. Install or update Seanerstack

```console
pip install --upgrade seanerstack
```

`seanervault` is a dependency of `seanerstack`, so pip installs it automatically from the same extra index.

## 3. Initialize Seanerstack

Choose the persistent directory in which Seanerstack will keep Spack configuration and mutable state, then bootstrap the compiler, configure build-cache/OCI registry access, and validate the result in one step:

```console
export SEANERSTACK_STATE_DIR=/path/to/seanerstack-state
seanerstack --secrets-file secrets.toml init gcc@15
```

The directory contains Seanerstack's private Spack configuration, install store, stages, caches, and managed environments. Seanerstack does not implicitly use `$HOME` for this state, and there is no `spack repo add` step: Seanerstack installs its curated repository into the private configuration itself.

`--secrets-file` is only required when `config.toml` declares build caches that need credentials (see the project README's "External resources and secrets" section). Omit it, or pass `--skip-buildcache-check`, when none do.

## Activate the setup

```console
eval "$(seanerstack activate)"
```

Spack is now prepared for SEANERGYS work. Use plain `spack` commands for package development, installation, and deployment. They use the selected Seanerstack state rather than normal user or system Spack configuration.

Leave the session with:

```console
eval "$(seanerstack deactivate)"
```
