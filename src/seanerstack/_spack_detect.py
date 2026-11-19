# SPDX-License-Identifier: Apache-2.0
"""Detect installed packages without registering them, and print them as JSON.

Run by Seanerstack as `spack python THIS_FILE PACKAGE... [--path=DIR]...`,
inside its isolated session, so it imports Spack, not Seanerstack. Unlike
`spack external find`, it writes no configuration: a package registered as an
external would be preferred over every build of it, and its hashes would then
match nothing in the project build cache.
"""

import json
import os
import sys

import spack.detection
import spack.repo


def main(arguments: list[str]) -> int:
    paths = [argument.removeprefix("--path=") for argument in arguments if argument.startswith("--path=")]
    packages = [argument for argument in arguments if not argument.startswith("--path=")]
    # PATH, and the given directories as well, not instead.
    hints = [directory for directory in os.environ.get("PATH", "").split(os.pathsep) if directory] + paths
    found = spack.detection.by_path(packages, repo=spack.repo.PATH, path_hints=hints)
    print(json.dumps({
        name: [{"spec": str(spec), "prefix": str(spec.external_path)} for spec in specs]
        for name, specs in sorted(found.items())
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
