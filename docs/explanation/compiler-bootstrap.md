# Compiler bootstrap

SEANERGYS dependencies are normally built with a compiler that is itself installed through Spack.

That creates a staged construction problem:

```text
available system/bootstrap compiler
        |
        v
Spack builds gcc@15
        |
        v
gcc@15 becomes the project compiler
        |
        v
Seanstack environments are concretized and installed
```

The compiler recipe comes from the normal Spack repositories; Seanstack does not carry its own GCC or LLVM recipe.

`seanstack bootstrap gcc@15` performs the project-specific transition from the initially available compiler to the Spack-installed production compiler. The compiler is established before package development environments are concretized, so compiler setup is separate from environment definitions.

For normal SEANERGYS work, this is a workstation setup operation rather than a per-environment choice.
