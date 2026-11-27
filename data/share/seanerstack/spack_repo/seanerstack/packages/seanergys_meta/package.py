# SPDX-License-Identifier: Apache-2.0
from spack_repo.builtin.build_systems.bundle import BundlePackage

from spack.package import *


class SeanergysMeta(BundlePackage):
    """Meta package to install Seanergys software stack on different platforms"""

    # This is a version of the package recipe, not of an upstream source tree.
    version("2026.08")

    # The packages that build with the project toolchain; build:rocky10 builds
    # this package in every pipeline. A recipe joins when it builds there, so
    # psmpi and telemetry-collector are not here yet: psmpi does not find the
    # pscom it depends on, and the net-snmp that telemetry-collector needs
    # does not link its Perl modules.
    depends_on("access-daemon", type="run")
    depends_on("flux-core", type="run")
    depends_on("flux-dataplane-connector", type="run")
    depends_on("flux-pmix", type="run")
    depends_on("flux-sched", type="run")
    depends_on("hpcmonitor4b", type="run")
    depends_on("hta-database-daemon", type="run")
    depends_on("meric", type="run")
    depends_on("priorisea", type="run")
    depends_on("properdocs", type="run")
    depends_on("pscom", type="run")
    depends_on("psmpi", type="run")
    depends_on("py-pycapnp", type="run")
    depends_on("seanerbus", type="run")
    depends_on("seanerbus-cli", type="run")
    depends_on("seanerbus-msg", type="run")
    depends_on("seanerbus-naming-service", type="run")
    depends_on("seanerbus-rs", type="run")
    # The collector defaults to disabling its optional SNMP plugin.
    depends_on("telemetry-collector", type="run")
