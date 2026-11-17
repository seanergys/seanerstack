# Work on a package

Use this procedure to build a SEANERGYS package from a local checkout. It assumes that the state is set up, the toolchain is installed and the state's `spack` is on `PATH`, as after the [tutorial](../tutorials/getting-started.md).

The example package is `properdocs`. Every command on this page comes from `tests/how-to/work-on-a-package.sh`, which the `how-to:work-on-a-package` job of the CI pipeline runs from start to end, so the procedure is tested with every change.

## 1. Get the checkout

Clone the package and change into the checkout. `$SOURCES` is the directory where you keep your sources:

```bash
--8<-- "tests/how-to/work-on-a-package.sh:checkout"
```

## 2. Activate the package environment

Seanerstack ships a Spack environment for the development of each package, and `seanerstack paths env` prints where it is. The state's `spack` has no shell integration, so activate the environment through the shell code that Spack prints:

```bash
--8<-- "tests/how-to/work-on-a-package.sh:activate"
```

## 3. Bind the checkout

Tell Spack that `properdocs@master` is built from the checkout:

```bash
--8<-- "tests/how-to/work-on-a-package.sh:develop"
```

The path of a checkout differs between machines, so it is recorded on your machine and not in Seanerstack.

## 4. Build and install

```bash
--8<-- "tests/how-to/work-on-a-package.sh:install"
```

Spack takes the dependencies from the build cache and builds `properdocs` from the checkout. After a change to the sources, the recipe or the dependencies, run the two commands again.

The installed package names the checkout it was built from:

```bash
--8<-- "tests/how-to/work-on-a-package.sh:check"
```

```text
properdocs@master dev_path=/home/you/src/properdocs
```

## 5. Leave the environment

```bash
--8<-- "tests/how-to/work-on-a-package.sh:deactivate"
```

In a later shell, change into the checkout and repeat step 2; the binding and the installation are still there.

## Add the package to seanergys-meta

`seanergys-meta` is the package that brings in the SEANERGYS software stack, and the `build:rocky10` job builds it in every pipeline. A new recipe is not part of it at first, so a recipe that does not build yet does not fail the pipelines of everyone else. Once the package builds with the project toolchain on Rocky Linux 10, add it to `packages/seanergys_meta/package.py`, in alphabetical order:

```python
    depends_on("properdocs", type="run")
```

From then on every pipeline builds it, and the default branch puts it into the project build cache.
