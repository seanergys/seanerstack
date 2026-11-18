# Use the project build cache

Seanerstack ships the SEANERGYS binary build cache as the `seanerstack-buildcache` resource: an OCI build cache in the seanerstack GitLab container registry, `registry.seanergys.fz-juelich.de/software/seanerstack/buildcache`. Spack cannot sign OCI build caches, so the cache is unsigned and registry access control is the trust boundary.

## Provide credentials

The registry takes a GitLab personal access token: `read_registry` to install, `write_registry` to push (`api` covers both). Store it in the secrets file under the name the resource refers to, and encrypt the file as described in [Create a secrets file](create-a-secrets-file.md):

```toml
[credentials.seanergys-registry]
username = "oauth2"
token = { __keyloom__ = "secret", value = "__keyloom__secret__" }
```

Give the file to `init`, which stores the token in the state directory, readable only by you, configures the cache, and checks that it can be read:

```console
seanerstack --secrets-file ./secrets.toml init
```

Spack's mirror configuration names only the variables that hold the token. The state's `spack` wrapper loads them from the stored credentials for every command, and Seanerstack's own commands read the stored credentials too, so no later command needs the secrets file again. Variables that are already set, as in CI, take precedence: `SEANERSTACK_RESOURCE_SEANERSTACK_BUILDCACHE_USERNAME` and `SEANERSTACK_RESOURCE_SEANERSTACK_BUILDCACHE_PASSWORD`.

## Check the cache

```console
seanerstack buildcache check
```

The check fails when the cache cannot be read, and also when its index was written by a newer Spack than the pinned one: Spack then only warns and lists nothing, so nothing in the cache could be installed. Rebuild such an index with `spack buildcache update-index seanerstack-buildcache` from the pinned Spack.

## Install from the cache

A plain `spack install` takes a binary whenever the cache holds the exact spec it concretized, and builds everything else from source. To fail instead of building, install with:

```console
spack install --use-buildcache only
```

A binary matches only when the concretized hash matches, which requires the same Spack version, the same Seanerstack and builtin package recipes, the same compiler at the same install path, operating system, and target microarchitecture as the build that pushed it. `seanerstack init` takes care of all of these but the operating system: it uses the pinned Spack, the default state directory `/opt/seanergys/state`, and the target of `[toolchain]`.

!!! warning "Externals take you off the project build cache"

    `seanerstack toolchain bootstrap --external gcc@16` or `--external rust` uses a compiler or package installed on your machine instead of the one the project builds. Every hash that depends on it then contains your machine's installation, so nothing built with it matches the project build cache, and Spack builds the rest of the stack from source. Do this only when you need that compiler or package. To build each package only once even so, keep your builds in a [filesystem build cache](#use-a-filesystem-build-cache) with `autopush = true`.

## Push to the cache

With a token that has write access, push an installed environment and refresh the index:

```console
eval "$(spack env activate --sh "$(seanerstack paths env --package <package>)")"
spack install
spack buildcache push --update-index seanerstack-buildcache
```

## Prepare the toolchain

The compiler, Rust and `capnproto` take hours to compile, so everyone installs them from the cache. A binary matches only the operating system it was built on, so the toolchain is built once for each platform in `[toolchain]`:

| Platform | Image | Spack's name for it |
| --- | --- | --- |
| `rocky10` | `rockylinux/rockylinux:10` | `rocky10` |
| `rocky9` | `rockylinux/rockylinux:9` | `rocky9` |
| `fedora45` | `fedora:45` | `fedora45` |
| `fedora44` | `fedora:44` | `fedora44` |
| `debian13` | `debian:13` | `debian13` |
| `debian14` | `debian:forky` | `debianforky` |
| `ubuntu26.04` | `ubuntu:26.04` | `ubuntu26.04` |
| `ubuntu24.04` | `ubuntu:24.04` | `ubuntu24.04` |
| `arch` | `archlinux:latest` | `arch` |

Debian 14 is still testing, so Spack names it after its code name until it is released. Arch Linux is a rolling release without a version.

To build for one platform, run this on a desktop with `docker` or `podman`, and a token with `write_registry`:

```console
seanerstack --config-file config.toml --secrets-file credentials.toml buildcache prepare --platform rocky10
```

`--platform all` builds every platform, one after the other. Both files are optional as far as the defaults fit: the build cache comes from `[toolchain]` in `config.toml`, and its token from the secrets file or from the variables `SEANERSTACK_RESOURCE_<NAME>_USERNAME` and `_PASSWORD`. The token is checked before anything is built.

The build runs in the image of the platform, because the operating system is part of every hash: binaries from a desktop's own system would never match those the services install. What the configured caches already hold is reused, every finished package is pushed at once, and the state stays under `~/.cache/seanerstack`, or the directory of `--state-dir` or `SEANERSTACK_STATE_DIR`, one directory per platform, so running the command again continues where it stopped. Inside the image, the build uses `/opt/seanergys/state`, the default state directory, so that its binaries match every machine set up with `seanerstack init`.

