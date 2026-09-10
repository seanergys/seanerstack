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
Usage: run.sh COMMAND [--shell]

Commands:
  check       run the workflow without installing flux-core
  install     run the workflow including `spack install`
  full        as install, but bootstrap gcc@15 first
  uninstall   remove flux-core from the Spack store again
  shell       drop straight into an interactive shell, no workflow

Add --shell to any of the others to be left in a shell once it finishes:

  ./run.sh check --shell
  ./run.sh install --shell

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
  UV_INDEX_SEANERGYS_USERNAME, UV_INDEX_SEANERGYS_PASSWORD
                   credentials for the internal package index that supplies
                   seanvault, a seanstack dependency. Your GitLab username, and
                   a personal access token with the `api` scope as the password.
                   Without them `uv tool install` cannot resolve seanstack and
                   the workflow stops at its first step.
USAGE
    exit "${1:-0}"
}

COMMAND="${1:-}"
[[ -z "$COMMAND" || "$COMMAND" == -h || "$COMMAND" == --help ]] && usage
shift

SHELL_AFTER=0
[[ "${1:-}" == "--shell" ]] && { SHELL_AFTER=1; shift; }
[[ $# -gt 0 ]] && { echo "unknown argument: $1" >&2; usage 2; }

case "$COMMAND" in
    check)     MODE=concretize ;;
    install)   MODE=install ;;
    full)      MODE=full ;;
    uninstall) MODE=uninstall ;;
    shell)     MODE=shell ;;
    *)         echo "unknown command: $COMMAND" >&2; usage 2 ;;
esac

# seanstack depends on seanvault, which lives in the internal index, so without
# credentials `uv tool install` fails inside the container with a dependency
# resolution error that says nothing about what to set. Warn rather than refuse:
# uv also reads ~/.netrc and its own configuration.
if [[ -z "${UV_INDEX_SEANERGYS_USERNAME:-}" || -z "${UV_INDEX_SEANERGYS_PASSWORD:-}" ]]; then
    cat >&2 <<'WARNING'
==> warning: UV_INDEX_SEANERGYS_USERNAME / UV_INDEX_SEANERGYS_PASSWORD are unset

    seanstack depends on seanvault from the SEANERGYS package index, so the
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
# seanstack depends on seanvault, which lives in the internal index rather than
# on PyPI, so the container needs the same credentials the host uses.
for name in UV_INDEX_SEANERGYS_USERNAME UV_INDEX_SEANERGYS_PASSWORD; do
    [[ -n "${!name:-}" ]] && args+=(-e "$name=${!name}")
done
[[ -n "${SEANSTACK_CPUS:-}" ]] && args+=(--cpus "$SEANSTACK_CPUS")

if [[ "$MODE" == shell ]]; then
    exec docker run "${args[@]}" "$IMAGE" bash --rcfile /scripts/shellrc -i
fi

args+=(-e "SEANSTACK_MODE=$MODE")

if [[ "$SHELL_AFTER" == 1 ]]; then
    # Deliberately not `set -e` on the workflow: even when it fails we want a
    # shell to debug in.
    exec docker run "${args[@]}" "$IMAGE" \
        bash -lc '/scripts/workflow.sh; echo; echo "--- workflow exited with code $? ---"; exec bash --rcfile /scripts/shellrc -i'
fi

exec docker run "${args[@]}" "$IMAGE" bash -lc /scripts/workflow.sh
