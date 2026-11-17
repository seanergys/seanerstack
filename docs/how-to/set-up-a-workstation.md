# Set up Spack for SEANERGYS

Use this procedure when preparing a machine for SEANERGYS work. For a completely new machine, follow the tutorial instead. Seanerstack installs the Spack it needs itself.

## 1. Configure pipx for the SEANERGYS package registry

Seanerstack is published to the SEANERGYS GitLab group's PyPI registry, which requires authentication even for read access. Create a GitLab personal, project, or group access token with at least the `read_api` scope, then point the installer at the registry as an extra index. [pipx](https://pipx.pypa.io/) uses `uv` or `pip` as its installer backend depending on its version, and they read different variables, so set both:

```console
export PIP_EXTRA_INDEX_URL="https://<token-name>:<token>@gitlab.seanergys.fz-juelich.de/api/v4/groups/158/-/packages/pypi/simple"
export UV_EXTRA_INDEX_URL="$PIP_EXTRA_INDEX_URL"
```

Persist it instead of exporting it in every shell by adding the same assignments to your shell profile.

## 2. Install or update Seanerstack

```console
pipx install --python python3.12 --include-deps seanerstack
```

To update an existing installation, run `pipx upgrade seanerstack`.

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

Its dependencies, including `keyloom`, come from PyPI.

## 3. Prepare the state directory

Seanerstack keeps its Spack, configuration, install store, stages, caches, and managed environments in one state directory, by default `/opt/seanergys/state`. Use that directory: every binary hash contains the install path of the compiler that built it, so only a machine with the same state directory reuses the binaries of the project build cache. Create it once and make it yours:

```console
sudo mkdir -p /opt/seanergys/state
sudo chown "$USER" /opt/seanergys/state
```

Another directory can be given with `--state-dir DIR` or `SEANERSTACK_STATE_DIR`, but then nothing from the project build cache matches.

## 4. Initialize Seanerstack

```console
seanerstack --secrets-file secrets.toml init
```

`init` sets up the state so that no later command needs another option:

- it installs the Spack version that Seanerstack pins into the state directory;
- it records the `config.toml` (the shipped one, or the one given with `--config-file`) and stores the credentials of `--secrets-file` in the state directory, readable only by you;
- it configures the build caches of `config.toml` and the CPU target of `[toolchain]`, `x86_64_v3`, for every package;
- it checks that every build cache and every Git resource can be read.

It installs no compiler. Fix any reported access error and run `init` again; running it again is also how any of these choices is changed later.

`--secrets-file` is needed for the SEANERGYS GitLab and the project build cache (see [Create a secrets file](create-a-secrets-file.md)). With it, Seanerstack asks for the keyloom vault password. Over `ssh host 'command'`, in a script or in CI there is no terminal to answer the prompt, and the command fails with `EOFError`. Supply the password with `--secrets-password-file FILE` or `--secrets-password-stdin` instead (see [Supply the vault password without a prompt](create-a-secrets-file.md#supply-the-vault-password-without-a-prompt)).

Seanerstack uses its pinned Spack, and refuses one given with `--spack-executable` or `SEANERSTACK_REAL_SPACK` that has another version: a different Spack writes build-cache indexes and specs that the pinned one cannot read, and its hashes match nothing in the cache. `seanerstack --version` names both versions.

## 5. Put the state's spack on PATH

`init` ends by printing the line that puts the state's `spack` wrapper first on `PATH`. Add it to your shell profile, such as `~/.bashrc`:

```console
export PATH=/opt/seanergys/state/spack/bin:$PATH
```

Plain `spack` commands then use the Seanerstack state in every shell, with its credentials, and not the normal user or system Spack configuration. See [Use the state's Spack](use-the-states-spack.md).

## 6. Install the compiler

```console
seanerstack toolchain bootstrap
```

It installs the compiler of `[toolchain]` in `config.toml`, from the project build cache where the cache holds it, and makes it the compiler of every later build. Spack is now prepared for SEANERGYS work.
