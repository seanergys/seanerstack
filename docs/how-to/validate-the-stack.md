# Validate Seanerstack changes

Spack-backed validation uses the same isolated state as compiler bootstrap and an activated Seanerstack session. Select that state before running validation:

```console
export SEANERSTACK_STATE_DIR=/path/to/seanerstack-state
seanerstack validate --online --compiler gcc@15 --spack
```

Alternatively, pass `--state-dir /path/to/seanerstack-state` as a global Seanerstack option.

This is the project validation command. It checks the shipped recipes and environments, verifies synchronization against upstream Git, checks the expected compiler configuration, and asks Spack to concretize the shipped environments without consulting normal user or system Spack configuration.

Fix validation failures rather than bypassing individual checks for normal project changes.
