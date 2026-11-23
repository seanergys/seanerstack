# Seanerstack

Seanerstack provides the Spack setup that SEANERGYS software is built with. It ships the project's Spack package recipes and environments, installs a pinned Spack into one state directory, and keeps that state apart from every other Spack configuration on the machine. Every workstation and CI job therefore computes the same hashes and takes its binaries from the project build cache.

Spack remains the tool that builds. Seanerstack sets the state up once, and from then on plain `spack` commands install and develop the software:

```console
seanerstack --secrets-file secrets.toml init
seanerstack toolchain bootstrap
spack install seanergys-meta
```

`seanergys-meta` is the package that brings in the SEANERGYS software stack.

## Maintainers

| Maintainer | Affiliation | Contact |
| --- | --- | --- |
| Jayesh Badwaik | Forschungszentrum Jülich | <j.badwaik@fz-juelich.de> |
| Radek Lonka, who cuts the [releases](explanation/releases.md) | VSB – Technical University of Ostrava | <radek.lonka@vsb.cz> |

For a problem or a question, open an issue in the [repository](https://gitlab.seanergys.fz-juelich.de/software/seanerstack/-/issues), or write to either of them.

## How these docs are organized

The documentation follows four kinds of pages, each with one purpose.

| Section | Purpose | Start here when |
| --- | --- | --- |
| [Tutorials](tutorials/index.md) | Learning by doing, from a new machine to the installed SEANERGYS stack. | You have not used Seanerstack before. |
| [How-to guides](how-to/index.md) | One procedure for each task, such as working on a package checkout. | You know what you want to do. |
| [Explanation](explanation/index.md) | Why Seanerstack works the way it does, and what was decided. | You want to understand or change the design. |
| [Reference](reference/index.md) | Every command, environment and package recipe, generated from the installed Seanerstack. | You need the exact name or meaning of an option. |

## What Seanerstack provides

| Part | Responsibility |
| --- | --- |
| Package recipes | The Spack recipes of the SEANERGYS software, in a Spack repository of their own. |
| Environments | A Spack environment for the development of each package. |
| `seanerstack init` | Sets up the state directory once: the pinned Spack, the configuration, the credentials, the build caches and the CPU target. |
| `seanerstack toolchain bootstrap` | Installs the project compiler and the toolchain packages, from the build cache where it holds them. |
| The state's `spack` | Runs Spack with the state's configuration and credentials from any shell. |
| `seanerstack buildcache` | Checks, explains and fills the project build cache. |
| `seanerstack package update` and `seanerstack validate` | Keep the recipes aligned with their upstream repositories and check the stack. |

## Components

| Component | Responsibility |
| --- | --- |
| Seanerstack | Provides the recipes, the environments and the isolated Spack state. |
| Spack | Concretizes, builds and installs the software in that state. |
| keyloom | Encrypts the secrets file that holds the GitLab and registry tokens. |
