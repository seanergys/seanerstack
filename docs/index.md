# Seanstack

Seanstack defines and maintains the Spack setup used by SEANERGYS.

It ships the project's curated Spack package recipes and environments, prepares Spack to use the project compiler, and provides maintenance checks for that curated content. Once the setup is prepared, normal development and deployment operations are performed directly with Spack.

The boundary is intentional:

```text
Seanstack
    prepares and maintains the SEANERGYS Spack setup
        |
        v
Spack
    concretizes, installs, develops, and deploys software
```

Seanstack does not introduce another package manager, environment format, compiler model, or wrapper around normal Spack commands.

## What Seanstack provides

Seanstack provides:

- the Spack package recipes curated by SEANERGYS;
- the Spack environments curated for development and, as they are added, deployment;
- `bootstrap` for making a Spack-installed compiler the compiler used for SEANERGYS builds;
- `sync` for keeping curated recipes aligned with their upstream Git repositories;
- `validate` for checking the curated stack;
- path commands that expose the installed recipes and environments to Spack.

After initial setup, a development session uses Spack directly:

```console
spack env activate "$(seanstack paths env --package <package>)"
spack develop --path /path/to/checkout <package>@develop
spack concretize -f
spack install
```

## How these docs are organized

- **Tutorials** start from a clean system and establish the complete supported SEANERGYS setup step by step.
- **How-to guides** cover distinct project tasks with one canonical procedure each.
- **Explanation** describes why the project is structured this way.
- **Reference** is generated from the CLI, package recipes, and environments.
