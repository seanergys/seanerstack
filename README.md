# Seanerstack

Seanerstack combines two closely related roles for SEANERGYS:

- a curated collection of native Spack package recipes and Spack environments;
- a small command-line tool that synchronizes, bootstraps, validates, and locates that content.

Seanerstack does **not** define its own package, environment, compiler, or toolchain format. Spack remains the source of truth for all of those concepts.

Seanerstack is developed in the SEANERGYS GitLab, at
<https://gitlab.seanergys.fz-juelich.de/software/seanerstack>, which the copy on
GitHub mirrors. The documentation is in [docs](docs/); start with
[Getting started](docs/tutorials/getting-started.md).

## Installation layout

The Python implementation is installed normally, while Spack-facing data is installed under the Python environment prefix:

```text
<prefix>/
├── bin/seanerstack
├── lib/python.../site-packages/seanerstack/
└── share/seanerstack/
    ├── spack-repo-index.yaml
    ├── spack_repo/seanerstack/
    │   ├── repo.yaml
    │   └── packages/
    └── environments/
```

The paths can always be discovered at runtime:

```console
seanerstack paths share
seanerstack paths repo
seanerstack paths env --package properdocs
```

For example:

```console
seanerstack --secrets-file secrets.toml init
export PATH=/opt/seanergys/state/spack/bin:$PATH
seanerstack toolchain bootstrap
eval "$(spack env activate --sh "$(seanerstack paths env --package properdocs)")"
```

`init` sets up the state directory, by default `/opt/seanergys/state`, once:
the pinned Spack, the configuration, the credentials, the build caches and the
CPU target. It checks access to every resource and installs no compiler; no
later command needs its options again. `seanerstack --version` prints the
Seanerstack version and the Spack version it pins.

To build COUNTDOWN with the Access Daemon backend, install
`countdown-seanergys+access_daemon` in a configured Seanerstack session. The
default `countdown-seanergys` spec builds without the backend. For MPI runs that
use the backend, set `CNTD_USE_ACCESS_DAEMON=1`.

## Development

```console
uv sync --all-groups
uv run pytest
uv run seanerstack --help
```

The unit tests are in `tests/unit`. The end-to-end tests in `tests/e2e` install
the wheel of the checkout into a fresh environment and run it against the
SEANERGYS GitLab, with credentials from a keyloom secrets file. They read the
seanerbroker and seanerbus-msg repositories, and build a small package, push it
to a test build cache, and install it back from there. Each build-cache test pushes to its own
repository, `test-e2e-buildcache-<test>`, under the registry location given by
`SEANERSTACK_E2E_REGISTRY`, never to the project build cache. They need Git,
a C compiler, make, and a GitLab token that can read seanerbroker and write to
that location; without a token they are skipped. Seanerstack installs its pinned
Spack for each test, unless `SEANERSTACK_E2E_SPACK` names one of the same version:

```console
export SEANERSTACK_E2E_TOKEN=<GitLab personal access token>
export SEANERSTACK_E2E_REGISTRY=oci://registry.seanergys.fz-juelich.de/<namespace>/<project>
tests/e2e/run.sh
```

The GitLab pipeline runs each file of `tests/e2e` in a job of its own, such as
`e2e:install` and `e2e:buildcache`, with the job token. On GitHub, the `install`
workflow only checks that `seanergys-meta` installs from the public build caches
alone, with and without read access to the private repositories; see
[CI pipelines](docs/explanation/pipelines.md).

Build or serve the documentation:

```console
uv run --group docs properdocs build
uv run --group docs properdocs serve
```

## External resources and secrets

