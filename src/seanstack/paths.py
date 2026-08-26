# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from pathlib import Path
import sysconfig


def _source_share_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "share" / "seanstack"


def _installed_share_path() -> Path:
    data_root = sysconfig.get_path("data")
    if not data_root:
        raise RuntimeError("Python did not report an installation data directory")
    return Path(data_root).resolve() / "share" / "seanstack"


def share_path() -> Path:
    """Return the Seanstack shared-data directory.

    A source checkout is preferred when the Python module itself is imported from
    that checkout. Installed wheels otherwise resolve through Python's ``data``
    installation scheme, which maps to ``<prefix>/share/seanstack``.
    """

    source = _source_share_path()
    if source.is_dir():
        return source.resolve()

    installed = _installed_share_path()
    if installed.is_dir():
        return installed

    raise RuntimeError(
        "could not locate Seanstack shared data; expected "
        f"{installed}"
    )


def repository_path() -> Path:
    path = share_path() / "spack_repo" / "seanstack"
    if not path.is_dir():
        raise RuntimeError(f"Seanstack Spack repository is missing: {path}")
    return path


def environments_path() -> Path:
    path = share_path() / "environments"
    if not path.is_dir():
        raise RuntimeError(f"Seanstack environment directory is missing: {path}")
    return path
