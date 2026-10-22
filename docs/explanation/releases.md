# Seanerstack releases

A Seanerstack release is a snapshot of the complete SEANERGYS Spack distribution at a particular point in time. The version covers the command-line tooling, curated package recipes, and shipped environments together.

Individual recipes and environments are not given independent Seanerstack release numbers.

## Versioning scheme

Seanerstack stays in the `0.x.y` series until it is in regular use by almost all partners. Semantic versioning is not meaningful yet at that stage, so the numbers are kept deliberately small:

- Patches go `0.x.1` through `0.x.9`.
- A minor bump (`0.x+1.0`) is used instead of letting the patch number grow large, even for changes that are not breaking.

Once usage is established across partners (tentatively around January/February 2027), Seanerstack moves to `1.0.0` and switches to strict [semantic versioning](https://semver.org/):

- Patch releases are reserved for bugfixes.
- Everything else is a minor release.
- A major bump (e.g. `1.9.0 -> 2.0.0`) happens once the minor number would otherwise grow large, regardless of whether the triggering change is breaking.

See [work item #21](https://gitlab.seanergys.fz-juelich.de/software/seanerstack/-/work_items/21) for the discussion behind this scheme.

## Release process

A maintainer owns cutting releases. The current version maintainer is Radek Lonka.

Cutting a release:

1. On the default branch, make a dedicated commit that only bumps the version — in `pyproject.toml` and `src/seanerstack/__init__.py` — and adds the new section to [`CHANGELOG.md`](https://gitlab.seanergys.fz-juelich.de/software/seanerstack/-/blob/main/CHANGELOG.md).
2. Tag that commit `vMAJOR.MINOR.PATCH` (e.g. `v0.1.0`) and push the tag.
3. Pushing the tag triggers the `publish` job, which builds the distribution with `uv build` and publishes it with `uv publish` to the GitLab group PyPI registry.

This process is currently manual. Automating the version bump and tagging through a dedicated CI runner is tracked as future work.

The self-managed SEANERGYS GitLab instance cannot currently use PyPI's GitLab Trusted Publishing integration, which is limited to projects hosted on `gitlab.com`. The GitLab project therefore provides a protected and masked `UV_PUBLISH_TOKEN` CI/CD variable for the PyPI project.

## Installing releases

```console
pip install --upgrade seanerstack
```

When reproducibility requires an exact Seanerstack release, pin the version:

```console
pip install seanerstack==0.1.0
```
