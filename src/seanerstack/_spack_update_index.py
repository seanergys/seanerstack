# SPDX-License-Identifier: Apache-2.0
"""Rebuild the index of an OCI build cache, leaving out specs this Spack cannot read.

Run by Seanerstack as `spack python THIS_FILE MIRROR`, inside its isolated
session, so it imports Spack, not Seanerstack.

`spack buildcache update-index` stops at the first spec it cannot read, such as
one that a newer Spack pushed, and leaves the old index in place. Here those
specs are left out of the index and named, and Spack's own code builds and
uploads the index from the rest. The binaries left out stay in the registry,
where nothing finds them.
"""

import concurrent.futures
import sys
import tempfile
import time

import spack.binary_distribution
import spack.config
import spack.error
import spack.mirrors.mirror
import spack.oci.oci
import spack.spec
import spack.stage


# How many requests the registry gets at once. Several jobs rebuild the index
# at the same time, each with this many.
THREADS = 8
# How often a config is asked for, and the pause before the second request,
# which doubles from one to the next: 2, 4, 8 and 16 seconds.
ATTEMPTS = 5
PAUSE = 2


def main(name: str) -> int:
    distribution = spack.binary_distribution
    mirror = spack.mirrors.mirror.MirrorCollection(binary=True)[name]
    image = spack.oci.oci.image_from_mirror(mirror)
    tags = [tag for tag in spack.oci.oci.list_tags(image) if distribution.tag_is_spec(tag)]

    read = distribution._oci_config_from_tag
    configs, left_out = {}, {}

    def fetch(image_and_tag):
        # A registry under load lets a request time out, and Spack does not
        # ask again. One config that cannot be read would stop the rebuild of
        # an index over hundreds, so it is asked for again, a little later
        # each time.
        for attempt in range(ATTEMPTS):
            try:
                return read(image_and_tag)
            except Exception as error:
                if attempt == ATTEMPTS - 1:
                    raise
                print(f"{image_and_tag[1]}: {error}; reading it again", flush=True)
                time.sleep(PAUSE * 2**attempt)

    def record(tag, config):
        configs[tag] = config
        if config is None:
            left_out[tag] = "not a spec"
            return
        try:
            spack.spec.Spec.from_dict(config)
        except (ValueError, KeyError, TypeError, spack.error.SpackError) as error:
            left_out[tag] = str(error)

    # A registry that cannot be read stops the rebuild, as in Spack.
    with concurrent.futures.ThreadPoolExecutor(THREADS) as pool:
        for tag, config in zip(tags, pool.map(lambda tag: fetch((image, tag)), tags)):
            record(tag, config)

    is_spec = distribution.tag_is_spec

    def indexed(tag):
        if not is_spec(tag):
            return False
        # Spack lists the tags again. A job that runs at the same time may
        # have pushed a binary since the listing above, and it is read now.
        if tag not in configs:
            record(tag, fetch((image, tag)))
        return tag not in left_out

    # Spack's rebuild, with the configs already fetched and without the specs
    # it cannot read. Threads, not Spack's process pool, which cannot run the
    # replacement for fetching a config.
    distribution.tag_is_spec = indexed
    distribution._oci_config_from_tag = lambda image_and_tag: configs[image_and_tag[1]]
    with tempfile.TemporaryDirectory(dir=spack.stage.stage_root(spack.config.CONFIG)) as tmpdir, \
            concurrent.futures.ThreadPoolExecutor(THREADS) as executor:
        distribution._oci_update_index(image, tmpdir, executor)

    print(f"indexed {len(configs) - len(left_out)} specs of {name}, left out {len(left_out)}")
    for tag, reason in sorted(left_out.items()):
        print(f"left out {tag}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
