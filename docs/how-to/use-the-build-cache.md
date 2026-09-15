# Use the project build cache

Seanstack ships the SEANERGYS binary build cache as the `seanstack-buildcache` resource: an OCI build cache in the seanstack GitLab container registry, `registry.seanergys.fz-juelich.de/software/seanstack/buildcache`. Spack cannot sign OCI build caches, so the cache is unsigned and registry access control is the trust boundary.

## Provide credentials

The registry takes a GitLab personal access token: `read_registry` to install, `write_registry` to push (`api` covers both). Store it in SeanVault under the name the resource refers to:

```toml
[credentials.seanergys-registry]
username = "oauth2"
token = { __seanvault__ = "secret", value = "$SEAN_VAULT;..." }
```

Activation with that vault exports the token into the session:

```console
export SEANSTACK_STATE_DIR=/path/to/seanstack-state
eval "$(seanstack --secrets-file ./secrets.toml activate)"
```

Without a vault, export `SEANSTACK_RESOURCE_SEANSTACK_BUILDCACHE_USERNAME` and `SEANSTACK_RESOURCE_SEANSTACK_BUILDCACHE_PASSWORD` yourself.

## Configure and check the cache

```console
seanstack buildcache configure
seanstack buildcache check
```

`configure` adds the cache as a binary mirror to the isolated configuration. Spack stores only the variable names, never the token.

## Install from the cache

A plain `spack install` takes a binary whenever the cache holds the exact spec it concretized, and builds everything else from source. To fail instead of building, install with:

```console
spack install --use-buildcache only
```

A binary matches only when the concretized hash matches, which requires the same Spack version, the same Seanstack and builtin package recipes, the same compiler configuration, operating system, and target microarchitecture as the build that pushed it.

## Push to the cache

With a token that has write access, push an installed environment and refresh the index:

```console
spack env activate "$(seanstack paths env --package <package>)"
spack install
spack buildcache push --update-index seanstack-buildcache
```
