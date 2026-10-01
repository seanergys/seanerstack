# Synchronize a package recipe

Use `sync` when maintaining a Seanerstack recipe whose upstream Git repository has gained a new release tag or tracked development-branch revision.

Synchronize the package:

```console
seanerstack package update properdocs
```

Review the resulting `package.py` change and commit it together with the corresponding Seanerstack change.

The recipe itself is the source of synchronization metadata. Seanerstack reads the upstream Git URL, branch-backed versions, and existing tag-backed or `sha256` archive versions from `package.py`; there is no parallel Seanerstack synchronization configuration.

For a recipe with `url` and `sha256` releases, new releases are downloaded to compute their checksums. A private archive needs the recipe's `seanerstack_resource` and the Seanervault options:

```console
seanerstack --secrets-file ./secrets.toml package update demobus
```

To check synchronization in CI or before submitting a change without modifying files, use:

```console
seanerstack package update --all --check
```
