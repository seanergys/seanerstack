# Seanstack

Seanstack combines two closely related roles for SEANERGYS:

- a curated collection of native Spack package recipes and Spack environments;
- a small command-line tool that synchronizes, bootstraps, validates, and locates that content.

Seanstack does **not** define its own package, environment, compiler, or toolchain format. Spack remains the source of truth for all of those concepts.

## Installation layout

The Python implementation is installed normally, while Spack-facing data is installed under the Python environment prefix:

```text
<prefix>/
├── bin/seanstack
├── lib/python.../site-packages/seanstack/
└── share/seanstack/
    ├── spack-repo-index.yaml
    ├── spack_repo/seanstack/
    │   ├── repo.yaml
    │   └── packages/
    └── environments/
```

The paths can always be discovered at runtime:

```console
seanstack sharepath
seanstack repopath
seanstack envpath --package properdocs
```

For example:

```console
spack repo add "$(seanstack repopath)"
seanstack bootstrap gcc@15
spack env activate "$(seanstack envpath --package properdocs)"
```

## Development

```console
uv sync --all-groups
uv run pytest
uv run seanstack --help
```

Build or serve the documentation:

```console
uv run --group docs properdocs build
uv run --group docs properdocs serve
```
