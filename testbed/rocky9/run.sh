#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
#
# Host-side wrapper around `docker run` for the Rocky Linux 9 test bed.
# Builds the image, then runs workflow.sh inside it against the repository
# checkout this script lives in.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${SEANSTACK_REPO:-$(cd "$HERE/../.." && pwd)}"
IMAGE="${SEANSTACK_IMAGE:-seanstack-rocky9}"
VOLUMES="${SEANSTACK_VOLUMES:-seanstack-spack}"

usage() {
    cat <<'USAGE'
Usage: run.sh COMMAND [--shell] [--push | --from-cache]

Commands:
  check       run the workflow without installing flux-core
  install     run the workflow including `spack install`
  full        as install, but bootstrap gcc@15 first
  uninstall   remove flux-core from the Spack store again
  shell       drop straight into an interactive shell, no workflow

Add --shell to any of the others to be left in a shell once it finishes:

  ./run.sh check --shell
  ./run.sh install --shell

Build cache options for install and full (cache: seanstack-buildcache):
  --push        push what was installed to the cache
  --from-cache  install only from the cache; fails if anything would be built

Environment:
  SEANSTACK_REPO   repository checkout to mount at /src (default: this repo)
  SEANSTACK_IMAGE  image name to build and run (default: seanstack-rocky9)
  SEANSTACK_VOLUMES
                   prefix for the named volume holding the Spack state
                   (default: seanstack-spack); use another prefix to run
                   against a clean state without discarding the default one
  SEANSTACK_JOBS   build jobs for `spack install` (default: nproc)
  SEANSTACK_GC     set to 1 to also run `spack gc` in uninstall mode
  SEANSTACK_SOLVE_TIMEOUT
                   seconds Spack may spend on a single concretization before
                   it reports an error (default: 600)
  SEANSTACK_CPUS   value for `docker run --cpus`
  SEANSTACK_BUILTIN_COMMIT
                   pin Spack's builtin package repository to this commit. A
                   --push run prints the value its --from-cache runs need.
  UV_INDEX_SEANERGYS_USERNAME, UV_INDEX_SEANERGYS_PASSWORD
                   credentials for the internal package index that supplies
                   seanervault, a seanstack dependency. Your GitLab username, and
                   a personal access token with the `api` scope as the password.
                   Without them `uv tool install` cannot resolve seanstack and
                   the workflow stops at its first step. The build cache uses
                   the same token for the container registry.
USAGE
    exit "${1:-0}"
}

COMMAND="${1:-}"
[[ -z "$COMMAND" || "$COMMAND" == -h || "$COMMAND" == --help ]] && usage
shift

SHELL_AFTER=0
CACHE=none
for arg in "$@"; do
    case "$arg" in
        --shell) SHELL_AFTER=1 ;;
        --push|--from-cache)
            [[ "$CACHE" == none ]] || { echo "--push and --from-cache are exclusive" >&2; usage 2; }
            [[ "$arg" == --push ]] && CACHE=push || CACHE=only
            ;;
        *) echo "unknown argument: $arg" >&2; usage 2 ;;
    esac
done

case "$COMMAND" in
    check)     MODE=concretize ;;
    install)   MODE=install ;;
    full)      MODE=full ;;
    uninstall) MODE=uninstall ;;
    shell)     MODE=shell ;;
    *)         echo "unknown command: $COMMAND" >&2; usage 2 ;;
esac

if [[ "$CACHE" != none && "$MODE" != install && "$MODE" != full ]]; then
    echo "--push and --from-cache apply to install and full only" >&2
    usage 2
fi

# seanstack depends on seanervault, which lives in the internal index, so without
# credentials `uv tool install` fails inside the container with a dependency
# resolution error that says nothing about what to set. Warn rather than refuse:
# uv also reads ~/.netrc and its own configuration.
if [[ -z "${UV_INDEX_SEANERGYS_USERNAME:-}" || -z "${UV_INDEX_SEANERGYS_PASSWORD:-}" ]]; then
    cat >&2 <<'WARNING'
==> warning: UV_INDEX_SEANERGYS_USERNAME / UV_INDEX_SEANERGYS_PASSWORD are unset

    seanstack depends on seanervault from the SEANERGYS package index, so the
    install step will fail unless uv finds credentials elsewhere:

      export UV_INDEX_SEANERGYS_USERNAME=<your GitLab username>
      read -rs UV_INDEX_SEANERGYS_PASSWORD && export UV_INDEX_SEANERGYS_PASSWORD

    The token needs the `api` scope. Verify it before a long run with:

      curl -sS -o /dev/null -w '%{http_code}\n' \
        -u "$UV_INDEX_SEANERGYS_USERNAME:$UV_INDEX_SEANERGYS_PASSWORD" \
        https://gitlab.seanergys.fz-juelich.de/api/v4/groups/158/-/packages/pypi/simple

WARNING
fi

# Build every time rather than only when the image is missing. Docker's layer
# cache makes this a no-op when nothing changed, and an image left over from an
# older Dockerfile is otherwise invisible until the workflow fails inside it.
echo "==> building $IMAGE"
docker build -t "$IMAGE" "$HERE"

# Seanstack keeps the whole mutable Spack state under one root, so a single
# volume covers the private configuration, install store, stages, caches, and
# managed environments.
args=(
    --rm
    -v "$REPO:/src:ro"
    -v "$HERE:/scripts:ro"
    -v "$VOLUMES-state:/state"
)
# -it only when a terminal is attached, so the script also works in CI and pipes.
[[ -t 0 && -t 1 ]] && args+=(-it)
[[ -n "${SEANSTACK_JOBS:-}" ]] && args+=(-e "SEANSTACK_JOBS=$SEANSTACK_JOBS")
[[ -n "${SEANSTACK_GC:-}" ]] && args+=(-e "SEANSTACK_GC=$SEANSTACK_GC")
[[ -n "${SEANSTACK_SOLVE_TIMEOUT:-}" ]] && args+=(-e "SEANSTACK_SOLVE_TIMEOUT=$SEANSTACK_SOLVE_TIMEOUT")
[[ -n "${SEANSTACK_BUILTIN_COMMIT:-}" ]] && args+=(-e "SEANSTACK_BUILTIN_COMMIT=$SEANSTACK_BUILTIN_COMMIT")
# seanstack depends on seanervault, which lives in the internal index rather than
# on PyPI, so the container needs the same credentials the host uses.
for name in UV_INDEX_SEANERGYS_USERNAME UV_INDEX_SEANERGYS_PASSWORD; do
    [[ -n "${!name:-}" ]] && args+=(-e "$name=${!name}")
done
[[ -n "${SEANSTACK_CPUS:-}" ]] && args+=(--cpus "$SEANSTACK_CPUS")

if [[ "$MODE" == shell ]]; then
    exec docker run "${args[@]}" "$IMAGE" bash --rcfile /scripts/shellrc -i
fi

args+=(-e "SEANSTACK_MODE=$MODE" -e "SEANSTACK_CACHE=$CACHE")

if [[ "$SHELL_AFTER" == 1 ]]; then
    # Deliberately not `set -e` on the workflow: even when it fails we want a
    # shell to debug in.
    exec docker run "${args[@]}" "$IMAGE" \
        bash -lc '/scripts/workflow.sh; echo; echo "--- workflow exited with code $? ---"; exec bash --rcfile /scripts/shellrc -i'
fi

exec docker run "${args[@]}" "$IMAGE" bash -lc /scripts/workflow.sh
