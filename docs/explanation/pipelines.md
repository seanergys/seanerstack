# CI pipelines

Every change reaches the default branch through a merge request and a merge train. The merge train tests each merge request on top of the default branch and of the merge requests ahead of it in the train, so the default branch receives exactly the commits that passed. The pipeline of the default branch then only publishes.

## Which job runs where

| Job | Merge request | Branch without merge request | Default branch | Tag | Schedule |
| --- | :---: | :---: | :---: | :---: | :---: |
| `test` | ✔ | ✔ | ✔ | ✔ | |
| `e2e:install`, `e2e:credentials`, `e2e:init`, `e2e:buildcache` | ✔ | | | | ✔ |
| `e2e:external-compiler` | ✔ | | | | ✔ |
| `build:rocky10` | ✔ | ✔ | ✔ | ✔ | |
| `docs` | ✔ | ✔ | ✔ | | |
| `pages` | | | ✔ | | |
| `publish:dev` | | | ✔ | | |
| `publish` | | | | ✔ | |

- **Merge request** pipelines decide whether a change may be merged. Once the project enables them, they run as merged results pipelines, on the merge request merged into the default branch, and as merge train pipelines.
- **Branch** pipelines give quick feedback on a branch before its merge request opens. A branch with an open merge request runs only the merge request pipeline.
- **Default branch** pipelines publish the documentation and a [development build](releases.md#development-builds). `test` runs first as a cheap check.
- **Tag** pipelines publish a [release](releases.md#release-process) after `test`.
- **Schedules** run the `e2e:*` jobs against the default branch every night. It notices when Spack or the GitLab instance changes while the default branch stays the same. A pipeline run by hand on the default branch, from **Build → Pipelines → Run pipeline**, runs them as well.

`e2e:external-compiler` runs `init` and `toolchain bootstrap --external` in Ubuntu 26.04 with its GCC 16 packages and in Ubuntu 24.04 with its GCC 14 packages, choosing the GCC that `init` found by name, builds a small package with that compiler, and checks that a GCC the image does not have is refused. It needs no token or registry.

Each `e2e:*` job runs one file of `tests/e2e`, so the areas run in parallel and a failure names its area. `e2e:buildcache` pushes into registry repositories named after each test, so those jobs take turns through the `e2e-registry` resource group. Merge train pipelines run side by side and would otherwise overwrite each other's build-cache index. The other `e2e:*` jobs only read the registry and need no turn.

## Building every package

`build:rocky10` builds every recipe of the repository on Rocky Linux 10, in every pipeline but the schedule, the way a user's machine does: `seanerstack init`, `seanerstack toolchain bootstrap`, then one environment with the default spec of each recipe. It installs what the project build cache holds, so a pipeline builds only what its change touches. Only the default branch pushes what it built and rebuilds the index; merge requests read the cache but put nothing into it. The private recipes are cloned with the job token, so each project they come from has to allow this project's job token under **Settings → CI/CD → Job token permissions**.

## Project settings

The merge train needs these settings, under **Settings → Merge requests**:

- **Merged results pipelines** enabled.
- **Merge trains** enabled.
- **Pipelines must succeed** enabled.
- **Allow skipping the merge train** disabled, so that every commit on the default branch has passed `e2e`.