External services are named in `config.toml`.  A resource may refer to a
credential set by name; the credential values themselves stay in a secrets file
encrypted with [keyloom](https://seanergys.github.io/keyloom).

```toml
[resources.seanergys-gitlab]
kind = "git"
url = "https://gitlab.seanergys.fz-juelich.de/"
credentials = "seanergys-gitlab"

[resources.buildcache]
kind = "spack-buildcache"
url = "s3://seanerstack-buildcache"
endpoint_url = "https://objectstore.example.org"
credentials = "objectstore"
autopush = true
signed = false
```

A private package recipe names the Git resource, not the credential:

```python
class PrivatePackage(Package):
    git = "https://gitlab.seanergys.fz-juelich.de/software/private-package.git"
    seanerstack_resource = "seanergys-gitlab"
```

Seanerstack sends the resource credentials to Git with the first request to a
URL under the resource, rather than only after the server asks for them, so an
invalid token fails even for a repository that anyone can read. They are passed
through Git's environment configuration, never on the command line. Older
versions of Git ignore that configuration, so Seanerstack refuses to run Git
with credentials unless it is version 2.31 or later.

A recipe that fetches releases as archives keeps `url` under the same resource.
Seanerstack sends the resource token as a `PRIVATE-TOKEN` header, only over HTTPS,
when downloading new releases to compute their `sha256`:

```python
class PrivatePackage(Package):
    url = "https://gitlab.seanergys.fz-juelich.de/software/private-package/-/archive/v1.0/private-package-v1.0.tar.gz"
    git = "https://gitlab.seanergys.fz-juelich.de/software/private-package.git"
    seanerstack_resource = "seanergys-gitlab"
```

The corresponding secrets file can use a shared credential entry:

```toml
[credentials.seanergys-gitlab]
username = "oauth2"
token = { __keyloom__ = "secret", value = "$KEYLOOM;..." }

[credentials.objectstore]
access_key_id = "..."
secret_access_key = { __keyloom__ = "secret", value = "$KEYLOOM;..." }

[credentials.seanergys-registry]
username = "oauth2"
token = { __keyloom__ = "secret", value = "$KEYLOOM;..." }
```

Write each secret value as the placeholder `__keyloom__secret__` and run
`keyloom encrypt secrets.toml`, which prompts for the vault password and for
each value; see [Create a secrets file](docs/how-to/create-a-secrets-file.md).

Use it without putting either the vault password or service credential on the
command line:

```console
seanerstack \
  --secrets-file ./secrets.toml \
  --secrets-password-file /run/secrets/vault-password \
  package update private-package
```

For interactive use, omit `--secrets-password-file`; Seanerstack prompts for the
vault password. CI may use `--secrets-password-stdin` instead.

`seanerstack init` configures the Spack binary build caches from `config.toml`
in the state; `seanerstack buildcache configure` does it again on its own.

A build cache with an `oci://` URL lives in a container registry and takes
`username` plus `password` or `token`; Spack cannot sign OCI caches, so such a
resource must set `signed = false`. A build cache with a `file://` URL is a
directory on a local or shared filesystem. It takes no credentials, because file
permissions control access to it, and it is unsigned unless the resource sets
`signed = true`. Any other URL is S3 or plain HTTPS, and takes the access key
pair, or no credentials for a cache that anyone can read; an `s3://` cache names
the endpoint of its S3 service in `endpoint_url`, which no other URL uses, and
`seanerstack validate` warns about it elsewhere. The project cache,
`seanerstack-buildcache`, is the seanerstack GitLab container registry;
`seanerstack-buildcache-bootstrap` beside it holds the first stage of the
compiler, with the same credentials, and only the bootstrap instance reads it.
The public build caches on the Juphoria object storage of FZJ hold the toolchain
and the stack too, and anyone can read them over HTTPS without credentials; see
[Use the build cache](docs/how-to/use-the-build-cache.md).

Seanerstack stores only environment-variable references in Spack's mirror
configuration. It never writes S3 keys or registry tokens into Spack
configuration. `seanerstack init --secrets-file FILE` stores the credentials
that the resources name in the state directory instead, readable only by
their owner, and the state's `spack` wrapper loads them into every Spack
process.

## Isolated Spack state

Seanerstack keeps its Spack, the Spack configuration and the mutable state
inside one state directory, by default `/opt/seanergys/state`; `--state-dir DIR`
or `SEANERSTACK_STATE_DIR` selects another. It does not use `~/.spack`,
`/etc/spack`, another Spack store, or another Spack cache.

`seanerstack init` writes a `spack` wrapper into the state. Put it on `PATH`
once, for example in `~/.bashrc`:

```console
$ export PATH=/opt/seanergys/state/spack/bin:$PATH
$ spack find
$ spack install <spec>
```

Plain `spack` is then the native Spack CLI of the pinned version, run with
Seanerstack's private configuration and the stored credentials, in any shell.
The wrapper redirects Spack user data and removes `SPACK_DISABLE_LOCAL_CONFIG`.
The private tree contains the install store, build stages, source and
miscellaneous caches, managed environments, and configuration.

`toolchain bootstrap`, Spack-backed validation, and build-cache commands use the
same state and what `init` recorded in it. There is intentionally no public
Spack `--scope` option.
