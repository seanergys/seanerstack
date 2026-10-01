#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
#
# Verification workflow for the "Onboard Flux-Core" work item, run inside the
# Rocky Linux 9 image built from the Dockerfile next to this script.
#
# SEANERSTACK_MODE selects what the workflow does:
#
#   concretize  (default)  Everything up to `spack concretize`, plus
#                          `seanerstack validate --spack`. Installs nothing.
#                          Minutes.
#
#   install                Additionally runs `spack install` and a smoke test,
#                          but keeps the Rocky 9 system compiler (gcc@11.5).
#                          Hours.
#
#   full                   The workflow exactly as proposed in the work item:
#                          bootstraps gcc@15 first, then installs and validates
#                          against it. Hours, plus roughly another hour and a
#                          half for GCC itself.
#
#                          The compiler requirement it writes lives in the
#                          isolated Spack configuration, which persists in the
#                          state volume, so the gcc@11 modes above clear it
#                          again on their way past.
#
#   uninstall              Removes an installed flux-core from the Spack store
#                          again, so the install can be repeated from scratch.
#                          Set SEANERSTACK_GC=1 to also collect the dependencies
#                          that are left orphaned. Seconds to minutes.
#
# SEANERSTACK_CACHE adds the project build cache (seanerstack-buildcache) to
# install and full:
#
#   none  (default)  Build from source as usual.
#   push             Push everything installed, including gcc@15 in full mode.
#   only             Install from the cache only. Anything missing there fails
#                    the run instead of building, so a green run proves the
#                    cache serves the whole stack.
#
# A binary is used only for an identical spec, recipes included. Set
# SEANERSTACK_BUILTIN_COMMIT on an `only` run to the builtin repository commit
# the `push` run printed.
#
# NOTE ON THE COMPILER
# --------------------
# SEANERGYS builds with gcc@15; `install` mode deliberately does not. It is a
# time-saving intermediate step that answers one question only: do flux-core
# and its dependency tree build at all on Rocky Linux 9? A green `install` run
# is therefore NOT evidence that the project-compiler setup works, only `full`
# produces that. Do not report an `install` run as the work item's
# verification.
set -euo pipefail

MODE="${SEANERSTACK_MODE:-concretize}"
JOBS="${SEANERSTACK_JOBS:-$(nproc)}"
GC="${SEANERSTACK_GC:-0}"
SOLVE_TIMEOUT="${SEANERSTACK_SOLVE_TIMEOUT:-600}"
CACHE="${SEANERSTACK_CACHE:-none}"
BUILTIN_COMMIT="${SEANERSTACK_BUILTIN_COMMIT:-}"
CACHE_NAME=seanerstack-buildcache

case "$MODE" in
    concretize|install|full|uninstall) ;;
    *) echo "SEANERSTACK_MODE must be concretize, install, full or uninstall (got '$MODE')" >&2; exit 2 ;;
esac

case "$CACHE" in
    none|push|only) ;;
    *) echo "SEANERSTACK_CACHE must be none, push or only (got '$CACHE')" >&2; exit 2 ;;
esac

if [[ "$CACHE" != none && "$MODE" != install && "$MODE" != full ]]; then
    echo "SEANERSTACK_CACHE=$CACHE needs mode install or full (got '$MODE')" >&2
    exit 2
fi

step() { printf '\n\033[1m=== %s\033[0m\n' "$*"; }

builtin_commit() {
    local path
    path="$(spack repo list --json | python3 -c 'import json, sys; print(next(r["path"] for r in json.load(sys.stdin) if r["name"] == "builtin"))')"
    git -C "$path" rev-parse HEAD
}

step "mode: $MODE, build cache: $CACHE, build jobs: $JOBS"

step "install seanerstack from the mounted source checkout"
uv tool install --force --quiet --from /src seanerstack
export PATH="/root/.local/bin:$PATH"

# Everything below runs against the isolated Spack state in $SEANERSTACK_STATE_DIR
# rather than ~/.spack. Activation exports the configuration Spack must use, so
# it has to happen before any spack command. The Seanerstack repository comes with
# that configuration; registering it by hand would defeat the isolation.
step "seanerstack activate   (state: $SEANERSTACK_STATE_DIR)"
eval "$(seanerstack activate)"
spack config get repos

# The isolated configuration starts with `packages:: {}`, which drops the
# system compiler along with everything else the host might have offered. Spack
# has nothing to build with until it is found again.
step "spack compiler find   (system gcc, the only compiler in a fresh state)"
spack compiler find
spack compiler list

# Spack waits forever on an unsatisfiable solve by default (concretizer:timeout
# is 0). An unsatisfiable requirement then looks exactly like a slow build: no
# output, no error, hours of CPU. Bound it, so the test bed reports a problem
# instead of hanging on one.
step "concretizer timeout: ${SOLVE_TIMEOUT}s"
spack config add "concretizer:timeout:$SOLVE_TIMEOUT"
spack config add "concretizer:error_on_timeout:true"

# A fresh state clones the latest builtin repository, whose recipes may differ
# from the ones the cached binaries were built with.
if [[ -n "$BUILTIN_COMMIT" ]]; then
    step "pin builtin package repository to $BUILTIN_COMMIT"
    spack repo update --scope user --commit "$BUILTIN_COMMIT" builtin
    # Spack rewrites repos.yaml without the `::` that keeps other scopes out.
    sed -i 's/^repos:$/repos::/' "$SEANERSTACK_STATE_DIR/spack/config/repos.yaml"