`--jobs` defaults to what the free memory allows, and the container gets at most 85 % of that memory. A CI job that already runs in the image of a platform uses `--no-container`.

When the build ends, the index of the cache is rebuilt: every package went to the cache as soon as it was built, and only the rebuilt index lets concretization on other machines find them.

Run it again after changing the Spack version or the `spack-packages` pin, because binaries match only on an identical hash.

### Add a platform

A `config.toml` can add a platform, or change one, and keeps the others:

```toml
[toolchain.platforms.almalinux10]
image = "docker.io/library/almalinux:10"
operating_system = "almalinux10"
package_manager = "dnf"
```

`operating_system` is what `spack arch --operating-system` prints in that image. `package_manager` is `dnf`, `apt` or `pacman`, and chooses the system packages of `[toolchain.system_packages]` that the image gets before Spack runs. A platform can add its own with `system_packages`, and name another Python with `python`, as Rocky 9 does for Python 3.12. Seanerstack and Spack both run with that Python in the image. Fedora 45 names Python 3.14, because Spack 1.2.2 has a ready-made clingo, its solver, for Python up to 3.14, and builds it from source for the Python 3.15 that Fedora 45 has as `python3`.

### Build binaries that install into any directory

Spack rewrites the install prefix inside a binary only into a path that is no longer than the one it was built in. The binaries of the project cache are built below `/opt/seanergys/state`, so they install only below a path of that length or shorter. To build a cache whose binaries install into a state directory of the user's choice, pad the install prefix:

```console
seanerstack --state-dir "$HOME/padded-state" --secrets-file credentials.toml buildcache prepare --platform rocky10 --padded-length 200
```

The build then happens below a prefix of 200 characters, and its binaries install into any shorter path.

!!! warning "Install a padded cache from a lockfile"
    The toolchain compiler is registered at its install path, and that path is part of the hash of every package built with it. In a padded build the path is the padded one, which no user's state has, so a machine that concretizes on its own computes other hashes and finds nothing in a padded cache. Ship the `spack.lock` of the environment with such a cache: installed from the lockfile, the packages keep the hashes of the build, and no compiler is needed.

A state keeps the padding of its first build. `buildcache prepare` refuses another padded length for a state that already holds installations; give the padded build a state directory of its own.

### Build it every night

The `toolchain` job of the CI pipeline runs `buildcache prepare --no-container` for every shipped platform, in parallel, on runners tagged `docker` and `seanerstack`. Each job runs in the image of its platform, so it needs no Docker daemon: it installs Python and the system packages of `[toolchain]`, clones Spack, and builds under `/opt/seanergys/state`, as `buildcache prepare` does in a container. It runs in a pipeline schedule of the default branch, which a maintainer creates under **Build → Pipeline schedules**, for example with the interval `0 1 * * *`, or by hand from **Build → Pipelines → Run pipeline**. It pushes with the job token, which may write to the container registry of the project. After the build, each job runs `buildcache explain` for the compiler and the packages of `[toolchain]`, so the log of a night that built something shows how its specs differ from those the cache held; a failed explanation does not fail the job.

A night in which nothing changed only checks that the cache holds everything. When the hashes change, for example with the Spack version or the `spack-packages` pin, it builds again, which for GCC and Rust takes hours, so the job may run for 12 hours. A unit test keeps the platforms of the job, their images and their Python equal to those in the shipped `config.toml`, so a platform added there also needs an entry in the job's matrix.

## Find out why a package is not taken from the cache

When Spack builds a package that you expected from the cache, ask Seanerstack why:

```console
seanerstack buildcache explain gcc@15.3.0
```

It concretizes the spec as `spack install` would, and compares it with every spec of the same name and version in the configured caches. For each one, it prints the nodes whose own fields differ, from the root down; a node that differs only because one of its dependencies differs is not repeated, so the cause is the lowest node listed:

```text
cached: gcc@15.3.0/frjwpux...  linux-fedora44-zen3
gcc  local /4vm5ymy  cached /frjwpux
    arch.target.name:
        local:  None
        cached: 'zen3'
```

The usual causes are a different CPU target, Spack version, recipe (`package_hash`), operating system, or compiler install path, such as a state directory other than the default or an external compiler. When the caches hold no spec of that name and version at all, it says so.

## Use a filesystem build cache

A build cache can also be a directory on a local or shared filesystem. Declare it as a resource with a `file://` URL in the `config.toml` passed with `--config-file`:

```toml
[resources.local-buildcache]
kind = "spack-buildcache"
url = "file:///scratch/seanerstack/buildcache"
autopush = true
```

A filesystem build cache takes no credentials, because file permissions control access to it. It is unsigned unless the resource sets `signed = true`, in which case Spack needs GPG keys to push to it and to verify what it installs from it. With `autopush = true`, every package that Spack builds is pushed to the cache, so a later installation with the same concretized hashes is taken from the directory instead of being built again.
