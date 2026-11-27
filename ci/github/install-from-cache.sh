#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
#
# Install seanergys-meta from the public build caches only, building nothing,
# in the image of a platform of config.toml, and check which repositories of
# the recipes can be read. Run by .github/workflows/install.yml in the
# checkout, as root in the container of the platform:
#
#   ci/github/install-from-cache.sh private   # with a token for the private repositories
#   ci/github/install-from-cache.sh public    # without any credentials
#
# The repositories are read from their copies in the GitHub organization
# seanergys. PLATFORM names the platform, and PYTHON its Python, as in
# config.toml. The private run takes SEANERGYS_GITHUB_TOKEN, a token that
# reads the repositories of the organization. The results go to RESULTS,
# by default results/ in the checkout.
set -euo pipefail

mode="${1:?private or public}"
PYTHON="${PYTHON:-python3}"

# Just enough Python for Seanerstack, which then installs the system packages
# of the platform from config.toml, as the toolchain jobs of GitLab do.
if command -v dnf >/dev/null; then
    dnf install -y --setopt=install_weak_deps=False "$PYTHON"
elif command -v apt-get >/dev/null; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 python3-venv python3-pip
else
    pacman -Syu --noconfirm --needed python python-pip
fi
"$PYTHON" -m venv /opt/seanerstack
# Spack runs with the Python of the platform, not with whichever python3 the image has.
export SPACK_PYTHON="$(command -v "$PYTHON")"
/opt/seanerstack/bin/pip install --quiet .
eval "$(/opt/seanerstack/bin/python -c 'import sys, seanerstack.config, seanerstack.prepare;
print(seanerstack.prepare.install_command(seanerstack.config.load_config().toolchain.platform(sys.argv[1])))' "$PLATFORM")"
# Spack names the operating system after /etc/os-release. An installed system
# links it to /usr/lib/os-release, but the archlinux image writes its own with
# the date of the image as version, which no machine has.
if [ -e /usr/lib/os-release ]; then ln -sf ../usr/lib/os-release /etc/os-release; fi
export PATH="/opt/seanerstack/bin:$PATH"

export SEANERSTACK_CONFIG_FILE="$PWD/ci/github.toml"

# Every repository of the SEANERGYS GitLab that a recipe names has a copy of
# the same name in the GitHub organization seanergys. Without a terminal, Git
# asks for nothing, so a repository it cannot read fails at once.
git config --global --add url.'https://github.com/seanergys/'.insteadOf 'https://gitlab.seanergys.fz-juelich.de/software/'
git config --global --add url.'https://github.com/seanergys/'.insteadOf 'git@gitlab.seanergys.fz-juelich.de:software/'
export GIT_TERMINAL_PROMPT=0

case "$mode" in
    private)
        : "${SEANERGYS_GITHUB_TOKEN:?a token that reads the repositories of the organization seanergys}"
        # Sent with the first request, as actions/checkout sends its own token.
        basic="$(printf 'x-access-token:%s' "$SEANERGYS_GITHUB_TOKEN" | base64 -w0)"
        git config --global http.https://github.com/seanergys/.extraheader "Authorization: Basic $basic"
        ;;
    public)
        ;;
    *)
        echo "unknown mode $mode: private or public" >&2
        exit 2
        ;;
esac

# Each step records its result in RESULTS and the job goes on, so that one run
# says which repositories it could not read and whether the stack installed.
# The job fails at the end when any step failed.
results="${RESULTS:-$PWD/results}"
mkdir -p "$results"
status=0

# init checks one recipe of each Git resource, which may be one this job cannot
# read; what it set up before that check is complete either way.
seanerstack init || status=1
# Every recipe, one line each: [OK] or [ERROR] access:PACKAGE: what Git said.
seanerstack validate --access | tee "$results/access.txt" || status=1

install=0
{
    eval "$(seanerstack activate)" &&
    seanerstack toolchain bootstrap --cache-only &&
    spack env create --without-view -d /opt/seanergys-meta &&
    spack -e /opt/seanergys-meta add seanergys-meta &&
    spack -e /opt/seanergys-meta concretize &&
    spack -e /opt/seanergys-meta install --cache-only \
        --jobs "$(python -c 'import seanerstack.jobs; print(seanerstack.jobs.default_jobs())')" &&
    spack -e /opt/seanergys-meta find
} || install=$?
if [ "$install" = 0 ]; then
    echo installed > "$results/install.txt"
else
    echo failed > "$results/install.txt"
    status=1
fi
exit "$status"
