# Set up a SEANERGYS system from scratch

This tutorial establishes the supported SEANERGYS software setup on a new Linux system. It ends with an isolated Seanerstack Spack session and a package checkout whose dependencies are installed through Spack.

The procedure assumes Bash, Git, and a working system compiler are already provided by the operating system. The system compiler is used only to bootstrap the compiler that SEANERGYS uses through Spack.

The example package is `properdocs`.

## 1. Configure pip for the SEANERGYS package registry

Seanerstack is published to the SEANERGYS GitLab group's PyPI registry, which requires authentication even for read access. Create a GitLab personal, project, or group access token with at least the `read_api` scope, then point pip at the registry as an extra index:

```console
export PIP_EXTRA_INDEX_URL="https://<token-name>:<token>@gitlab.seanergys.fz-juelich.de/api/v4/groups/158/-/packages/pypi/simple"
```

Persist it instead of exporting it in every shell by adding the same assignment to `pip.conf` (`extra-index-url`) or your shell profile.

## 2. Install the latest Seanerstack

```console
pip install --upgrade seanerstack
```

Its dependencies, including `keyloom` for the secrets file, come from PyPI. Seanerstack installs its curated Spack repository and environments under its installation prefix in `share/seanerstack`. The `seanerstack` command exposes their installed paths, so users do not need to locate that directory themselves.

## 3. Install Spack

Obtain the Spack executable used by Seanerstack. The Spack checkout itself may live anywhere convenient; Seanerstack isolates Spack's mutable configuration and state rather than requiring the executable to be installed inside the state directory.

For example:

```console
git clone --depth=1 https://github.com/spack/spack.git /path/to/spack
export PATH="/path/to/spack/bin:$PATH"
```

Do not register Seanerstack in the normal user Spack configuration. Seanerstack supplies its repository through the isolated configuration it creates.

## 4. Choose the Seanerstack state directory

Select the directory that will contain the complete mutable Spack state for this Seanerstack setup:

```console
export SEANERSTACK_STATE_DIR=/path/to/seanerstack-state
```

Seanerstack deliberately does not default this state to `$HOME`. The directory will contain the private Spack configuration, install store, stages, caches, and managed environments.

## 5. Initialize Seanerstack

Bootstrap the project compiler, configure build-cache/OCI registry access, and validate the result, all in one step:

```console
seanerstack init gcc@15
```

Seanerstack uses the compiler package supplied by Spack; it does not ship a GCC recipe of its own. The initially available system compiler is used to build GCC when necessary, after which the isolated Seanerstack configuration requires the Spack-installed GCC for SEANERGYS builds. Fix any reported errors before proceeding.

If `config.toml` declares build caches that need credentials, pass `--secrets-file secrets.toml` (see the project README's "External resources and secrets" section); otherwise omit it, or add `--skip-buildcache-check`.

## 6. Activate the isolated Spack session

Activate Seanerstack before using Spack directly:

```console
eval "$(seanerstack activate)"
```

From this point, plain `spack` uses the Seanerstack configuration and state selected by `SEANERSTACK_STATE_DIR`. Existing `~/.spack` or system Spack configuration is not part of this session.

## 7. Obtain the package checkout

For this tutorial:

```console
mkdir -p /path/to/src
git clone https://github.com/ProperDocs/properdocs.git /path/to/src/properdocs
cd /path/to/src/properdocs
```

## 8. Activate the environment shipped by Seanerstack

Activate the development environment associated with the package:

```console
spack env activate "$(seanerstack paths env --package properdocs)"
```

The environment is an ordinary Spack environment supplied by Seanerstack. The active Seanerstack session ensures that its concretization and installations use only the selected private Spack state.

## 9. Bind the local checkout

Tell Spack that `properdocs@master` is provided by the checkout you just cloned:

```console
spack develop --path "$PWD" properdocs@master
```

The checkout path is machine-local state, so it is deliberately not stored in Seanerstack.

## 10. Concretize and install

Use Spack normally:

```console
spack concretize -f
spack install
```

The system is now ready for work on the package.

## Subsequent work sessions

Set the same state directory and reactivate Seanerstack before invoking Spack:

```console
export SEANERSTACK_STATE_DIR=/path/to/seanerstack-state
eval "$(seanerstack activate)"
cd /path/to/src/properdocs
spack env activate "$(seanerstack paths env --package properdocs)"
```

Then use normal Spack commands as needed. When finished with the Seanerstack session:

```console
eval "$(seanerstack deactivate)"
```
