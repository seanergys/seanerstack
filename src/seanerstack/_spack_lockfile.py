# SPDX-License-Identifier: Apache-2.0
"""Read or store a file below a build cache of the session, such as the compiler lockfile.

Run by Seanerstack as `spack python THIS_FILE get NAME PATH DESTINATION` or
`spack python THIS_FILE put NAME PATH SOURCE`, inside its isolated session, so
it imports Spack, not Seanerstack. PATH is relative to the URL of the mirror
NAME, read below its fetch URL and written below its push URL, with the
credentials of the session, as Spack reads and writes binaries there.

The exit status is 0 when the file was read or stored, 2 when the cache has
no file at PATH (get) or has one already, which stays as it is (put), and 1
when the cache could not be read or written.
"""

import shutil
import sys

import spack.mirrors.mirror
import spack.util.url
import spack.util.web


def _mirror(name: str):
    """The binary mirror `name` of the session.

    @param name: the name of the mirror
    @return: the mirror, or None when the session has none of this name
    """
    mirrors = spack.mirrors.mirror.MirrorCollection(binary=True)
    return mirrors[name] if name in mirrors else None


def get(name: str, path: str, destination: str) -> int:
    """Save the file at `path` below the mirror `name` as `destination`.

    @param name: the name of a binary mirror of the session
    @param path: the path of the file below the fetch URL of the mirror
    @param destination: where to save it
    @return: 0 when saved, 2 when the cache has no such file, 1 when it cannot be read
    """
    mirror = _mirror(name)
    if mirror is None:
        print(f"{name}: no binary mirror of this name")
        return 1
    url = spack.util.url.join(mirror.fetch_url, *path.split("/"))
    try:
        if not spack.util.web.url_exists(url):
            return 2
        _, _, response = spack.util.web.read_from_url(url)
        with open(destination, "wb") as stream:
            shutil.copyfileobj(response, stream)
    except Exception as error:
        print(f"{name}: cannot read {url}: {error}")
        return 1
    return 0


def put(name: str, path: str, source: str) -> int:
    """Store `source` at `path` below the mirror `name`, unless a file is there already.

    @param name: the name of a binary mirror of the session
    @param path: the path of the file below the push URL of the mirror
    @param source: the file to store
    @return: 0 when stored, 2 when the cache has a file there already, 1 when it cannot be written
    """
    mirror = _mirror(name)
    if mirror is None:
        print(f"{name}: no binary mirror of this name")
        return 1
    url = spack.util.url.join(mirror.push_url, *path.split("/"))
    try:
        if spack.util.web.url_exists(url):
            return 2
        spack.util.web.push_to_url(source, url, keep_original=True)
    except Exception as error:
        print(f"{name}: cannot write {url}: {error}")
        return 1
    return 0


if __name__ == "__main__":
    action, *arguments = sys.argv[1:]
    sys.exit({"get": get, "put": put}[action](*arguments))