fi

if [[ "$CACHE" != none ]]; then
    step "build cache: configure $CACHE_NAME"
    # The mirror stores only variable names; the GitLab token is the registry password.
    export SEANERSTACK_RESOURCE_SEANERSTACK_BUILDCACHE_USERNAME="${UV_INDEX_SEANERGYS_USERNAME:?the build cache needs UV_INDEX_SEANERGYS_USERNAME}"
    export SEANERSTACK_RESOURCE_SEANERSTACK_BUILDCACHE_PASSWORD="${UV_INDEX_SEANERGYS_PASSWORD:?the build cache needs UV_INDEX_SEANERGYS_PASSWORD}"
    seanerstack buildcache configure
    spack mirror list
fi

if [[ "$CACHE" == only ]]; then
    step "build cache: check"
    seanerstack buildcache check
fi

if [[ "$MODE" == uninstall ]]; then
    # Deliberately without activating the environment: `spack uninstall` grows a
    # `--remove` behaviour inside an environment that would edit the shipped
    # spack.yaml. Operating on the store directly cannot touch the manifest.
    step "spack uninstall flux-core"
    if spack find flux-core >/dev/null 2>&1; then
        spack uninstall --yes-to-all --all --dependents flux-core
    else
        echo "flux-core is not installed; nothing to do"
    fi

    if [[ "$GC" == 1 ]]; then
        step "spack gc   (dependencies left orphaned by the uninstall)"
        spack gc --yes-to-all
    fi

    step "remaining installed packages"
    spack find || true

    step "done (mode: uninstall)"
    exit 0
fi

step "seanerstack --help"
seanerstack --help

step "seanerstack paths share"
seanerstack paths share

step "seanerstack paths repo"
seanerstack paths repo

# `seanerstack toolchain bootstrap` writes the language requirements into the
# isolated configuration, which persists in the state volume, so a `full` run
# leaves `require: gcc@15` behind and every later gcc@11 run fails to
# concretize against it. Each mode therefore states its own compiler intent
# instead of inheriting whatever the previous run happened to leave.
if [[ "$MODE" == full ]]; then
    # Bootstrap would build GCC from source; take it from the cache first.
    if [[ "$CACHE" == only ]] && ! spack find gcc@15 >/dev/null 2>&1; then
        step "spack install --use-buildcache only gcc@15"
        spack install --use-buildcache only gcc@15
    fi

    step "seanerstack toolchain bootstrap gcc@15   (builds GCC 15 unless installed)"
    seanerstack toolchain bootstrap gcc@15
    # The bootstrap registers the compiler as an external before requiring it.
    # Without that registration the requirement cannot be satisfied at all, so
    # show what Spack now considers available.
    spack compiler list

    if [[ "$CACHE" == push ]]; then
        # By hash: once used, the compiler also has an external record that
        # makes `gcc@15` ambiguous, and externals cannot be pushed anyway.
        gcc_hash="$(spack find --json gcc@15 | python3 -c 'import json, sys; print(next(s["hash"] for s in json.load(sys.stdin) if not s.get("external")))')"
        step "spack buildcache push $CACHE_NAME gcc@15   (/$gcc_hash)"
        spack buildcache push --update-index "$CACHE_NAME" "/$gcc_hash"
    fi
else
    step "compiler: Rocky 9 system gcc   (dropping any gcc@15 requirement)"
    for language in c cxx fortran; do
        spack config remove "packages:$language:require" 2>/dev/null || true
    done
fi

spack config get packages

step "seanerstack paths env --package flux-core"
seanerstack paths env --package flux-core

step "spack env activate + spack concretize"
spack env activate "$(seanerstack paths env --package flux-core)"
spack concretize

if [[ "$MODE" == concretize ]]; then
    spack spec
fi

if [[ "$MODE" != concretize ]]; then
    if [[ "$CACHE" == only ]]; then
        step "spack install --use-buildcache only"
        spack install --use-buildcache only -j "$JOBS"
    else
        step "spack install"
        spack install -j "$JOBS"
    fi

    if [[ "$CACHE" == push ]]; then
        step "spack buildcache push $CACHE_NAME"
        spack buildcache push --update-index "$CACHE_NAME"
    fi

    # `spack install` succeeding does not mean the result runs: flux-core is a
    # resource manager, so start an instance and put a job through it.
    step "smoke test: start a Flux instance and run a job"
    spack load flux-core
    flux --version
    flux start flux resource list
    flux start flux run -N1 hostname
fi

step "seanerstack validate"
if [[ "$MODE" == full ]]; then
    seanerstack validate --compiler gcc@15 --spack
else
    seanerstack validate --spack
fi

step "builtin package repository commit"
commit="$(builtin_commit)"
echo "$commit"
if [[ "$CACHE" == push ]]; then
    echo "install from the cache in a fresh state with:"
    echo "  SEANERSTACK_BUILTIN_COMMIT=$commit SEANERSTACK_VOLUMES=consumer ./run.sh $MODE --from-cache"
fi

step "done (mode: $MODE, build cache: $CACHE)"
