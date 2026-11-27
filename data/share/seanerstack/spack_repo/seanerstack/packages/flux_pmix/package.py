# SPDX-License-Identifier: Apache-2.0

from spack_repo.builtin.packages.flux_pmix.package import FluxPmix as BuiltinFluxPmix

class FluxPmix(BuiltinFluxPmix):
    """Flux as Spack has it, but building from SEANERGYS GitLab"""

    git = "git@gitlab.seanergys.fz-juelich.de:software/flux-pmix.git"
    get_full_repo = True

