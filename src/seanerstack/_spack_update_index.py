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

import spack.binary_distribution
import spack.error
import spack.mirrors.mirror
import spack.oci.oci
import spack.spec
import spack.stage


def main(name: str) -> int:
    distribution = spack.binary_distribution
    mirror = spack.mirrors.mirror.MirrorCollection(binary=True)[name]
    image = spack.oci.oci.image_from_mirror(mirror)
    tags = [tag for tag in spack.oci.oci.list_tags(image) if distribution.tag_is_spec(tag)]

    fetch = distribution._oci_config_from_tag
    configs, left_out = {}, {}

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
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
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
    with tempfile.TemporaryDirectory(dir=spack.stage.get_stage_root()) as tmpdir, \
            concurrent.futures.ThreadPoolExecutor(16) as executor:
        distribution._oci_update_index(image, tmpdir, executor)

    print(f"indexed {len(configs) - len(left_out)} specs of {name}, left out {len(left_out)}")
    for tag, reason in sorted(left_out.items()):
        print(f"left out {tag}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
