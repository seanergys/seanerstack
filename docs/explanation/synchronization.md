# Synchronization

Seanerstack's package recipes are authoritative for the SEANERGYS stack, while upstream Git repositories are authoritative for their tags and tracked branches.

`seanerstack package update` keeps those two sources aligned without introducing another package metadata file.

For each recipe, Seanerstack reads:

- the upstream Git repository from the recipe;
- tracked development branches from branch-backed `version` directives;
- the release-tag convention from existing tag-backed versions.

For example:

```python
version("1.6.7", tag="v1.6.7")
version("1.6.6", tag="v1.6.6")
```

establishes the `v{version}` convention. A new upstream `v1.6.8` can therefore be added as a new native Spack version directive.

## Archive releases

A recipe may fetch releases as archives instead of cloning Git:

```python
url = "https://gitlab.seanergys.fz-juelich.de/software/seanerbroker/-/archive/v0.2.1/seanerbroker-v0.2.1.tar.gz"
git = "https://gitlab.seanergys.fz-juelich.de/software/seanerbroker.git"

version("main", branch="main")
version("0.2.1", sha256="3a5c...")
```

Upstream tags are still read from `git`. The release-tag convention comes from the `url` path segment holding one of the recipe's `sha256` versions; when several segments hold it, the one naming an existing upstream tag is used. Here `v0.2.1` establishes `v{version}`.

For a new tag, Seanerstack substitutes the version into `url` as Spack does, downloads the archive, and adds `version("X", sha256="...")`. Only gzip archives (`.tar.gz`) are supported; any other download, such as a sign-in page, is an error. `--check`, `--dry-run`, and `validate --online` only report missing releases; they download nothing and do not re-verify existing checksums.

A recipe that mixes `tag=` and `sha256=` releases is rejected.

GitLab generates `/-/archive/` tarballs on demand. They are byte-stable today, but a GitLab upgrade could change them and invalidate recorded checksums.

If the existing recipe does not establish one unambiguous convention, synchronization fails rather than creating Seanerstack-specific synchronization metadata.

## Recipes without releases

A recipe with branches but no releases, such as `seanerbroker` with only `version("main", branch="main")`, follows those branches. Synchronization checks that they still exist upstream, and takes no releases from the upstream tags, so it needs no convention.

## Recipes without a Git URL

Synchronization reads upstream through Git, so `validate --online` and `package update --all` leave out a recipe without a `git` URL, such as `py-pycapnp`, which fetches from PyPI, or one that extends a recipe of Spack and takes its versions from there. `package update` with the name of such a recipe reports that it has no Git URL.
