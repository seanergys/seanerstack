# CI pipelines

Every change reaches the default branch through a merge request and a merge train. The merge train tests each merge request on top of the default branch and of the merge requests ahead of it in the train, so the default branch receives exactly the commits that passed. The pipeline of the default branch then only publishes.

## Which job runs where

| Job | Merge request | Branch without merge request | Default branch | Tag | Schedule |
| --- | :---: | :---: | :---: | :---: | :---: |
| `test` | ✔ | ✔ | ✔ | ✔ | |
| `e2e` | ✔ | | | | ✔ |
| `e2e:external-compiler` | ✔ | | | | ✔ |
| `docs` | ✔ | ✔ | ✔ | | |
| `pages` | | | ✔ | | |
| `publish:dev` | | | ✔ | | |
| `publish` | | | | ✔ | |

- **Merge request** pipelines decide whether a change may be merged. Once the project enables them, they run as merged results pipelines, on the merge request merged into the default branch, and as merge train pipelines.
- **Branch** pipelines give quick feedback on a branch before its merge request opens. A branch with an open merge request runs only the merge request pipeline.
- **Default branch** pipelines publish the documentation and a [development build](releases.md#development-builds). `test` runs first as a cheap check.
- **Tag** pipelines publish a [release](releases.md#release-process) after `test`.
- **Schedules** run `e2e` against the default branch every night. It notices when Spack or the GitLab instance changes while the default branch stays the same. A pipeline run by hand on the default branch, from **Build → Pipelines → Run pipeline**, runs `e2e` as well.

`e2e:external-compiler` runs `init` and `toolchain bootstrap --external` in Ubuntu 26.04 with its GCC 16 packages and in Ubuntu 24.04 with its GCC 14 packages, choosing the GCC that `init` found by name, builds a small package with that compiler, and checks that a GCC the image does not have is refused. It needs no token or registry.

`e2e` pushes into registry repositories named after each test, so `e2e` jobs take turns through the `e2e-registry` resource group. Merge train pipelines run side by side and would otherwise overwrite each other's build-cache index.

## Project settings

The merge train needs these settings, under **Settings → Merge requests**:

- **Merged results pipelines** enabled.
- **Merge trains** enabled.
- **Pipelines must succeed** enabled.
- **Allow skipping the merge train** disabled, so that every commit on the default branch has passed `e2e`.
