# Seanerstack

Seanerstack defines and maintains the isolated Spack setup used by SEANERGYS.

It ships the project's curated Spack package recipes and environments, prepares Spack to use the project compiler, and provides maintenance checks for that curated content. It also establishes a private configuration and state boundary so an existing user or system Spack setup cannot silently affect SEANERGYS builds.

The boundary is intentional:

```text
Seanerstack
    curates content and establishes isolated Spack state
        |
        v
Spack
    concretizes, installs, develops, and deploys software
```

Seanerstack does not introduce another package manager, environment format, compiler model, or replacement syntax for normal Spack commands.

## What Seanerstack provides

Seanerstack provides:

- the Spack package recipes curated by SEANERGYS;
- the Spack environments curated for development and, as they are added, deployment;
- `init` for bootstrapping the compiler, configuring build-cache/OCI registry access, and validating the result, in one step;
- `toolchain bootstrap` for making a Spack-installed compiler the compiler used for SEANERGYS builds;
- `package update` for keeping curated recipes aligned with their upstream Git repositories;
- `validate` for checking the curated stack;
- `buildcache` for configuring binary mirrors as named resources;
- `activate` and `deactivate` for using native Spack with isolated configuration and state;
- path commands that expose the installed recipes and environments.

A normal development session looks like:

```console
export SEANERSTACK_STATE_DIR=/path/to/seanerstack-state
eval "$(seanerstack activate)"
spack env activate "$(seanerstack paths env --package <package>)"
spack develop --path /path/to/checkout <package>@develop
spack concretize -f
spack install
```

## How these docs are organized

- **Tutorials** start from a clean system and establish the complete supported SEANERGYS setup step by step.
- **How-to guides** cover distinct project tasks with one canonical procedure each.
- **Explanation** describes why the project is structured this way, including the isolation model.
- **Reference** is generated from the CLI, package recipes, and environments.
