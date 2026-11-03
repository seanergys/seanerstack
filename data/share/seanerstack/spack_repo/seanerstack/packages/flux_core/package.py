# SPDX-License-Identifier: Apache-2.0
import re

from spack_repo.builtin.packages.flux_core.package import FluxCore as BuiltinFluxCore

from spack.package import *


class FluxCore(BuiltinFluxCore):
    """Flux as Spack has it, which can also build a commit"""

    # configure takes the version from `git describe`, which needs the tags. Spack
    # clones a commit alone, and the refspec of that clone makes the builtin recipe
    # fail to fetch the history, so configure stops at an invalid version.
    get_full_repo = True

    def test_version(self):
        """check that flux reports a version that starts with a release"""
        output = which(self.prefix.bin.flux, required=True)("version", output=str, error=str)
        assert re.search(r"^commands:\s+\d+\.\d+\.\d+", output, re.MULTILINE), output

    def test_run_a_job(self):
        """run a job in an instance of one broker"""
        flux = which(self.prefix.bin.flux, required=True)
        assert flux("start", "flux", "run", "echo", "ran", output=str, error=str).strip() == "ran"
