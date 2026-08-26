# Synchronization

Seanstack's package recipes are authoritative for the SEANERGYS stack, while upstream Git repositories are authoritative for their tags and tracked branches.

`seanstack sync` keeps those two sources aligned without introducing another package metadata file.

For each recipe, Seanstack reads:

- the upstream Git repository from the recipe;
- tracked development branches from branch-backed `version` directives;
- the release-tag convention from existing tag-backed versions.

For example:

```python
version("1.6.7", tag="v1.6.7")
version("1.6.6", tag="v1.6.6")
```

establishes the `v{version}` convention. A new upstream `v1.6.8` can therefore be added as a new native Spack version directive.

If the existing recipe does not establish one unambiguous convention, synchronization fails rather than creating Seanstack-specific synchronization metadata.
