# Architecture

Seanstack combines a curated Spack distribution for SEANERGYS with the small amount of tooling required to prepare and maintain it.

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

## Preparation and maintenance tooling

The `seanstack` command handles project-specific operations that sit around Spack:

```text
sync       upstream Git -> curated package.py
bootstrap  Spack-installed compiler -> usable SEANERGYS compiler setup
validate   curated recipes/environments -> consistency checks
```

Path commands expose the installed native artifacts so they can be passed to Spack:

```text
repopath
envpath --package <package>
```

Seanstack is therefore not a wrapper over Spack. It prepares and maintains the Spack setup that SEANERGYS has chosen; users then invoke Spack directly to concretize, install, develop, and deploy software.
