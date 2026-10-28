# Seanerstack

Seanerstack combines two closely related roles for SEANERGYS:

- a curated collection of native Spack package recipes and Spack environments;
- a small command-line tool that synchronizes, bootstraps, validates, and locates that content.

Seanerstack does **not** define its own package, environment, compiler, or toolchain format. Spack remains the source of truth for all of those concepts.

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
export SEANERSTACK_STATE_DIR=/path/to/seanerstack-state
seanerstack toolchain bootstrap gcc@15
eval "$(seanerstack activate)"
spack env activate "$(seanerstack paths env --package properdocs)"
```

## Development

```console
uv sync --all-groups
uv run pytest
uv run seanerstack --help
```

The unit tests are in `tests/unit`. The end-to-end tests in `tests/e2e` install
the wheel of the checkout into a fresh environment and run it against the
SEANERGYS GitLab, with credentials from a keyloom secrets file. They read the
demobus repository, and build a small package, push it to a test build cache,
and install it back from there. Each build-cache test pushes to its own
repository, `test-e2e-buildcache-<test>`, under the registry location given by
`SEANERSTACK_E2E_REGISTRY`, never to the project build cache. They need Git,
Spack, a C compiler, make, and a GitLab token that can read demobus and write to
that location; without a token they are skipped:

```console
export SEANERSTACK_E2E_TOKEN=<GitLab personal access token>
export SEANERSTACK_E2E_SPACK=/path/to/spack/bin/spack
export SEANERSTACK_E2E_REGISTRY=oci://registry.seanergys.fz-juelich.de/<namespace>/<project>
tests/e2e/run.sh
```

CI runs them in the `e2e` job with the job token.

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

Configure the Spack binary build caches from `config.toml` in the selected isolated state with:

```console
seanerstack --state-dir /path/to/seanerstack-state buildcache configure
```

A build cache with an `oci://` URL lives in a container registry and takes
`username` plus `password` or `token`; Spack cannot sign OCI caches, so such a
resource must set `signed = false`. A build cache with a `file://` URL is a
directory on a local or shared filesystem. It takes no credentials, because file
permissions control access to it, and it is unsigned unless the resource sets
`signed = true`. Any other URL is S3 and takes the access key pair. The project
cache, `seanerstack-buildcache`, is the seanerstack GitLab container registry.

Seanerstack stores only environment-variable references in Spack's mirror
configuration. It never writes S3 keys or registry tokens into Spack
configuration. The actual variables must be present in any later native
`spack` process that accesses a private cache; this is intentionally left as a
process/session concern rather than storing decrypted credentials on disk.

## Isolated Spack session

Seanerstack keeps Spack configuration and mutable state inside one explicitly selected
state directory. It does not use `~/.spack`, `/etc/spack`, another Spack store, or
another Spack cache for Seanerstack-managed operations.

Activate a shell with:

```console
$ eval "$(seanerstack --state-dir /path/to/seanerstack-state activate)"
$ spack find
$ spack install <spec>
```

After activation, plain `spack` is the native Spack CLI executed with Seanerstack's
private configuration. The session sets `SEANERSTACK_STATE_DIR`, disables normal
local Spack configuration, redirects Spack user data, and places a transparent
launcher first on `PATH`. The private tree contains the install store, build
stages, source and miscellaneous caches, managed environments, and configuration.

If the private build cache needs credentials, activate with the existing secrets
options, for example:

```console
$ eval "$(seanerstack --state-dir /path/to/seanerstack-state --secrets-file secrets.toml activate)"
```

Leave the session with:

```console
$ eval "$(seanerstack deactivate)"
```

`toolchain bootstrap`, Spack-backed validation, and build-cache commands use the
same isolated state. Outside an activated shell, pass `--state-dir DIR` or set
`SEANERSTACK_STATE_DIR`. There is intentionally no public Spack `--scope` option.
