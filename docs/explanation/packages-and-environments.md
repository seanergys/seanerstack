# Packages and environments

Seanerstack does not define package or environment concepts of its own. It curates native Spack package recipes and native Spack environments for SEANERGYS.

## Package recipes

The Seanerstack package repository is authoritative for the recipes curated by the project. A recipe records package-specific information such as upstream sources, versions, variants, dependencies, conflicts, and providers.

That information belongs only in `package.py`; Seanerstack does not duplicate it in `pyproject.toml` or another metadata format.

The repository is installed into Seanerstack's private Spack configuration automatically. Users should not add it to their normal user Spack configuration with `spack repo add`.

## Environments

Seanerstack also ships the Spack environments adopted by the project. An environment can represent a development context or, when deployment environments are introduced, a deployment context.

With the state's `spack` on `PATH`, locate the environment with Seanerstack and activate it with Spack:

```console
eval "$(spack env activate --sh "$(seanerstack paths env --package priorisea)")"
```

A local development checkout is then attached with `spack develop`. Checkout paths remain local because they differ between machines.

The environment files themselves stay native Spack manifests. Seanerstack supplies and maintains them; Spack performs the actual environment operations inside the selected Seanerstack state.
