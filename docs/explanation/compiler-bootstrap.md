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

## Using a compiler that is already installed

A machine may already have the compiler the stack needs: GCC 16 from the distribution, or a GCC toolset in `/opt/rh`. `--external PREFIX` makes that compiler the project compiler instead of building one:

```console
$ seanerstack toolchain bootstrap gcc@16 --external /usr
```

This is the second half of the bootstrap on its own: `spack compiler find PREFIX` registers what the prefix holds as externals, and the same language requirements are written. Nothing is built.

The compiler spec has to name a compiler in that prefix. Spack does not refuse a spec it has no external for: if `/usr` holds only GCC 15, `gcc@16` concretizes to a GCC 16 built from source, and the requirement would start that build at the next install. Seanerstack therefore asks Spack what the spec resolves to before writing any requirement, and stops unless it is the external in PREFIX:

```text
'gcc@16' does not name the compiler in /usr: Spack resolves it to gcc@16.2.0 built from source.
```

After the requirements, the probe checks that its compiler is that external too.

An external compiler changes the hash of everything built with it, so a stack built with the GCC of `/usr` shares no binaries with one built with the Spack-installed gcc@15. `seanerstack buildcache prepare` keeps building its compiler for that reason: the project build cache is for machines bootstrapped the normal way, and an external compiler suits a workstation or a CI job that does not push to it.
