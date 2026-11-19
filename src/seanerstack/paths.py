# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path
import sysconfig


def _source_share_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "share" / "seanerstack"


def source_checkout() -> Path | None:
    """Return the root of the checkout this module runs from, if there is one."""
    source = _source_share_path()
    return source.parents[2] if source.is_dir() else None


def _installed_share_path() -> Path:
    data_root = sysconfig.get_path("data")
    if not data_root:
        raise RuntimeError("Python did not report an installation data directory")
    return Path(data_root).resolve() / "share" / "seanerstack"


def share_path() -> Path:
    """Return the Seanerstack shared-data directory.

    A source checkout is preferred when the Python module itself is imported from
    that checkout. Installed wheels otherwise resolve through Python's ``data``
    installation scheme, which maps to ``<prefix>/share/seanerstack``.
    """

    source = _source_share_path()
    if source.is_dir():
        return source.resolve()

    installed = _installed_share_path()
    if installed.is_dir():
        return installed

    raise RuntimeError(
        "could not locate Seanerstack shared data; expected "
        f"{installed}"
    )


def repository_path() -> Path:
    path = share_path() / "spack_repo" / "seanerstack"
    if not path.is_dir():
        raise RuntimeError(f"Seanerstack Spack repository is missing: {path}")
    return path


def toolchain_lockfile(operating_system: str) -> Path | None:
    """The shipped lockfile of the compiler environment for an operating system, or None.

    @param operating_system: the operating system as Spack names it, such as rocky10
    @return: the path of the lockfile, or None when Seanerstack ships none for it
    """
    path = share_path() / "toolchain" / operating_system / "spack.lock"
    return path if path.is_file() else None


def environments_path() -> Path:
    path = share_path() / "environments"
    if not path.is_dir():
        raise RuntimeError(f"Seanerstack environment directory is missing: {path}")
    return path
