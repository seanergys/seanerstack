# Packages and environments

Seanstack does not define package or environment concepts of its own. It curates native Spack package recipes and native Spack environments for SEANERGYS.

## Package recipes

The Seanstack package repository is authoritative for the recipes curated by the project. A recipe records package-specific information such as upstream sources, versions, variants, dependencies, conflicts, and providers.

That information belongs only in `package.py`; Seanstack does not duplicate it in `pyproject.toml` or another metadata format.

The repository is installed into Seanstack's private Spack configuration automatically. Users should not add it to their normal user Spack configuration with `spack repo add`.

## Environments

Seanstack also ships the Spack environments adopted by the project. An environment can represent a development context or, when deployment environments are introduced, a deployment context.

First activate the isolated Seanstack Spack session, then locate and activate the environment using Spack:

```console
export SEANSTACK_STATE_DIR=/path/to/seanstack-state
eval "$(seanstack activate)"
spack env activate "$(seanstack paths env --package properdocs)"
```

A local development checkout is then attached with `spack develop`. Checkout paths remain local because they differ between machines.

The environment files themselves stay native Spack manifests. Seanstack supplies and maintains them; Spack performs the actual environment operations inside the selected Seanstack state.
