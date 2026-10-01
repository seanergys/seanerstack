# Activate the isolated Spack session

Use this procedure whenever you want ordinary `spack` commands to use Seanerstack's private configuration, store, stages, caches, and environments.

## Choose the state directory

Choose one persistent directory for the Seanerstack installation state. It must be writable by the user running Spack.

```console
export SEANERSTACK_STATE_DIR=/path/to/seanerstack-state
```

Seanerstack does not choose a directory under `$HOME` automatically.

## Activate Seanerstack

With `SEANERSTACK_STATE_DIR` set:

```console
eval "$(seanerstack activate)"
```

Alternatively, select the directory on the command line:

```console
eval "$(seanerstack --state-dir /path/to/seanerstack-state activate)"
```

The shell now resolves `spack` through Seanerstack's transparent launcher. Use Spack normally:

```console
spack find
spack spec hdf5
spack install hdf5
```

## Activate with private build-cache credentials

When configured build caches require Seanervault credentials, supply the vault while activating:

```console
eval "$(seanerstack \
    --state-dir /path/to/seanerstack-state \
    --secrets-file ./secrets.toml \
    activate)"
```

For interactive use, Seanerstack prompts for the Seanervault password. The decrypted build-cache credentials are exported only into the activated session; they are not written into Spack configuration.

For a non-interactive session, use one of the existing password-source options instead of placing the vault password on the command line.

## Leave the session

```console
eval "$(seanerstack deactivate)"
```

The shell variables managed by Seanerstack are restored to their pre-activation values.
