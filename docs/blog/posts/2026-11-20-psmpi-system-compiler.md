---
date: 2026-11-20
categories:
  - Spack
---

# psmpi was built by the system compiler

On 2026-11-20 `build:rocky10` stopped in the `configure` of `psmpi`: "checking for pmix.h... no", "--with-pmix is given but not found". `pmix` was installed and a dependency of `psmpi`, so the headers were there. The compiler that looked for them was not the compiler of the stack. This post records what was found, and what followed: the languages that three recipes now declare, and the compiler guard of the state.

<!-- more -->

## What happened

Spack gives a package a compiler only when the package depends on a language, with `depends_on("c")`, `depends_on("cxx")` or `depends_on("fortran")`. Then its compiler wrapper comes first on the `PATH` of the build, under every compiler name, calls the compiler of the stack, and passes the include directories of the dependencies. A package that declares no language gets no compiler and no wrapper.

`psmpi` declared no language. Its `configure` ran whatever `gcc` was on `PATH`, the system GCC 14 of Rocky Linux 10, outside the compiler rule of the stack and without the include directories of `pmix` and `ucc`; and a bare `--with-pmix` makes `configure` look nowhere else. The concretized spec showed it: there was no `%c` on `psmpi`.

`pscom`, which `psmpi` depends on, was built the same way, without failing. CMake took the `cc` it found, the system GCC 14, and the binary in the project build cache was compiled by it. Nothing had said so.

`seanerbroker` had the same hole in another form. `rustc` links every binary by calling `cc` from `PATH`, and Spack's `rust` sets no linker for the packages that build with it. `seanerbroker` declared no language, so its link step ran the system GCC too.

## What followed

- `psmpi` depends on `c`, `cxx` and `fortran`, as `mpich` does, so the project compiler builds it, and its recipe passes `--with-pmix` and `--with-ucc` with the prefixes of the dependencies, as `mpich` passes `--with-pmix`.
- `pscom` depends on `c`, and `seanerbroker` on `c`, as 23 of the 33 Cargo packages of Spack's builtin recipes do. The hashes of both changed, and both were built once more.
- A recipe test checks that every recipe that compiles something declares the languages it is compiled from; a Cargo package counts as compiled, since `rustc` links with `cc`.
- The state got a [compiler guard](../../explanation/isolation.md#the-compiler-guard): a directory `spack/compiler-guard` with a script under each compiler name, `cc`, `gcc`, `g++`, `gfortran` and the others, that fails and says which dependency is missing. Every Spack run of the state has it in front of `PATH`. A package with a language finds Spack's wrapper first; one without, that compiles anyway, stops there instead of taking the system compiler.

Checked with the pinned Spack: `spack compiler find` still registers `/usr/bin/gcc`, since compilers are registered and called by their absolute paths and the detection skips the scripts of the guard, which report no version; a package without a language that calls `cc` fails with the message; and one that depends on `c` gets the wrapper, which calls the compiler of the stack.
