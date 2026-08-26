# Validate Seanstack changes

Run the standard validation before submitting changes to Seanstack:

```console
seanstack validate --online --compiler gcc@15 --spack
```

This is the project validation command. It checks the shipped recipes and environments, verifies synchronization against upstream Git, checks the expected compiler configuration, and asks Spack to concretize the shipped environments.

Fix validation failures rather than bypassing individual checks for normal project changes.
