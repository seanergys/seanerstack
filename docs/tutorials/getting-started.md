# Set up a SEANERGYS system from scratch

This tutorial establishes the supported SEANERGYS software setup on a new Linux system. It ends with an isolated Seanstack Spack session and a package checkout whose dependencies are installed through Spack.

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

Obtain the Spack executable used by Seanstack. The Spack checkout itself may live anywhere convenient; Seanstack isolates Spack's mutable configuration and state rather than requiring the executable to be installed inside the state directory.

For example:

```console
git clone --depth=1 https://github.com/spack/spack.git /path/to/spack
export PATH="/path/to/spack/bin:$PATH"
```

Do not register Seanstack in the normal user Spack configuration. Seanstack supplies its repository through the isolated configuration it creates.

## 4. Choose the Seanstack state directory

Select the directory that will contain the complete mutable Spack state for this Seanstack setup:

```console
export SEANSTACK_STATE_DIR=/path/to/seanstack-state
```

Seanstack deliberately does not default this state to `$HOME`. The directory will contain the private Spack configuration, install store, stages, caches, and managed environments.

## 5. Bootstrap the SEANERGYS compiler

Prepare the isolated Spack setup to use the project compiler:

```console
seanstack toolchain bootstrap gcc@15
```

Seanstack uses the compiler package supplied by Spack; it does not ship a GCC recipe of its own. The initially available system compiler is used to build GCC when necessary, after which the isolated Seanstack configuration requires the Spack-installed GCC for SEANERGYS builds.

## 6. Verify the setup

Run the standard validation against the same private state:

```console
seanstack validate --compiler gcc@15 --spack
```

Fix validation failures before proceeding.

## 7. Activate the isolated Spack session

Activate Seanstack before using Spack directly:

```console
eval "$(seanstack activate)"
```

From this point, plain `spack` uses the Seanstack configuration and state selected by `SEANSTACK_STATE_DIR`. Existing `~/.spack` or system Spack configuration is not part of this session.

## 8. Obtain the package checkout

For this tutorial:

```console
mkdir -p /path/to/src
git clone https://github.com/ProperDocs/properdocs.git /path/to/src/properdocs
cd /path/to/src/properdocs
```

## 9. Activate the environment shipped by Seanstack

Activate the development environment associated with the package:

```console
spack env activate "$(seanstack paths env --package properdocs)"
```

The environment is an ordinary Spack environment supplied by Seanstack. The active Seanstack session ensures that its concretization and installations use only the selected private Spack state.

## 10. Bind the local checkout

Tell Spack that `properdocs@master` is provided by the checkout you just cloned:

```console
spack develop --path "$PWD" properdocs@master
```

The checkout path is machine-local state, so it is deliberately not stored in Seanstack.

## 11. Concretize and install

Use Spack normally:

```console
spack concretize -f
spack install
```

The system is now ready for work on the package.

## Subsequent work sessions

Set the same state directory and reactivate Seanstack before invoking Spack:

```console
export SEANSTACK_STATE_DIR=/path/to/seanstack-state
eval "$(seanstack activate)"
cd /path/to/src/properdocs
spack env activate "$(seanstack paths env --package properdocs)"
```

Then use normal Spack commands as needed. When finished with the Seanstack session:

```console
eval "$(seanstack deactivate)"
```
