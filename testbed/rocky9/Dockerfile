# SPDX-License-Identifier: Apache-2.0
# Rocky Linux 9 test bed for the SEANERGYS flux-core onboarding workflow.
FROM rockylinux/rockylinux:9

# Toolchain and utilities Spack expects from the operating system. The system
# GCC is only ever used to bootstrap the Spack-provided compiler.
RUN dnf -y install --setopt=install_weak_deps=False \
        bzip2 ca-certificates diffutils file findutils gcc gcc-c++ \
        gcc-gfortran git gnupg2 gzip hostname make patch perl python3 \
        tar unzip which xz zlib-devel \
 && dnf clean all

# uv, per the SEANERGYS tutorial, brings its own Python and installs seanstack.
ENV UV_INSTALL_DIR=/usr/local/bin
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && uv --version

# Seanstack isolates Spack's configuration and state, so the checkout only has
# to provide the executable. It may live anywhere; /opt keeps it clear of the
# state directory, which is the part that persists in a volume.
ENV SPACK_ROOT=/opt/spack
RUN git clone --depth=1 https://github.com/spack/spack.git "$SPACK_ROOT" \
 && printf '\nsource "%s/share/spack/setup-env.sh"\n' "$SPACK_ROOT" >> /root/.bashrc

# The complete mutable Spack state: private configuration, install store,
# stages, caches, and managed environments.
ENV SEANSTACK_STATE_DIR=/state

WORKDIR /work
CMD ["/bin/bash", "-l"]
