# Use the project build cache

Seanerstack ships the SEANERGYS binary build cache as the `seanerstack-buildcache` resource: an OCI build cache in the seanerstack GitLab container registry, `registry.seanergys.fz-juelich.de/software/seanerstack/buildcache`. Spack cannot sign OCI build caches, so the cache is unsigned and registry access control is the trust boundary.

## Provide credentials

The registry takes a GitLab personal access token: `read_registry` to install, `write_registry` to push (`api` covers both). Store it in the secrets file under the name the resource refers to, and encrypt the file as described in [Create a secrets file](create-a-secrets-file.md):

```toml
[credentials.seanergys-registry]
username = "oauth2"
token = { __keyloom__ = "secret", value = "__keyloom__secret__" }
```

Activation with that file exports the token into the session:

```console
export SEANERSTACK_STATE_DIR=/path/to/seanerstack-state
eval "$(seanerstack --secrets-file ./secrets.toml activate)"
```

Without a secrets file, export `SEANERSTACK_RESOURCE_SEANERSTACK_BUILDCACHE_USERNAME` and `SEANERSTACK_RESOURCE_SEANERSTACK_BUILDCACHE_PASSWORD` yourself.

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

## Prepare the toolchain

The compiler, Rust and `capnproto` take hours to compile, so everyone installs them from the cache. To put them there, run this on a desktop with `docker` or `podman`, and a token with `write_registry`:

```console
seanerstack --config-file config.toml --secrets-file credentials.toml buildcache prepare
```

Both files are optional as far as the defaults fit: the build cache comes from `[toolchain]` in `config.toml`, and its token from the secrets file. The token is checked before anything is built.

The build runs in the image of `[toolchain]`, because the operating system is part of every hash: binaries from a desktop's own system would never match those the services install. What the configured caches already hold is reused, every finished package is pushed at once, and the state stays under `~/.cache/seanerstack` or `--state-dir`, so running the command again continues where it stopped.

`--jobs` defaults to what the free memory allows, and the container gets at most 85 % of that memory. A CI job that already runs in the image uses `--no-container`.

Run it again after changing the Spack version or the `spack-packages` pin, because binaries match only on an identical hash.

## Use a filesystem build cache

A build cache can also be a directory on a local or shared filesystem. Declare it as a resource with a `file://` URL in the `config.toml` passed with `--config-file`:

```toml
[resources.local-buildcache]
kind = "spack-buildcache"
url = "file:///scratch/seanerstack/buildcache"
autopush = true
```

A filesystem build cache takes no credentials, because file permissions control access to it. It is unsigned unless the resource sets `signed = true`, in which case Spack needs GPG keys to push to it and to verify what it installs from it. With `autopush = true`, every package that Spack builds is pushed to the cache, so a later installation with the same concretized hashes is taken from the directory instead of being built again.
