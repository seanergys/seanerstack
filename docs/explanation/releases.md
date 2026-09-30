# Seanerstack releases

A Seanerstack release is a snapshot of the complete SEANERGYS Spack distribution at a particular point in time. The version covers the command-line tooling, curated package recipes, and shipped environments together.

Individual recipes and environments are not given independent Seanerstack release numbers.

## Calendar versions

The publishing pipeline assigns a PEP 440-compatible calendar version:

```text
YYYY.M.D.N
```

For example:

```text
2026.8.26.143
```

The date is taken from the GitLab pipeline creation time and `N` is the project's GitLab pipeline IID. This makes the version unique for the project and stable when a failed publishing job is retried.

The generated release version is used only for the build and is not committed back to `pyproject.toml`.

## Publishing policy

Every push to the default branch runs the normal tests and documentation build. After those stages succeed, GitLab exposes the PyPI publishing job as a manual action. A maintainer explicitly starts that job when the current default-branch state should become a published Seanerstack snapshot. The job then builds the distribution with `uv build` and publishes it with `uv publish`.

The manual release job is optional for the pipeline itself: a normal default-branch pipeline can finish successfully without publishing a release. Publishing therefore always requires an explicit action in the GitLab CI/CD interface.

The self-managed SEANERGYS GitLab instance cannot currently use PyPI's GitLab Trusted Publishing integration, which is limited to projects hosted on `gitlab.com`. The GitLab project therefore provides a protected and masked `UV_PUBLISH_TOKEN` CI/CD variable for the PyPI project.

## Installing releases

Normal systems track the latest successfully published Seanerstack snapshot:

```console
uv tool install seanerstack@latest
```

Existing installations are updated with:

```console
uv tool upgrade seanerstack
```

When reproducibility requires an exact Seanerstack snapshot, pin the published calendar version:

```console
uv tool install seanerstack==2026.8.26.143
```
