# Use the project build cache

Seanerstack ships the SEANERGYS binary build cache as the `seanerstack-buildcache` resource: an OCI build cache in the seanerstack GitLab container registry, `registry.seanergys.fz-juelich.de/software/seanerstack/buildcache`. Spack cannot sign OCI build caches, so the cache is unsigned and registry access control is the trust boundary.

## Provide credentials

The registry takes a GitLab personal access token: `read_registry` to install, `write_registry` to push (`api` covers both). Store it in a keyloom secrets file under the name the resource refers to. Write the entry with a placeholder:

```toml
[credentials.seanergys-registry]
username = "oauth2"
token = { __keyloom__ = "secret", value = "__keyloom__secret__" }
```

Then encrypt the file in place; `keyloom` prompts for the vault password and for the token:

```console
keyloom encrypt secrets.toml
```

The `keyloom` command is installed together with Seanerstack.

Activation with that vault exports the token into the session:

```console
export SEANERSTACK_STATE_DIR=/path/to/seanerstack-state
eval "$(seanerstack --secrets-file ./secrets.toml activate)"
```

Without a vault, export `SEANERSTACK_RESOURCE_SEANERSTACK_BUILDCACHE_USERNAME` and `SEANERSTACK_RESOURCE_SEANERSTACK_BUILDCACHE_PASSWORD` yourself.

## Configure and check the cache

```console
seanerstack buildcache configure
seanerstack buildcache check
```

`configure` adds the cache as a binary mirror to the isolated configuration. Spack stores only the variable names, never the token.

## Install from the cache

A plain `spack install` takes a binary whenever the cache holds the exact spec it concretized, and builds everything else from source. To fail instead of building, install with:

```console
spack install --use-buildcache only
```

A binary matches only when the concretized hash matches, which requires the same Spack version, the same Seanerstack and builtin package recipes, the same compiler configuration, operating system, and target microarchitecture as the build that pushed it.

## Push to the cache

With a token that has write access, push an installed environment and refresh the index:

```console
spack env activate "$(seanerstack paths env --package <package>)"
spack install
spack buildcache push --update-index seanerstack-buildcache
```
