# Create a secrets file

Credentials for the resources in `config.toml` are kept in a secrets file. Its secret values are encrypted with [keyloom](https://seanergys.github.io/keyloom); every other field stays readable, so the file can be reviewed without the vault password. The `keyloom` command is installed together with Seanerstack when you install it as described in [Set up a workstation](set-up-a-workstation.md) (`--include-deps` for pipx). Without that option, pipx and uv expose only the commands of the package itself, and `keyloom` has to be installed separately with `pipx install keyloom` or `uv tool install keyloom`.

keyloom chooses the file format by extension: `.toml`, `.yaml`/`.yml`, or `.json`. The examples below use TOML.

## 1. Write the credential entries

The names of the entries are fixed: each resource in `config.toml` names the entry it reads with its `credentials` key. The `config.toml` that Seanerstack ships needs these two:

| Entry | Used for | Token scope |
| --- | --- | --- |
| `credentials.seanergys-gitlab` | The SEANERGYS GitLab: reading the repositories of the private recipes, for Seanerstack and for the Git that Spack clones them with. | `read_repository`, `read_api` |
| `credentials.seanergys-registry` | The project build cache in the GitLab container registry. | `read_registry`; `write_registry` to push |

One GitLab access token with these scopes serves both entries.

Write `secrets.toml` with exactly these two tables. Mark every secret value with a `__keyloom__` wrapper. The value `__keyloom__secret__` is a placeholder whose secret is entered when the file is encrypted, so the token is never written to disk in plaintext:

```toml
[credentials.seanergys-gitlab]
username = "oauth2"
token = { __keyloom__ = "secret", value = "__keyloom__secret__" }

[credentials.seanergys-registry]
username = "oauth2"
token = { __keyloom__ = "secret", value = "__keyloom__secret__" }
```

Seanerstack looks an entry up by this name only. An entry with another name is not read, and `seanerstack init` then reports that the resource cannot be read.

A `config.toml` of your own, given with `--config-file`, can name further resources. Each takes an entry named as its `credentials` key, with the fields of its kind:

| Resource | Fields |
| --- | --- |
| Git (`kind = "git"`) | `username` (default `oauth2`); `token` or `password` |
| Build cache with an `oci://` URL | `username` (default `oauth2`); `token` or `password` |
| Build cache with any other URL (S3) | `access_key_id`, `secret_access_key`; optional `session_token` |

```toml
[credentials.objectstore]
access_key_id = "AKIA..."
secret_access_key = { __keyloom__ = "secret", value = "__keyloom__secret__" }
```

Restrict the file to its owner before encrypting it; keyloom keeps the permissions of the file it replaces:

```console
chmod 600 secrets.toml
```

## 2. Encrypt the file

```console
keyloom encrypt secrets.toml
```

keyloom prompts for the vault password, and then for the value of each placeholder; for a new file, both are entered twice. The file is rewritten in place, with comments and formatting kept, and every wrapper value becomes an envelope such as `$KEYLOOM;1;argon2-v2;...`. keyloom also adds a `[__keyloom__]` table at the end of the file, with which it checks the vault password; leave it as it is.

Placeholders require a terminal. In a script, write the value itself into the wrapper, `{ __keyloom__ = "secret", value = "glpat-..." }`, and pass the vault password with `--password-file FILE` or `--password-stdin`. The value is then plaintext on disk until `keyloom encrypt` has run.

## 3. Check the file

```console
keyloom check secrets.toml
keyloom check --verify secrets.toml
```

The first command fails if any secret is not encrypted, and needs no password. The second also decrypts every secret with the vault password. Seanerstack reads the file with the same password:

```console
seanerstack --secrets-file secrets.toml buildcache check
```

## Add or replace a credential

Add the new entry, or replace the envelope of an existing value, with a placeholder, and run `keyloom encrypt secrets.toml` again. keyloom checks the existing envelopes against the vault password before it prompts and leaves them unchanged.

## Change the vault password

```console
keyloom reencrypt --change-password secrets.toml
```

Every secret is decrypted and encrypted again in memory; no plaintext is written.

## Supply the vault password without a prompt

Seanerstack reads the vault password from a file with `--secrets-password-file FILE`, or from the first line of standard input with `--secrets-password-stdin`. Keep a password file readable by its owner only. Do not pass the vault password as a command-line argument.

## Convert a Seanervault file

keyloom does not read Seanervault envelopes. Replace each Seanervault wrapper with a placeholder, then encrypt the file and enter the values again:

```toml
# before
token = { __seanervault__ = "secret", value = "$SEAN_VAULT;..." }
# after
token = { __keyloom__ = "secret", value = "__keyloom__secret__" }
```

```console
keyloom encrypt secrets.toml
```
