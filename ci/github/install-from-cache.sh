#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
#
# Install seanergys-meta from the build caches only, building nothing, in the
# image of a platform of config.toml. Run by .github/workflows/install.yml in
# the checkout, as root in the container of the platform:
#
#   ci/github/install-from-cache.sh private   # the private resources: SEANERGYS GitLab and its registry
#   ci/github/install-from-cache.sh public    # the public build caches only, without any credentials
#
# PLATFORM names the platform, and PYTHON its Python, as in config.toml. The
# private run takes the GitLab credentials from SEANERGYS_GITLAB_USERNAME and
# SEANERGYS_GITLAB_TOKEN, a token that reads repositories and the registry,
# and passes them in a secrets file, as users do.
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

case "$mode" in
    private)
        : "${SEANERGYS_GITLAB_USERNAME:?the user of the GitLab token}" "${SEANERGYS_GITLAB_TOKEN:?a GitLab token}"
        # The secrets file only has to outlive the job. keyloom came with Seanerstack.
        umask 077
        head -c 32 /dev/urandom | base64 > /tmp/vault-password
        cat > /tmp/secrets.toml <<EOF
[credentials.seanergys-gitlab]
username = "$SEANERGYS_GITLAB_USERNAME"
token = { __keyloom__ = "secret", value = "$SEANERGYS_GITLAB_TOKEN" }

[credentials.seanergys-registry]
username = "$SEANERGYS_GITLAB_USERNAME"
token = { __keyloom__ = "secret", value = "$SEANERGYS_GITLAB_TOKEN" }
EOF
        umask 022
        keyloom encrypt /tmp/secrets.toml --password-file /tmp/vault-password
        secrets=(--secrets-file /tmp/secrets.toml --secrets-password-file /tmp/vault-password)
        # Every private recipe can be cloned with these credentials, not just one of each resource.
        seanerstack "${secrets[@]}" validate --access
        ;;
    public)
        export SEANERSTACK_CONFIG_FILE="$PWD/ci/github-public.toml"
        secrets=()
        ;;
    *)
        echo "unknown mode $mode: private or public" >&2
        exit 2
        ;;
esac

seanerstack "${secrets[@]}" init
eval "$(seanerstack activate)"
seanerstack toolchain bootstrap --cache-only
spack env create --without-view -d /opt/seanergys-meta
spack -e /opt/seanergys-meta add seanergys-meta
spack -e /opt/seanergys-meta concretize
spack -e /opt/seanergys-meta install --cache-only \
    --jobs "$(python -c 'import seanerstack.jobs; print(seanerstack.jobs.default_jobs())')"
spack -e /opt/seanergys-meta find
