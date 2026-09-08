# Packages and environments

Seanstack does not define package or environment concepts of its own. It curates native Spack package recipes and native Spack environments for SEANERGYS.

## Package recipes

The Seanstack package repository is authoritative for the recipes curated by the project. A recipe records package-specific information such as upstream sources, versions, variants, dependencies, conflicts, and providers.

That information belongs only in `package.py`; Seanstack does not duplicate it in `pyproject.toml` or another metadata format.

## Environments

Seanstack also ships the Spack environments adopted by the project. An environment can represent a development context or, when deployment environments are introduced, a deployment context.

For development, users locate the environment associated with a package and activate it using Spack:

```console
spack env activate "$(seanstack paths env --package properdocs)"
```

A local development checkout is then attached with `spack develop`. Checkout paths remain local because they differ between machines.

The environment files themselves stay native Spack manifests. Seanstack supplies and maintains them; Spack performs the actual environment operations.
