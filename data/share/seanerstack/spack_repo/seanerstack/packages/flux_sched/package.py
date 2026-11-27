# SPDX-License-Identifier: Apache-2.0

from spack_repo.builtin.packages.flux_sched.package import FluxSched as BuiltinFluxSched

class FluxSched(BuiltinFluxSched):
    """Flux as Spack has it, but building from SEANERGYS GitLab"""

    git = "git@gitlab.seanergys.fz-juelich.de:software/flux-sched.git"
    get_full_repo = True

