# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from spack.package import Package, depends_on, license, mkdirp, version


class Hpcmonitor4b(Package):
    """Blender add-on for visualizing HPC cluster monitoring data, with dependencies
    for generating USD cluster models from Excel workbooks."""

    homepage = "https://gitlab.seanergys.fz-juelich.de/software/hpcmonitor4b"
    git = "https://gitlab.seanergys.fz-juelich.de/software/hpcmonitor4b.git"
    seanerstack_resource = "seanergys-gitlab"

    license("GPL-3.0-or-later")

    version("main", branch="main")

    # The generator runs from the source checkout using the Spack environment.
    depends_on("python", type="run")
    depends_on("py-numpy@2.2.2", type="run")
    depends_on("py-openpyxl@3.1.5:", type="run")
    depends_on("py-pandas@1.5:", type="run")
    depends_on("py-pillow@10:", type="run")
    depends_on("py-usd-core@25.8:", type="run")

    def install(self, spec, prefix):
        addon = Path(self.stage.source_path) / "addons" / "hpcmonitor4b"
        config_name = "hpcmonitor4b_client_config.py"
        config_template = addon / (config_name + ".template")
        mkdirp(prefix.share)
        with ZipFile(Path(prefix.share) / "hpcmonitor4b.zip", "w", ZIP_DEFLATED) as archive:
            for source in sorted(addon.rglob("*")):
                relative = source.relative_to(addon)
                if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
                    continue
                if source.is_file() and source.name != config_name and source.suffix != ".pyc":
                    archive.write(source, Path(addon.name) / relative)

            # Blender imports this module on load. Ship the blank template as its default.
            archive.write(config_template, Path(addon.name) / config_name)
