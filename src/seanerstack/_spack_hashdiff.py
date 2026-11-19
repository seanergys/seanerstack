# SPDX-License-Identifier: Apache-2.0
"""Explain why a locally concretized spec does not match the build cache.

Run by Seanerstack as `spack python THIS_FILE [--match=os|target|all] SPEC`,
inside its isolated session, so it imports Spack, not Seanerstack;
`seanerstack buildcache explain SPEC` does that.

For every cached spec with the same name and version, and by default the same
operating system, walks both DAGs and prints the nodes whose own fields
differ (package_hash, variants, arch, ...). `--match=target` takes only the
cached specs of the same target as well, `--match=all` those of every platform.
A node whose hash differs only because a dependency differs is not repeated;
the reason sits lower in the graph.
"""

import sys

import spack
import spack.binary_distribution
import spack.concretize
import spack.config
import spack.spec


def node_fields(spec):
    """Return the node's hashed fields without dependencies and hashes."""
    node = dict(spec.to_node_dict())
    node.pop("dependencies", None)
    node.pop("hash", None)
    return node


def flat(value, prefix=""):
    """Flatten nested dicts to {dotted.key: value}."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            out.update(flat(item, f"{prefix}.{key}" if prefix else str(key)))
        return out
    return {prefix: value}


def edges(spec):
    """Return {dependency name: (edge depflag, virtuals, dependency spec)}."""
    return {
        edge.spec.name: (edge.depflag, tuple(sorted(edge.virtuals)), edge.spec)
        for edge in spec.edges_to_dependencies()
    }


def compare(local, cached, path, seen, report):
    key = (local.dag_hash(), cached.dag_hash())
    if key in seen or local.dag_hash() == cached.dag_hash():
        return
    seen.add(key)

    a, b = flat(node_fields(local)), flat(node_fields(cached))
    fields = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))

    ea, eb = edges(local), edges(cached)
    only_local = sorted(ea.keys() - eb.keys())
    only_cached = sorted(eb.keys() - ea.keys())
    edge_changes = sorted(n for n in ea.keys() & eb.keys() if ea[n][:2] != eb[n][:2])

    if fields or only_local or only_cached or edge_changes:
        lines = [f"{' -> '.join(path)}  local /{local.dag_hash(7)}  cached /{cached.dag_hash(7)}"]
        for k in fields:
            lines.append(f"    {k}:\n        local:  {a.get(k)!r}\n        cached: {b.get(k)!r}")
        for n in only_local:
            lines.append(f"    dependency only in local:  {ea[n][2].format('{name}{@version}{/hash:7}')}")
        for n in only_cached:
            lines.append(f"    dependency only in cached: {eb[n][2].format('{name}{@version}{/hash:7}')}")
        for n in edge_changes:
            lines.append(f"    edge to {n}: local {ea[n][:2]}  cached {eb[n][:2]}")
        report.append("\n".join(lines))

    for n in sorted(ea.keys() & eb.keys()):
        compare(ea[n][2], eb[n][2], path + [n], seen, report)


MATCHES = ("os", "target", "all")


def select(local, cached, match):
    """The cached specs to compare with: those a machine like this one could install.

    A cache holds the same package for every platform it is built on, and a
    spec for another operating system differs in every node, which says
    nothing about why this machine builds.

    Returns the chosen specs, and for the rest how many there are for each
    operating system and target.
    """
    def fits(spec):
        if match == "all":
            return True
        same_os = spec.architecture.os == local.architecture.os
        return same_os and (match == "os" or str(spec.architecture.target) == str(local.architecture.target))

    chosen = [spec for spec in cached if fits(spec)]
    left_out = {}
    for spec in cached:
        if not fits(spec):
            key = f"{spec.architecture.os}-{spec.architecture.target}"
            left_out[key] = left_out.get(key, 0) + 1
    return chosen, left_out


def main(argv):
    match = "os"
    if argv and argv[0].startswith("--match="):
        match, argv = argv[0].partition("=")[2], argv[1:]
    if len(argv) != 1 or match not in MATCHES:
        print(__doc__)
        return 2
    print(f"spack {spack.spack_version}")
    local = spack.concretize.concretize_one(argv[0])
    print(f"local:  {local.format('{name}{@version}{/hash}')}  {local.format('{arch}')}")

    cached = [
        s
        for s in spack.binary_distribution.update_cache_and_get_specs(config=spack.config.CONFIG)
        if s.name == local.name and s.version == local.version
    ]
    if not cached:
        print(f"no {local.name}@{local.version} in any configured build cache")
        return 1

    chosen, left_out = select(local, cached, match)
    wanted = {
        "os": f"for {local.architecture.os}",
        "target": f"for {local.architecture.os} and {local.architecture.target}",
        "all": "for any platform",
    }[match]
    print(f"cached: {len(cached)} of {local.name}@{local.version}, {len(chosen)} {wanted}")
    if left_out:
        others = ", ".join(f"{key} ({count})" for key, count in sorted(left_out.items()))
        print(f"not compared: {others}; --all compares them too")
    if not chosen:
        return 1

    for c in chosen:
        print(f"\ncached: {c.format('{name}{@version}{/hash}')}  {c.format('{arch}')}")
        if c.dag_hash() == local.dag_hash():
            print("    identical: the cache should be used")
            continue
        report = []
        compare(local, c, [local.name], set(), report)
        print("\n\n".join(report) if report else "    no field differences found (hash method differs?)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
