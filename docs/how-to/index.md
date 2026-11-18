# How-to guides

Each guide gives one procedure for one task. Options beyond that procedure are in the [reference](../reference/index.md).

## Set up

| Guide | Task |
| --- | --- |
| [Set up a workstation](set-up-a-workstation.md) | Install Seanerstack, set up the state and install the toolchain, with the choices each step has. |
| [Create a secrets file](create-a-secrets-file.md) | Write and encrypt the file with the GitLab and registry tokens. |
| [Use the state's Spack](use-the-states-spack.md) | Run plain `spack` commands in the state, and keep the state in another directory. |

## Build

| Guide | Task |
| --- | --- |
| [Use the project build cache](use-the-build-cache.md) | Install from the cache, fill it for a platform, and find out why a package is built instead. |
| [Work on a package](work-on-a-package.md) | Build a package from a local checkout in its Seanerstack environment. |

## Maintain the stack

| Guide | Task |
| --- | --- |
| [Synchronize a package recipe](sync-a-package.md) | Bring the versions of a recipe up to its upstream repository. |
| [Validate Seanerstack changes](validate-the-stack.md) | Check recipes, environments and the compiler configuration before a merge request. |
