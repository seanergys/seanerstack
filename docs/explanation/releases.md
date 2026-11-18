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

1. On the default branch, make a dedicated commit that only bumps the version in `pyproject.toml` with `uv version MAJOR.MINOR.PATCH` and adds the new section to [`CHANGELOG.md`](https://gitlab.seanergys.fz-juelich.de/software/seanerstack/-/blob/main/CHANGELOG.md). `pyproject.toml` is the only place that defines the version; `seanerstack.__version__` reads it from the installed package metadata.
2. Tag that commit `vMAJOR.MINOR.PATCH` (e.g. `v0.1.0`) and push the tag.
3. Pushing the tag triggers the `publish` job, which checks that the tag matches the version in `pyproject.toml`, builds the distribution with `uv build`, and publishes it with `uv publish` to the GitLab group PyPI registry.

This process is currently manual. Automating the version bump and tagging through a dedicated CI runner is tracked as future work.

The self-managed SEANERGYS GitLab instance cannot currently use PyPI's GitLab Trusted Publishing integration, which is limited to projects hosted on `gitlab.com`. The GitLab project therefore provides a protected and masked `UV_PUBLISH_TOKEN` CI/CD variable for the PyPI project.

## Development builds

Besides tagged releases, every push to the default branch publishes a development build to the same registry. Its version is the next patch version with the pipeline number as development release, for example `0.1.4.dev57` after release `0.1.3`. Development builds let consumers such as seanertest live at head: a requirement that names a development release, such as `seanerstack>=0.1.3.dev0`, makes installers choose the newest build. A development build sorts before the next release, so a release is always newer than the development builds before it.

## Installing releases

```console
pipx install --include-deps seanerstack
pipx upgrade seanerstack
```

When reproducibility requires an exact Seanerstack release, pin the version:

```console
pipx install --include-deps seanerstack==0.1.0
```
