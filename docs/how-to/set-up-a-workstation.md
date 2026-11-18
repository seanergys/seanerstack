# Set up a workstation

Use this procedure to prepare a machine for SEANERGYS work when a step needs a choice that the [tutorial](../tutorials/getting-started.md) leaves out: another installer, a compiler off `PATH`, another state directory, or an update of an existing installation. The steps are those of the tutorial, each with its options.

## 1. Install or update Seanerstack

Seanerstack is on PyPI:

```console
pipx install --python python3.12 --include-deps seanerstack
```

To update an existing installation, run `pipx upgrade seanerstack`.

Seanerstack requires Python 3.12 or newer. Pass `--python` explicitly: without it, pipx uses the system `python3`, which may be older.

Use pipx rather than a plain `pip install`. Without a virtual environment, pip silently falls back to a `--user` installation on hosts where you cannot write to the system site-packages, and Seanerstack cannot find its shared data in that layout. pipx installs into an isolated virtual environment and needs no root access. Inside a virtual environment that you manage yourself, `pip install --upgrade seanerstack` works as well.

If pipx is not available, for example on the login node of a cluster, install with [uv](https://docs.astral.sh/uv/) instead. It downloads Python 3.12 itself when the system one is older:

```console
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
uv tool install --python 3.12 --with-executables-from keyloom seanerstack
```

Update it with `uv tool upgrade seanerstack`.

`--include-deps` (`--with-executables-from keyloom` for uv) also puts the `keyloom` command on the PATH, which you need for the secrets file. pipx and uv otherwise expose only the commands of the package itself.

## 2. Prepare the state directory

Seanerstack keeps its Spack, configuration, install store, stages, caches, and managed environments in one state directory, by default `/opt/seanergys/state`. Use that directory: every binary hash contains the install path of the compiler that built it, so only a machine with the same state directory reuses the binaries of the project build cache. Create it once and make it yours:

```console
export SEANERSTACK_STATE_DIR=/opt/seanergys/state
sudo mkdir -p "$SEANERSTACK_STATE_DIR"
sudo chown "$USER" "$SEANERSTACK_STATE_DIR"
```

`SEANERSTACK_STATE_DIR` names the state directory for every `seanerstack` command, and `--state-dir DIR` does the same for one command. Unset, it is `/opt/seanergys/state`. To keep the state elsewhere, set another directory here and in your shell profile; nothing from the project build cache matches then, and Spack builds from source (see [Keep the state in another directory](use-the-states-spack.md#keep-the-state-in-another-directory)).

## 3. Initialize Seanerstack

```console
seanerstack --secrets-file secrets.toml init
```

`init` sets up the state so that no later command needs another option:

- it installs the Spack version that Seanerstack pins into the state directory;
- it records the `config.toml` (the shipped one, or the one given with `--config-file`) and stores the credentials of `--secrets-file` in the state directory, readable only by you;
- it configures the build caches of `config.toml` and the CPU target of `[toolchain]`, `x86_64_v3`, for every package;
- it finds the compilers on the machine and registers them, and finds the toolchain's packages, such as rust, without registering them; it prints both lists;
- it checks that every build cache and every Git resource can be read.

```text
compilers found:
  gcc@11.5.0  /usr
  gcc@14.2.1  /opt/rh/gcc-toolset-14/root/usr
packages found:
  rust@1.97.1  /usr
```

A compiler off `PATH`, such as a gcc-toolset, is found with `--find /opt/rh/gcc-toolset-14/root/usr`; `init` remembers the prefix. It installs no compiler. Fix any reported access error and run `init` again; running it again is also how any of these choices is changed later.

`--secrets-file` is needed for the SEANERGYS GitLab and the project build cache (see [Create a secrets file](create-a-secrets-file.md)). With it, Seanerstack asks for the keyloom vault password. Over `ssh host 'command'`, in a script or in CI there is no terminal to answer the prompt, and the command fails with `EOFError`. Supply the password with `--secrets-password-file FILE` or `--secrets-password-stdin` instead (see [Supply the vault password without a prompt](create-a-secrets-file.md#supply-the-vault-password-without-a-prompt)).

Seanerstack uses its pinned Spack, and refuses one given with `--spack-executable` or `SEANERSTACK_REAL_SPACK` that has another version: a different Spack writes build-cache indexes and specs that the pinned one cannot read, and its hashes match nothing in the cache. `seanerstack --version` names both versions.

## 4. Activate the state

```console
eval "$(seanerstack activate)"
```

`spack` is then the Spack of the state in this shell, with its configuration and credentials. Other shells keep whatever Spack they had. Run the line in each shell that works with the state, and leave it with `eval "$(seanerstack deactivate)"`. See [Use the state's Spack](use-the-states-spack.md).

## 5. Install the toolchain

```console
seanerstack toolchain bootstrap
```

It installs the compiler of `[toolchain]` in `config.toml` and makes it the compiler of every later build, then installs the toolchain's packages with it, rust and capnproto. Each comes from the project build cache where the cache holds it, so the hours that GCC and Rust take to build are spent once, in CI. Spack is now prepared for SEANERGYS work.

The defaults suit almost everyone. `--compiler` builds another compiler, `--source-compiler gcc@14` builds it with a compiler that `init` found, `--target` and `--os` set the CPU target and the operating system to expect, and package names as arguments install only those. `--external` uses a compiler or package that `init` found instead of building it; see the warning in [Use the build cache](use-the-build-cache.md#install-from-the-cache).
