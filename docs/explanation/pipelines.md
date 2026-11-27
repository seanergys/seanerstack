# CI pipelines

Every change reaches the default branch through a merge request and a merge train. The merge train tests each merge request on top of the default branch and of the merge requests ahead of it in the train, so the default branch receives exactly the commits that passed. The pipeline of the default branch then only publishes.

## Which job runs where

| Job | Merge request | Branch without merge request | Default branch | Tag | Schedule |
| --- | :---: | :---: | :---: | :---: | :---: |
| `test` | ✔ | ✔ | ✔ | ✔ | |
| `e2e:install`, `e2e:credentials`, `e2e:init`, `e2e:buildcache` | ✔ | | | | ✔ |
| `e2e:external-compiler` | ✔ | | | | ✔ |
| `access` | ✔ | ✔ | ✔ | ✔ | ✔ |
| `build:rocky10` | ✔ | ✔ | ✔ | ✔ | |
| `tutorial:install-the-stack` | ✔ | ✔ | ✔ | ✔ | |
| `how-to:work-on-a-package` | ✔ | ✔ | ✔ | ✔ | |
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

`build:rocky10` builds `seanergys-meta` on Rocky Linux 10, in every pipeline but the schedule, the way a user's machine does: `seanerstack init`, `seanerstack toolchain bootstrap`, then an environment with that one package. Before it installs, it runs `seanerstack buildcache explain` for the compiler and the packages of `[toolchain]` and for `seanergys-meta`, so the log says why a pipeline builds what the build cache seems to hold; that step never fails the job. `seanergys-meta` depends on every recipe that builds with the project toolchain; a recipe that does not build yet stays out of it, and joins it once it does (see [Work on a package](../how-to/work-on-a-package.md#add-the-package-to-seanergys-meta)). It installs what the project build cache holds, so a pipeline builds only what its change touches. Every pipeline, merge requests included, pushes what it built and rebuilds the index with `seanerstack buildcache update-index`, which leaves out binaries the pinned Spack cannot read: a change is built once, and its merge train and the default branch install it. Binaries of a change that is never merged stay in the cache, with hashes that no recipe of the default branch produces. While the pipeline variable `PUBLISH_TOOLCHAIN` is `true`, which it is by default, `build:rocky10` then also runs `seanerstack toolchain publish`: the first stage of the compiler goes to the bootstrap cache and the compiler lockfile to the build cache, so that the pipelines after it find both. The same variable starts the `toolchain` job for every platform in every push and web pipeline, which publishes the same for each; a merge request pipeline offers it to start by hand. A platform that fails does not fail the pipeline. Any other value, set as a CI/CD variable of the project or of a pipeline, leaves the toolchain to the nightly schedule and to a pipeline run by hand, without a commit. When `init` finds the index unreadable, the pipeline rebuilds it and runs `init` again. The private recipes are cloned with the job token, which each job writes into its secrets file as a user writes their own token, so each project they come from has to allow this project's job token under **Settings → CI/CD → Job token permissions**. The `access` job runs `seanerstack validate --access` with the job token in every pipeline, the schedule included, and names each recipe whose project does not allow it.

`tutorial:install-the-stack` runs `tests/tutorials/install-the-stack.sh` on Rocky Linux 10 with the Seanerstack of the commit. The script is the [tutorial](../tutorials/getting-started.md): the page shows its sections, so the commands a reader types are the ones this job has run. It sets up the state with `init`, activates it, installs the toolchain and `seanergys-meta`, and checks that the stack is installed by the Spack of the state. Only the first step differs: the job uses the Seanerstack it installed from the checkout, where a reader installs the release with pipx.

Both jobs set up their state in a directory with a random name of a random length below `/var/tmp`, not in the directory the build cache is built in. A binary that installs only where it was built, or a hash that depends on the state directory, therefore fails them instead of passing unnoticed.

`how-to:work-on-a-package` runs `tests/how-to/work-on-a-package.sh` on Rocky Linux 10, in a state set up with `seanerstack init` and `seanerstack toolchain bootstrap`. The script is the procedure of [Work on a package](../how-to/work-on-a-package.md): the guide shows its sections, so the commands a reader types are the ones this job has run. It clones `priorisea` with the job token, binds the checkout to the package environment, installs it, and checks that the installed package was built from the checkout. The priorisea project and the projects of its submodules therefore have to allow this project's job token, as for `build:rocky10`.

## Installing from the build caches on GitHub

The GitLab pipeline fills the build caches; the workflow `.github/workflows/install.yml` of the GitHub copy of the project only checks that `seanergys-meta` installs from the public build caches on Juphoria, and builds nothing. It runs `ci/github/install-from-cache.sh` in the image of a platform of `[toolchain.platforms]`, which installs Seanerstack from the checkout, runs `init` and `toolchain bootstrap --cache-only`, and installs an environment with `seanergys-meta` with `spack install --cache-only`. A binary that the caches lack, the compiler lockfile included, fails the job instead of being built.

Both take `ci/github.toml`: the public build caches, read over Swift without keys, which the `toolchain:public` jobs fill, their compiler lockfiles included, and the Git resource of the recipes, without credentials. Git rewrites the SEANERGYS GitLab URLs of the recipes to the copies of the repositories in the GitHub organization `seanergys`, and `seanerstack validate --access` tries every one. Each platform has two jobs:

- **private** reads the repositories with the secret `SEANERGYS_GITHUB_TOKEN`, a token that reads the repositories of the organization.
- **public** has no credentials at all, so it reads only the public repositories.

A step that fails does not stop the job: `init`, the access of each repository and the install are recorded in `results/`, and the job fails at the end. Each job keeps its results as an artifact, and the `report` job puts them into one table in the summary of the run, a row for `seanergys-meta` and for each repository, a column for each job. Until every repository is public, the public jobs fail on the repositories that are not.

Pushes to the default branch and pull requests run both jobs on Rocky Linux 10. **Actions → install → Run workflow** takes the platforms to check, names of `[toolchain.platforms]` separated by spaces, or `all`.

## Project settings

The merge train needs these settings, under **Settings → Merge requests**:

- **Merged results pipelines** enabled.
- **Merge trains** enabled.
- **Pipelines must succeed** enabled.
- **Allow skipping the merge train** disabled, so that every commit on the default branch has passed `e2e`.
