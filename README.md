# Seanstack

Seanstack combines two closely related roles for SEANERGYS:

- a curated collection of native Spack package recipes and Spack environments;
- a small command-line tool that synchronizes, bootstraps, validates, and locates that content.

Seanstack does **not** define its own package, environment, compiler, or toolchain format. Spack remains the source of truth for all of those concepts.

## Installation layout

The Python implementation is installed normally, while Spack-facing data is installed under the Python environment prefix:

```text
<prefix>/
├── bin/seanstack
├── lib/python.../site-packages/seanstack/
└── share/seanstack/
    ├── spack-repo-index.yaml
    ├── spack_repo/seanstack/
    │   ├── repo.yaml
    │   └── packages/
    └── environments/
```

The paths can always be discovered at runtime:

```console
seanstack paths share
seanstack paths repo
seanstack paths env --package properdocs
```

For example:

```console
export SEANSTACK_STATE_DIR=/path/to/seanstack-state
seanstack toolchain bootstrap gcc@15
eval "$(seanstack activate)"
spack env activate "$(seanstack paths env --package properdocs)"
```

## Development

```console
uv sync --all-groups
uv run pytest
uv run seanstack --help
```

Build or serve the documentation:

```console
uv run --group docs properdocs build
uv run --group docs properdocs serve
```

## External resources and secrets

External services are named in `config.toml`.  A resource may refer to a
credential set by name; the credential values themselves stay in a Seanervault
file.

```toml
[resources.seanergys-gitlab]
kind = "git"
url = "https://gitlab.seanergys.fz-juelich.de/"
credentials = "seanergys-gitlab"

[resources.buildcache]
kind = "spack-buildcache"
url = "s3://seanstack-buildcache"
endpoint_url = "https://objectstore.example.org"
credentials = "objectstore"
autopush = true
signed = false
```

A private package recipe names the Git resource, not the credential:

```python
class PrivatePackage(Package):
    git = "https://gitlab.seanergys.fz-juelich.de/software/private-package.git"
    seanstack_resource = "seanergys-gitlab"
```

A recipe that fetches releases as archives keeps `url` under the same resource.
Seanstack sends the resource token as a `PRIVATE-TOKEN` header, only over HTTPS,
when downloading new releases to compute their `sha256`:

```python
class PrivatePackage(Package):
    url = "https://gitlab.seanergys.fz-juelich.de/software/private-package/-/archive/v1.0/private-package-v1.0.tar.gz"
    git = "https://gitlab.seanergys.fz-juelich.de/software/private-package.git"
    seanstack_resource = "seanergys-gitlab"
```

The corresponding Seanervault file can use a shared credential entry:

```toml
[credentials.seanergys-gitlab]
username = "oauth2"
token = { __seanervault__ = "secret", value = "$SEAN_VAULT;..." }

[credentials.objectstore]
access_key_id = "..."
secret_access_key = { __seanervault__ = "secret", value = "$SEAN_VAULT;..." }

[credentials.seanergys-registry]
username = "oauth2"
token = { __seanervault__ = "secret", value = "$SEAN_VAULT;..." }
```

Use it without putting either the vault password or service credential on the
command line:

```console
seanstack \
  --secrets-file ./secrets.toml \
  --secrets-password-file /run/secrets/seanervault-password \
  package update private-package
```

For interactive use, omit `--secrets-password-file`; Seanstack prompts for the
Seanervault password. CI may use `--secrets-password-stdin` instead.

Configure the Spack binary build caches from `config.toml` in the selected isolated state with:

```console
seanstack --state-dir /path/to/seanstack-state buildcache configure
```

A build cache with an `oci://` URL lives in a container registry and takes
`username` plus `password` or `token`; Spack cannot sign OCI caches, so such a
resource must set `signed = false`. Any other URL is S3 and takes the access key
pair. The project cache, `seanstack-buildcache`, is the seanstack GitLab
container registry.

Seanstack stores only environment-variable references in Spack's mirror
configuration. It never writes S3 keys or registry tokens into Spack
configuration. The actual variables must be present in any later native
`spack` process that accesses a private cache; this is intentionally left as a
process/session concern rather than storing decrypted credentials on disk.

## Isolated Spack session

SeanStack keeps Spack configuration and mutable state inside one explicitly selected
state directory. It does not use `~/.spack`, `/etc/spack`, another Spack store, or
another Spack cache for SeanStack-managed operations.

Activate a shell with:

```console
$ eval "$(seanstack --state-dir /path/to/seanstack-state activate)"
$ spack find
$ spack install <spec>
```

After activation, plain `spack` is the native Spack CLI executed with SeanStack's
private configuration. The session sets `SEANSTACK_STATE_DIR`, disables normal
local Spack configuration, redirects Spack user data, and places a transparent
launcher first on `PATH`. The private tree contains the install store, build
stages, source and miscellaneous caches, managed environments, and configuration.

If the private build cache needs credentials, activate with the existing Seanervault
options, for example:

```console
$ eval "$(seanstack --state-dir /path/to/seanstack-state --secrets-file secrets.toml activate)"
```

Leave the session with:

```console
$ eval "$(seanstack deactivate)"
```

`toolchain bootstrap`, Spack-backed validation, and build-cache commands use the
same isolated state. Outside an activated shell, pass `--state-dir DIR` or set
`SEANSTACK_STATE_DIR`. There is intentionally no public Spack `--scope` option.
