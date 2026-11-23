# Explanation

These pages describe the design of Seanerstack and the reasons behind it. For a procedure, see the [tutorial](../tutorials/index.md) and the [how-to guides](../how-to/index.md).

## Design

| Page | Question it answers |
| --- | --- |
| [Architecture](architecture.md) | What Seanerstack ships, what it keeps in the state directory, and what it leaves to Spack. |
| [Isolation](isolation.md) | How the state stays apart from other Spack configuration on the machine. |
| [Compiler bootstrap](compiler-bootstrap.md) | How the project compiler is installed and becomes the compiler of every build. |
| [Packages and environments](packages-and-environments.md) | Which recipes and environments Seanerstack ships, and where their information lives. |
| [Synchronization](synchronization.md) | How recipe versions follow the upstream repositories. |

The evidence behind these pages is in the [blog](../blog/index.md), by date: for example [What Spack 1.2.2 does with a compiler that is a package](../blog/posts/2026-11-18-compiler-as-a-package.md), the record behind the compiler bootstrap.

## Project

| Page | Question it answers |
| --- | --- |
| [CI pipelines](pipelines.md) | Which job runs in which pipeline, and what each one checks. |
| [Releases](releases.md) | How versions are numbered and published. |
