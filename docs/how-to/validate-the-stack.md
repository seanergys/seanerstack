# Validate Seanstack changes

Spack-backed validation uses the same isolated state as compiler bootstrap and an activated Seanstack session. Select that state before running validation:

```console
export SEANSTACK_STATE_DIR=/path/to/seanstack-state
seanstack validate --online --compiler gcc@15 --spack
```

Alternatively, pass `--state-dir /path/to/seanstack-state` as a global Seanstack option.

This is the project validation command. It checks the shipped recipes and environments, verifies synchronization against upstream Git, checks the expected compiler configuration, and asks Spack to concretize the shipped environments without consulting normal user or system Spack configuration.

Fix validation failures rather than bypassing individual checks for normal project changes.
