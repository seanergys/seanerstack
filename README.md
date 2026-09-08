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
spack repo add "$(seanstack paths repo)"
seanstack toolchain bootstrap gcc@15
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
credential set by name; the credential values themselves stay in a SeanVault
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

The corresponding SeanVault file can use a shared credential entry:

```toml
[credentials.seanergys-gitlab]
username = "oauth2"
token = { __seanvault__ = "secret", value = "$SEAN_VAULT;..." }

[credentials.objectstore]
access_key_id = "..."
secret_access_key = { __seanvault__ = "secret", value = "$SEAN_VAULT;..." }
```

Use it without putting either the vault password or service credential on the
command line:

```console
seanstack \
  --secrets-file ./secrets.toml \
  --secrets-password-file /run/secrets/seanvault-password \
  package update private-package
```

For interactive use, omit `--secrets-password-file`; Seanstack prompts for the
SeanVault password. CI may use `--secrets-password-stdin` instead.

Configure S3-backed Spack binary build caches from `config.toml` with:

```console
seanstack buildcache configure
```

Seanstack stores only environment-variable references in Spack's mirror
configuration. It never writes the S3 access key or secret key into Spack
configuration. The actual variables must be present in any later native
`spack` process that accesses a private cache; this is intentionally left as a
process/session concern rather than storing decrypted credentials on disk.
