# SPDX-License-Identifier: Apache-2.0
from spack_repo.builtin.build_systems.python import PythonPackage

from spack.package import *


class Properdocs(PythonPackage):
    """Static site generator used for Seanstack and SEANERGYS documentation."""

    homepage = "https://properdocs.org/"
    git = "https://github.com/ProperDocs/properdocs.git"

    # Development follows the upstream default branch.
    version("master", branch="master")

    # Released versions are synchronized from upstream Git tags by `seanstack sync`.
    version("1.6.7", tag="v1.6.7")
    version("1.6.6", tag="v1.6.6")
    version("1.6.5", tag="v1.6.5")

    depends_on("python@3.10:", type=("build", "run"))
    depends_on("py-hatchling", type="build")

    depends_on("py-click@7:", type=("build", "run"))
    depends_on("py-jinja2@2.11.1:", type=("build", "run"))
    depends_on("py-markupsafe@2.0.1:", type=("build", "run"))
    depends_on("py-markdown@3.3.6:", type=("build", "run"))
    depends_on("py-pyyaml@5.1:", type=("build", "run"))
    depends_on("py-watchdog@2:", type=("build", "run"))
    depends_on("py-ghp-import@1:", type=("build", "run"))
    depends_on("py-pyyaml-env-tag@0.1:", type=("build", "run"))
    depends_on("py-packaging@20.5:", type=("build", "run"))
    depends_on("py-pathspec@0.11.1:", type=("build", "run"))
    depends_on("py-platformdirs@2.2:", type=("build", "run"))
