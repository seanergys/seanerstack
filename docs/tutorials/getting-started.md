# Install the SEANERGYS stack

This tutorial takes a new Linux machine to the installed SEANERGYS software stack in five steps. Each step is one or two commands.

You need:

| Requirement | Detail |
| --- | --- |
| A Linux machine | With Bash, Git, a C, C++ and Fortran compiler, Python 3.12 or newer, and [pipx](https://pipx.pypa.io/). |
| A GitLab access token | For the SEANERGYS GitLab, with the scopes that [Create a secrets file](../how-to/create-a-secrets-file.md#1-write-the-credential-entries) names. |
| A secrets file | `secrets.toml` with that token, written as the same guide describes. |

## 1. Install Seanerstack

Seanerstack is on PyPI. Install it with pipx:

```console
pipx install --python python3.12 --include-deps seanerstack
```

`--include-deps` also installs the `keyloom` command, which encrypts the secrets file.

## 2. Set up the state

Seanerstack keeps its Spack, the configuration, the installed software and the caches in one state directory, which `SEANERSTACK_STATE_DIR` names. Create it and make it yours, then let `init` set it up:

```console
export SEANERSTACK_STATE_DIR=/opt/seanergys/state
sudo mkdir -p "$SEANERSTACK_STATE_DIR"
sudo chown "$USER" "$SEANERSTACK_STATE_DIR"
seanerstack --secrets-file secrets.toml init
```

`init` asks for the password of the secrets file. It installs the Spack version that Seanerstack pins, stores the credentials, configures the project build cache, and checks that every build cache and Git repository can be read. If it reports an access error, correct the token and run it again.

!!! note "Why this directory"
    `/opt/seanergys/state` is also the directory Seanerstack uses when the variable is unset. Every binary in the build cache contains the path of the compiler that built it, so only a state there reuses those binaries. With another directory in `SEANERSTACK_STATE_DIR` everything works the same, but Spack builds the toolchain and the stack from source; set the variable in your shell profile then, so every shell names the same state.

## 3. Activate the state

```console
eval "$(seanerstack activate)"
```

In this shell, `spack` is now the Spack of the Seanerstack state, with its configuration and credentials. Every other shell is unchanged, so another Spack on the machine keeps working there. Run the same line in each new shell that works with the state, and leave it with `eval "$(seanerstack deactivate)"`.

## 4. Install the toolchain

```console
seanerstack toolchain bootstrap
```

This installs the project compiler, GCC 15, and makes it the compiler of every later build. It then installs Rust and Cap'n Proto. All three come from the build cache, so the step takes minutes.

## 5. Install the stack

```console
spack install seanergys-meta
```

`seanergys-meta` depends on every package of the SEANERGYS stack that builds with the project toolchain. On Rocky Linux 10, where the CI pipeline builds it, Spack takes the packages from the build cache. On another system Spack builds them, and clones the SEANERGYS repositories with your own Git access.

List what is installed:

```console
spack find
```

The stack is installed, and the machine is set up for SEANERGYS work.

## Next steps

| Goal | Page |
| --- | --- |
| Change a package and build it from your checkout | [Work on a package](../how-to/work-on-a-package.md) |
| Choose another installer, state directory or compiler | [Set up a workstation](../how-to/set-up-a-workstation.md) |
| Have the state's Spack in every shell, or keep the state in another directory | [Use the state's Spack](../how-to/use-the-states-spack.md) |
| Find out why Spack builds a package that the cache should hold | [Use the project build cache](../how-to/use-the-build-cache.md#find-out-why-a-package-is-not-taken-from-the-cache) |
| Understand how the state stays apart from other Spack setups | [Isolation](../explanation/isolation.md) |
