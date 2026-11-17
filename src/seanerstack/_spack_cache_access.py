# SPDX-License-Identifier: Apache-2.0
"""Check that the OCI build caches of the session answer a request.

Run by Seanerstack as `spack python THIS_FILE`, inside its isolated session,
so it imports Spack, not Seanerstack.

`spack install` treats a build cache that refuses a request, such as a
private registry asked without credentials, like one that lacks the binary:
it prints "no binary available" and builds from source. Here the same request
that an install starts with, for a manifest of the cache, is made with the
session's credentials, and a refusal is named.
"""

import sys
import urllib.error
import urllib.request

import spack.binary_distribution
import spack.mirrors.mirror
import spack.oci.image
import spack.oci.oci
import spack.oci.opener


def main() -> int:
    refused = 0
    for name, mirror in spack.mirrors.mirror.MirrorCollection(binary=True).items():
        if not spack.oci.image.is_oci_url(mirror.fetch_url):
            continue
        image = spack.oci.oci.image_from_mirror(mirror).with_tag(spack.binary_distribution.default_index_tag)
        request = urllib.request.Request(
            url=image.manifest_url(), headers={"Accept": ", ".join(spack.oci.oci.all_content_type)}
        )
        try:
            spack.oci.opener.urlopen(request).close()
        except urllib.error.HTTPError as error:
            # A cache without an index answers, and can still hold binaries.
            if error.code != 404:
                refused += 1
                print(f"{name}: {mirror.fetch_url} refuses the request: {error}")
        except Exception as error:
            refused += 1
            print(f"{name}: {mirror.fetch_url} cannot be reached: {error}")
    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
