<!-- SPDX-License-Identifier: Apache-2.0 -->
# Rocky Linux 9 test bed

A container test bed that exercises seanerstack on the target platform of the
flux-core onboarding work item: Rocky Linux 9, with uv and Spack installed the
way `docs/tutorials/getting-started.md` describes, driving Spack through the
isolated state directory that seanerstack manages.

| File | Purpose |
| --- | --- |
| `Dockerfile` | Rocky Linux 9 image with the Spack toolchain, uv, and a Spack checkout |
| | (`SEANERSTACK_STATE_DIR=/state`; the Spack checkout itself lives in `/opt/spack`) |
| `workflow.sh` | The verification workflow, run inside the container |
| `run.sh` | Host-side `docker run` wrapper; builds the image on first use |
| `shellrc` | Bash rc for the interactive shell, prepares the same state as the workflow |

## Usage

```console
./run.sh check              # workflow up to `spack concretize`; installs nothing
./run.sh install            # additionally `spack install` and a smoke test
./run.sh full               # as install, but bootstrap gcc@15 first
./run.sh uninstall          # remove flux-core from the Spack store again
./run.sh shell              # interactive shell, no workflow
```

Append `--shell` to any of the first four to be left in a shell once the
workflow finishes, whether it succeeded or not. `./run.sh --help` lists the
environment variables (`SEANERSTACK_JOBS`, `SEANERSTACK_CPUS`, and others).

## Build cache

`install` and `full` take `--push` or `--from-cache` to exercise the project
build cache, `seanerstack-buildcache` in the seanerstack GitLab container registry.
The GitLab token from [Credentials](#credentials) is also the registry password.

```console
./run.sh full --push
SEANERSTACK_BUILTIN_COMMIT=<commit> SEANERSTACK_VOLUMES=consumer ./run.sh full --from-cache
```

The first run builds as usual and pushes everything it installed, gcc@15
included. The second starts from an empty state and installs with
`--use-buildcache only`, so it fails as soon as anything would have to be built:
a green run proves the cache serves the whole stack.

A binary is used only when the consumer concretizes the identical spec, so both
runs need the same image, host CPU, and recipes. A fresh state clones the latest
builtin package repository, which is why the consumer pins the commit the push
run prints at its end.

`install --push` puts gcc@11 builds into the project cache; prefer `full` for
anything meant to stay there.

The repository checkout is mounted read-only at `/src` and installed with
`uv tool install --from /src seanerstack`, so the workflow tests the working tree
rather than a published release.

## Credentials

seanerstack depends on seanervault, which lives in the SEANERGYS package index
rather than on PyPI, so the install step needs credentials for it. Export them
before running anything; `run.sh` passes them into the container and warns when
they are missing.

```console
$ export UV_INDEX_SEANERGYS_USERNAME=<your GitLab username>
$ read -rs UV_INDEX_SEANERGYS_PASSWORD && export UV_INDEX_SEANERGYS_PASSWORD
```

The password is a GitLab personal access token with the `api` scope. `read -rs`
keeps it out of the shell history. A fine-grained token is not enough: the
index is a group-level endpoint, which those tokens do not reach.

Check it before starting a run that takes hours:

```console
$ curl -sS -o /dev/null -w '%{http_code}\n' \
    -u "$UV_INDEX_SEANERGYS_USERNAME:$UV_INDEX_SEANERGYS_PASSWORD" \
    https://gitlab.seanergys.fz-juelich.de/api/v4/groups/158/-/packages/pypi/simple
200
```

## Compiler

SEANERGYS builds with `gcc@15`, and `install` mode deliberately does not: it
keeps the Rocky Linux 9 system compiler as a time-saving intermediate step that
answers one question only: do flux-core and its dependency tree build on Rocky
Linux 9 at all? Only `full` bootstraps `gcc@15` and validates against it, so a
green `install` run is not evidence that the project-compiler setup works.

`seanerstack toolchain bootstrap` writes its language requirements into the
isolated Spack configuration, which persists in the state volume, so a `full`
run would otherwise leave `require: gcc@15` behind and break every later gcc@11
run. Each mode therefore sets the compiler it wants before concretizing.
Switching between the two costs nothing beyond the concretization itself: both
compilers stay in the store, so no rebuild follows.

`full` also leaves gcc@15 registered as an external, which the requirement needs
in order to be satisfiable at all; see
[Compiler bootstrap](../../docs/explanation/compiler-bootstrap.md). That
registration is harmless to the gcc@11 modes: with no requirement in the
configuration, Spack still picks the system compiler.

A fresh state directory starts from `packages:: {}`, which drops the host's
compilers along with everything else. The workflow therefore runs
`spack compiler find` before anything else, or Spack would have nothing to
build gcc@15 with.

## When a run appears to hang

A concretization that cannot be satisfied does not fail in Spack, it runs out
the clock at full CPU with no output. The workflow therefore bounds every solve
(`SEANERSTACK_SOLVE_TIMEOUT`, 600s by default) so that such a run reports

```text
Error: Spack is taking more than 600 seconds to solve for zlib, stopping concretization
```

instead of looking like a slow build. If you see it, the compiler requirement in
the user scope is unsatisfiable; check `spack compiler list` and the `gcc:
externals:` block in `spack config --scope user get packages`.

## State between runs

Seanerstack keeps the whole mutable Spack state under one root, so a single named
volume mounted at `/state` carries the private configuration, install store,
stages, caches, and managed environments across runs. An interrupted install
resumes instead of restarting. To start clean:

```console
docker volume rm seanerstack-spack-state
```

Note that a clean state means rebuilding gcc@15 from source in `full` mode,
which takes roughly an hour and a half.
