# Synchronize a package recipe

Use `sync` when maintaining a Seanstack recipe whose upstream Git repository has gained a new release tag or tracked development-branch revision.

Synchronize the package:

```console
seanstack package update properdocs
```

Review the resulting `package.py` change and commit it together with the corresponding Seanstack change.

The recipe itself is the source of synchronization metadata. Seanstack reads the upstream Git URL, branch-backed versions, and existing tag-backed versions from `package.py`; there is no parallel Seanstack synchronization configuration.

To check synchronization in CI or before submitting a change without modifying files, use:

```console
seanstack package update --all --check
```
