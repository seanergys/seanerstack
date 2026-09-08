# Set up a SEANERGYS system from scratch

This tutorial establishes the supported SEANERGYS software setup on a new Linux system. It starts with the base operating system and ends with a package checkout whose dependencies are installed through Spack.

The procedure assumes Bash, Git, and a working system compiler are already provided by the operating system. The system compiler is used only to bootstrap the compiler that SEANERGYS uses through Spack.

The example package is `properdocs`.

## 1. Install uv

Install uv using its standard installer:

```console
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Start a new shell so `uv` is on `PATH`.

## 2. Install the latest Seanstack

Install Seanstack as a uv tool:

```console
uv tool install seanstack@latest
```

Seanstack installs its curated Spack repository and environments under its installation prefix in `share/seanstack`. The `seanstack` command exposes their installed paths, so users do not need to locate that directory themselves.

## 3. Install Spack

Install Spack in the standard SEANERGYS location:

```console
git clone --depth=1 https://github.com/spack/spack.git "$HOME/.local/share/spack"
```

Configure Bash to make this Spack installation available in future shells:

```console
printf '\nsource "$HOME/.local/share/spack/share/spack/setup-env.sh"\n' >> "$HOME/.bashrc"
source "$HOME/.local/share/spack/share/spack/setup-env.sh"
```

From this point onward, Spack is the interface used for normal dependency and environment operations.

## 4. Register the Seanstack package repository

Make the curated SEANERGYS recipes available to Spack:

```console
spack repo add "$(seanstack paths repo)"
```

This is a one-time operation for this Spack installation.

## 5. Bootstrap the SEANERGYS compiler

Prepare Spack to use the project compiler:

```console
seanstack toolchain bootstrap gcc@15
```

Seanstack uses the compiler package supplied by Spack; it does not ship a GCC recipe of its own. The initially available system compiler is used to build GCC when necessary, after which Spack uses the Spack-installed GCC for SEANERGYS builds.

## 6. Verify the setup

Run the standard validation:

```console
seanstack validate --compiler gcc@15 --spack
```

Fix validation failures before proceeding.

## 7. Obtain the package checkout

For this tutorial:

```console
mkdir -p "$HOME/src"
git clone https://github.com/ProperDocs/properdocs.git "$HOME/src/properdocs"
cd "$HOME/src/properdocs"
```

## 8. Activate the environment shipped by Seanstack

Activate the development environment associated with the package:

```console
spack env activate "$(seanstack paths env --package properdocs)"
```

The environment is an ordinary Spack environment supplied by Seanstack. Seanstack does not proxy subsequent Spack operations.

## 9. Bind the local checkout

Tell Spack that `properdocs@develop` is provided by the checkout you just cloned:

```console
spack develop --path "$PWD" properdocs@develop
```

The checkout path is machine-local state, so it is deliberately not stored in Seanstack.

## 10. Concretize and install

Use Spack normally:

```console
spack concretize -f
spack install
```

The system is now ready for work on the package.

## Subsequent work sessions

The workstation setup, repository registration, and compiler bootstrap are not repeated for every session. Start by entering the checkout and activating its environment:

```console
cd "$HOME/src/properdocs"
spack env activate "$(seanstack paths env --package properdocs)"
```

Then use normal Spack commands as needed.
