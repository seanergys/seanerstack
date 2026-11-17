# Set up a SEANERGYS system from scratch

This tutorial establishes the supported SEANERGYS software setup on a new Linux system. It ends with the Seanerstack state set up, its `spack` on `PATH`, and a package checkout whose dependencies are installed through Spack.

The procedure assumes Bash, Git, and a working system compiler are already provided by the operating system. The system compiler is used only to bootstrap the compiler that SEANERGYS uses through Spack.

The example package is `properdocs`.

## 1. Configure pipx for the SEANERGYS package registry

Seanerstack is published to the SEANERGYS GitLab group's PyPI registry, which requires authentication even for read access. Create a GitLab personal, project, or group access token with at least the `read_api` scope, then point the installer at the registry as an extra index. [pipx](https://pipx.pypa.io/) uses `uv` or `pip` as its installer backend depending on its version, and they read different variables, so set both:

```console
export PIP_EXTRA_INDEX_URL="https://<token-name>:<token>@gitlab.seanergys.fz-juelich.de/api/v4/groups/158/-/packages/pypi/simple"
export UV_EXTRA_INDEX_URL="$PIP_EXTRA_INDEX_URL"
```

Persist it instead of exporting it in every shell by adding the same assignments to your shell profile.

## 2. Install the latest Seanerstack

```console
pipx install --python python3.12 --include-deps seanerstack
```

Seanerstack requires Python 3.12 or newer. Pass `--python` explicitly: without it, pipx uses the system `python3`, which may be older.

Use pipx rather than a plain `pip install`. Without a virtual environment, pip silently falls back to a `--user` installation on hosts where you cannot write to the system site-packages, and Seanerstack cannot find its shared data in that layout. pipx installs into an isolated virtual environment and needs no root access. Inside a virtual environment that you manage yourself, `pip install --upgrade seanerstack` works as well.

If pipx is not available, for example on the login node of a cluster, install with [uv](https://docs.astral.sh/uv/) instead. It reads `UV_EXTRA_INDEX_URL` from step 1 and downloads Python 3.12 itself when the system one is older:

```console
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv tool install --python 3.12 --with-executables-from keyloom seanerstack
```

Update it with `uv tool upgrade seanerstack`.

`--include-deps` (`--with-executables-from keyloom` for uv) also puts the `keyloom` command on the PATH, which you need for the secrets file. pipx and uv otherwise expose only the commands of the package itself.

Its dependencies, including `keyloom`, come from PyPI. Seanerstack installs its curated Spack repository and environments under its installation prefix in `share/seanerstack`. The `seanerstack` command exposes their installed paths, so users do not need to locate that directory themselves.

## 3. Prepare the state directory

Seanerstack keeps the complete mutable Spack setup in one state directory, by default `/opt/seanergys/state`: its own Spack, the private configuration, install store, stages, caches, and managed environments. Use that directory, because every binary hash contains the install path of the compiler that built it, and only that directory matches the binaries of the project build cache:

```console
sudo mkdir -p /opt/seanergys/state
sudo chown "$USER" /opt/seanergys/state
```

There is no separate Spack to install: Seanerstack clones the Spack version it pins into this directory, and refuses another version, because a different Spack produces hashes and build-cache formats that the project cache does not hold. Do not register Seanerstack in the normal user Spack configuration either; Seanerstack supplies its repository through the isolated configuration it creates.

## 4. Initialize Seanerstack

Set up the state and check access to every resource, in one step:

```console
seanerstack --secrets-file secrets.toml init
```

`init` installs the pinned Spack, records the configuration and stores the credentials of the secrets file in the state directory, readable only by you. It configures the build caches and the CPU target of `[toolchain]`, `x86_64_v3`, and checks that every build cache and Git resource can be read. It installs no compiler. Fix any reported errors and run `init` again before proceeding. No later command needs any of these options again.

The secrets file holds the token for the SEANERGYS GitLab and its container registry (see [Create a secrets file](../how-to/create-a-secrets-file.md)). Seanerstack asks for its keyloom vault password. When there is no terminal to answer the prompt (over `ssh host 'command'`, in a script or in CI), the command fails with `EOFError`; supply the password with `--secrets-password-file FILE` or `--secrets-password-stdin` instead (see [Supply the vault password without a prompt](../how-to/create-a-secrets-file.md#supply-the-vault-password-without-a-prompt)).

## 5. Put the state's spack on PATH

`init` ends by printing the line that puts the state's `spack` first on `PATH`. Add it to `~/.bashrc` and run it in the current shell:

```console
export PATH=/opt/seanergys/state/spack/bin:$PATH
```

From this point, plain `spack` uses the Seanerstack configuration, state and credentials, in this shell and every later one. Existing `~/.spack` or system Spack configuration is not part of it. To use the state in the current shell only, run `eval "$(seanerstack activate)"` instead.

## 6. Install the toolchain

```console
seanerstack toolchain bootstrap
```

It installs the compiler of `[toolchain]` and makes it the compiler of every later build, then installs rust and capnproto with it. Each comes from the project build cache where the cache holds it, so GCC and Rust, which take hours to build, are not built here. Seanerstack uses the compiler package supplied by Spack; it does not ship a GCC recipe of its own.

## 7. Obtain the package checkout

For this tutorial:

```console
mkdir -p /path/to/src
git clone https://github.com/ProperDocs/properdocs.git /path/to/src/properdocs
cd /path/to/src/properdocs
```

## 8. Activate the environment shipped by Seanerstack

Activate the development environment associated with the package. The state's `spack` has no Spack shell integration, so activate through the shell code that Spack prints:

```console
eval "$(spack env activate --sh "$(seanerstack paths env --package properdocs)")"
```

The environment is an ordinary Spack environment supplied by Seanerstack. Its concretization and installations use only the private Spack state.

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

Nothing needs to be set up again. In a new shell:

```console
cd /path/to/src/properdocs
eval "$(spack env activate --sh "$(seanerstack paths env --package properdocs)")"
```

Then use normal Spack commands as needed. Leave the environment with:

```console
eval "$(spack env deactivate --sh)"
```
