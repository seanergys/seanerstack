# Validate Seanerstack changes

Spack-backed validation uses the state that `seanerstack init` set up, by default `/opt/seanergys/state`, with the configuration and credentials it recorded:

```console
seanerstack validate --online --compiler gcc@15 --spack
```

For another state directory, pass `--state-dir DIR` or set `SEANERSTACK_STATE_DIR`.

This is the project validation command. It checks the shipped recipes and environments, verifies synchronization against upstream Git, checks the expected compiler configuration, and asks Spack to concretize the shipped environments without consulting normal user or system Spack configuration.

It also warns about an option of a `config.toml` resource that the resource's URL has no use for, such as `endpoint_url`, which names an S3 service, on a resource whose URL is not `s3://`. A warning does not fail the command.

Fix validation failures rather than bypassing individual checks for normal project changes.
