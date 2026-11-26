# SPDX-License-Identifier: Apache-2.0
"""Check that a build cache of the session takes a push.

Run by Seanerstack as `spack python THIS_FILE NAME`, inside its isolated
session, so it imports Spack, not Seanerstack.

A small file goes to test/ below the push URL of the mirror NAME, the way
Spack pushes a binary there, with the credentials of the session, and is
removed again. A cache that refuses, or that Spack cannot reach, such as an
S3 cache without boto3 in the Python of Spack, is named.
"""

import os
import sys
import tempfile
import uuid

import spack.mirrors.mirror
import spack.util.url
import spack.util.web


def main(name: str) -> int:
    """Push a small file to the mirror `name`, and remove it again.

    @param name: the name of a binary mirror of the session
    @return: 0 when the push went through, 1 otherwise
    """
    mirrors = spack.mirrors.mirror.MirrorCollection(binary=True)
    if name not in mirrors:
        print(f"{name}: no binary mirror of this name")
        return 1
    mirror = mirrors[name]
    url = spack.util.url.join(mirror.push_url, "test", f"seanerstack-push-check-{uuid.uuid4().hex}")
    descriptor, path = tempfile.mkstemp()
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write("A push check of Seanerstack, removed after it was written.\n")
        spack.util.web.push_to_url(path, url, keep_original=True)
    except Exception as error:
        print(f"{name}: {mirror.push_url} refuses a push: {error}")
        return 1
    finally:
        if os.path.exists(path):
            os.remove(path)
    try:
        spack.util.web.remove_url(url)
    except Exception as error:
        # The push went through; only the check file stays behind.
        print(f"{name}: takes a push to {url}, which could not be removed: {error}")
        return 0
    print(f"{name}: takes a push to {mirror.push_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
