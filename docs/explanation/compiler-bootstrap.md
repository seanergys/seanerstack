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
Seanerstack environments are concretized and installed
```

The compiler recipe comes from the normal Spack repositories; Seanerstack does not carry its own GCC or LLVM recipe.

`seanerstack toolchain bootstrap gcc@15` performs the project-specific transition from the initially available compiler to the Spack-installed production compiler. The compiler is established before package development environments are concretized, so compiler setup is separate from environment definitions.

For normal SEANERGYS work, this is a workstation setup operation rather than a per-environment choice.

## Why the new compiler is registered as an external

Spack 1.x has no separate notion of a compiler: `c`, `cxx` and `fortran` are virtual packages, and `gcc` is one provider among others. Directing the stack at a compiler therefore means requiring a provider for those virtuals:

```yaml
packages:
  c:       {require: [gcc@15]}
  cxx:     {require: [gcc@15]}
  fortran: {require: [gcc@15]}
```

Such a requirement is global: it applies to *every* node that needs the virtual. That includes the nodes inside the new compiler's own build tree, which the system compiler built:

```text
gcc@15.3.0            %c,cxx=gcc@11.5.0     <- built by the system compiler
  |-- binutils        %c,cxx=gcc@11.5.0
  |-- m4, perl, texinfo, zstd, gmp, mpfr ...  all gcc@11
```

Written on its own, the requirement forbids reusing that tree, so the only way to satisfy it is to rebuild gcc@15 with gcc@15, which is circular. The system compiler cannot stand in either, because `11.5.0` does not match `gcc@15`. There is no solution, and Spack does not report one: it keeps searching for hours at full CPU.

`seanerstack toolchain bootstrap` therefore registers the compiler as an external before writing the requirements:

```console
$ spack compiler find "$(spack location -i gcc@15)"
```

An external node is a leaf: it carries no build dependencies, so the requirement has nothing left to contradict. Concretization then takes seconds and the whole stack, the compiler excepted, is built by gcc@15.
