# Architecture

Seanerstack combines curated native Spack content for SEANERGYS with the small amount of tooling required to prepare, isolate, and maintain it.

## Curated Spack content

Seanerstack ships native Spack content under `share/seanerstack`:

```text
share/seanerstack/
├── spack_repo/seanerstack/
│   ├── repo.yaml
│   └── packages/
└── environments/
```

The package recipes define the packages curated by SEANERGYS. The environments define project contexts used for development and, as deployment environments are added, deployment.

These remain ordinary Spack artifacts. Seanerstack determines which artifacts SEANERGYS ships; Spack determines their package and environment semantics.

## Private Spack state

Seanerstack keeps the mutable Spack setup separate from the installed curated content. `seanerstack init` sets up one state directory, by default `/opt/seanergys/state`, with the pinned Spack, the private Spack configuration, store, stages, caches, managed environments, and the stored credentials.

```text
<state-dir>/spack/
├── bin/spack
├── config/
├── store/
├── stage/
├── cache/
├── source-cache/
├── environments/
└── package_repos/
```

This boundary prevents a user's existing `~/.spack` configuration, mirrors, externals, compiler configuration, stores, or caches from silently changing the SEANERGYS setup.

## Preparation and maintenance tooling

The `seanerstack` command handles project-specific operations around native Spack:

```text
init                  config.toml, credentials, pinned Spack -> state directory, access checks
package update        upstream Git -> curated package.py
toolchain bootstrap   compiler of [toolchain] -> isolated compiler policy
validate              curated recipes/environments -> consistency checks
buildcache            configured resources -> isolated Spack mirrors
```

Path commands expose the installed native artifacts:

```text
paths share
paths repo
paths env --package <package>
```

Seanerstack is therefore not a replacement command language for Spack. The `spack` wrapper in the state directory establishes the configuration and state boundary; users put it on `PATH` once and then invoke ordinary `spack` commands to concretize, install, develop, and deploy software.
