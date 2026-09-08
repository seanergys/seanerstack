# Architecture

Seanstack combines curated native Spack content for SEANERGYS with the small amount of tooling required to prepare, isolate, and maintain it.

## Curated Spack content

Seanstack ships native Spack content under `share/seanstack`:

```text
share/seanstack/
├── spack_repo/seanstack/
│   ├── repo.yaml
│   └── packages/
└── environments/
```

The package recipes define the packages curated by SEANERGYS. The environments define project contexts used for development and, as deployment environments are added, deployment.

These remain ordinary Spack artifacts. Seanstack determines which artifacts SEANERGYS ships; Spack determines their package and environment semantics.

## Private Spack state

Seanstack keeps the mutable Spack setup separate from the installed curated content. The user chooses a state directory, and Seanstack creates the private Spack configuration, store, stages, caches, and managed environments below it.

```text
<state-dir>/spack/
├── bin/spack
├── config/
├── store/
├── stage/
├── cache/
├── source-cache/
└── environments/
```

This boundary prevents a user's existing `~/.spack` configuration, mirrors, externals, compiler configuration, stores, or caches from silently changing the SEANERGYS setup.

## Preparation and maintenance tooling

The `seanstack` command handles project-specific operations around native Spack:

```text
package update        upstream Git -> curated package.py
toolchain bootstrap   Spack-installed compiler -> isolated compiler policy
validate              curated recipes/environments -> consistency checks
buildcache            configured resources -> isolated Spack mirrors
activate/deactivate   shell -> isolated native Spack session
```

Path commands expose the installed native artifacts:

```text
paths share
paths repo
paths env --package <package>
```

Seanstack is therefore not a replacement command language for Spack. Activation establishes the configuration and state boundary; users then invoke ordinary `spack` commands to concretize, install, develop, and deploy software.
