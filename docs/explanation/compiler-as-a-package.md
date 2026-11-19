# The compiler as a package: what Spack does with it

On 2026-11-18 the project compiler changed from an external to a package that the concretizer reuses. The first real build of that design stopped at a compiler probe that never finished. This page records what was found while making it work: what Spack 1.2.2 does with a compiler that is a package, which ways of requiring it fail and why, and what is still open. [Compiler bootstrap](compiler-bootstrap.md) describes the design that resulted; this page is the evidence behind it.

Everything here was observed with Spack 1.2.2 on Rocky Linux 10, whose system compiler is GCC 14.4.1, with `gcc@15.3.0` as the project compiler. Where the develop branch of Spack was tried, it was commit `7188f9d6e0` of 2026-11-18.

## Why the compiler became a package

An external is hashed by its path. The built compiler was registered as an external, so its hash, and the hash of everything built with it, contained the state directory. A state in another directory matched nothing in the build cache. Spack 1.2.2 has no setting that leaves the path out: `Spec.to_node_dict` writes the prefix and the compiler paths of every external into what is hashed.

A package is hashed by its recipe and its dependencies, and has the same hash wherever it is installed. So the compiler is installed in an environment of its own, and the concretizer may reuse what that environment holds and nothing else.

## What failed, and why

### A requirement on the language has no solution

The first form of the design required the compiler on the language virtuals:

```yaml
packages:
  c:       {require: [gcc@15]}
  cxx:     {require: [gcc@15]}
  fortran: {require: [gcc@15]}
```

Spack applies such a requirement to every node that needs the language, including the dependencies of the compiler itself. Those were built by the system compiler, and their `gcc-runtime@14.4.1` depends on `gcc@14.4.1`. Reusing the built compiler therefore breaks the requirement, and not reusing it leaves no compiler that satisfies it.

Spack 1.2.2 does not say so. `spack spec zlib` ran at full load on one core until the probe's limit of 300 seconds, and without a limit for more than two minutes before it was stopped. Asked for the compiler explicitly, it answers within seconds:

```console
$ spack spec zlib %gcc@15
==> Error: failed to concretize `zlib %gcc@15` for the following reasons:
     1. Cannot satisfy 'gcc@15'
     2. Cannot satisfy 'gcc@15' (version 14.4.1 does not match)
        required because gcc@15 is a requirement for package cxx
          required because gcc-runtime depends on gcc
          required because gcc@15 is a requirement for package c
```

The develop branch of Spack gives the same reasons for plain `zlib`, in about 20 seconds. Moving to it would have changed how the failure shows, and not the failure.

Without the three requirements, `spack spec zlib %gcc@15` concretizes in seven seconds and reuses the built compiler. So the reuse works; the requirement was the problem.

### A preference is not enough

A preference can always be satisfied, so it never forces a choice. These forms were tried in a state that could reuse the built compiler, each with `spack spec zlib`:

| Rule | Compiler of `zlib` |
| --- | --- |
| `prefer: [gcc@15]` on `c`, `cxx` and `fortran` | system gcc 14.4.1 |
| `prefer: ["%c=gcc@15", "%cxx=gcc@15", "%fortran=gcc@15"]` on `all` | system gcc 14.4.1 |
| `prefer: ["%gcc@15"]` on `all` | gcc 15.3.0, but `zlib` gets another hash |
| `prefer: ["@15"]` on `gcc` | gcc 15.3.0 |
| No rule, and the system compiler no longer registered | system gcc 14.4.1, reused from the compiler's tree |
| `conflict` with `%c=gcc@:14` and `%c=gcc@16:` on `all` | system gcc 14.4.1 |

Building `zlib` with gcc 15 needs one new package more, `gcc-runtime@15.3.0`, than building it with the system compiler, whose runtime is installed already. That is the likely reason the preferences lose: Spack ranks building fewer packages above a preference. Without any rule, 18 of the 20 new packages of `rust` would be compiled by the system compiler.

Even where a preference wins for one package, it is not a rule, and a package that falls back to the system compiler does so silently.

### The condition `%cxx` also holds for packages without C++

The next form was a requirement on every package with a condition, which Spack does not apply to compilers and their runtime libraries:

```yaml
packages:
  all:
    require:
    - spec: "%cxx=gcc@15"
      when: "%cxx"
```

With it, `zlib` and `capnproto` concretized, and `rust` did not:

```console
$ spack spec rust
==> Error: failed to concretize `rust` for the following reasons:
     1. Only external, or concrete, compilers are allowed for the c language
```

Each of the 20 new packages of `rust` was then concretized alone. Only `libgit2` failed. More packages narrowed it down:

| Package | Languages | Built with | Result |
| --- | --- | --- | --- |
| `libgit2`, `json-c` | C | CMake | fails |
| `libssh2 build_system=cmake` | C | CMake | fails: "libssh2 cannot have a dependency on cxx" |
| `libssh2`, `libmd` | C | Autotools | concretizes |
| `expat build_system=cmake`, `re2c build_system=cmake` | C and C++ | CMake | concretizes |
| `cmake` | C and C++ | itself | concretizes |

The rule for C++ alone is enough to break `libgit2`, and the rule for C alone is not. So the condition `%cxx` holds for a package that has no C++ itself but depends directly on one that has: every C library built with CMake, because CMake is written in C++. The requirement then gives that package a C++ compiler, which its recipe does not allow.

This also happens with plain Spack, the system compiler alone, and no reused compiler, on 1.2.2 and on develop. There `spack spec --fresh zlib` fails with "gmake cannot have a dependency on cxx": the condition also holds for `gmake`, which `zlib`, a package with C++, depends on. A reproduction with a workflow that runs it for both versions is kept separately; the cause in the solver was not traced, and no upstream report was found.

### A toolchain is applied to the compiler's own tree

Spack's toolchains express the same rule with conditions on the dependency:

```yaml
toolchains:
  seanergys:
  - {spec: "%c=gcc@15", when: "%c"}
  - {spec: "%cxx=gcc@15", when: "%cxx"}
  - {spec: "%fortran=gcc@15", when: "%fortran"}
packages:
  all:
    require: ["%seanergys"]
```

Every spec then fails with "Cannot satisfy 'gcc@15'", as with the requirement on the language.

## The rule that works

```yaml
packages:
  all:
    require:
    - any_of: ["%cxx=gcc@15", "%cxx=gcc@15"]
      when: "%cxx=gcc"
```

and the same for `c` and `fortran`. It reads: a package that takes C++ from a gcc takes it from gcc@15. [How the compiler is required](compiler-bootstrap.md#how-the-compiler-is-required) explains each part of its form.

With a compiler environment that holds `gcc@15.3.0` built by gcc 14.4.1, these concretize in seconds, with every new package compiled by gcc 15.3.0: `zlib`, `capnproto`, `libgit2`, `json-c`, `rust`, `python`, `openblas` and `hdf5+fortran~mpi`. The compiler environment concretizes again to the same compiler with the rule in place. A complete `seanerstack toolchain bootstrap` then built `rust` and `capnproto` in a padded state directory in 28 minutes.

The rule is hard. A spec that asks for another gcc, such as `zlib %gcc@14`, has no solution, and Spack 1.2.2 takes minutes to say so.

## What reuse brings with it

At first the concretizer could reuse everything in the compiler environment, not only the compiler. A new package that needs a library of the compiler's own tree links against that installation, which the system compiler built. For `rust` these were:

| Library of the compiler's tree | Used by |
| --- | --- |
| `zlib-ng` | `cmake`, `curl`, `libssh2`, `openssl`, `python`, `rust`, `rust-bootstrap`, `sqlite` |
| `ncurses` | `cmake`, `python` |
| `readline` | `python`, `sqlite` |
| `xz` | `libssh2`, `python` |
| `bzip2`, `gdbm`, `gettext`, `zstd` | `python` |
| `gmake` | `cmake` |

The hashes are still the same on every machine of a platform, because the compiler's tree is. "Compiled by gcc 15" holds for every new package, and not for these libraries.

Spack can be told to reuse the compiler alone, and Seanerstack now does:

```yaml
concretizer:
  reuse:
    from:
    - type: environment
      path: /opt/seanergys/state/spack/environments/compiler
      include: ["gcc@15"]
```

`rust` then has 37 new packages in place of 21, all compiled by gcc 15.3.0, and builds its own `ncurses`, `readline`, `xz`, `bzip2`, `gettext` and `gmake`. Only `zlib-ng` and `zstd` are still the ones of the compiler's tree, which gcc itself links against. `seanergys-meta` concretizes to 115 new packages, all compiled by gcc 15.3.0. Every hash of the stack changed with this.

It has one consequence for the compiler itself. Concretized again in a state that has the rule and may reuse the earlier compiler, the compiler environment gave another compiler, `/inbwxol`: its dependencies were no longer reusable, so they became new packages that the rule compiles with the earlier compiler. `bootstrap` therefore takes the rule and the reuse out of the configuration before it concretizes the compiler, and writes them back afterwards. The compiler is then `/awyc5sy` again, whether it is concretized or installed from the lockfile.

## The system compiler still decides the compiler's hash

The compiler is built by the system compiler, which is an external, and an external is hashed with the languages it offers. A machine without `gfortran` registers the system GCC with C and C++ only, concretizes the project compiler to another hash, and finds nothing in the build cache. Spack then builds the compiler from source without saying why.

`seanerstack buildcache explain gcc@15` shows the difference against the cached compiler of the same operating system:

```text
gcc -> binutils -> diffutils -> gcc  local /i7yr4sl  cached /7jn7qej
    external.extra_attributes.compilers.fortran:
        local:  None
        cached: '/usr/bin/gfortran'
    parameters.languages:
        local:  ['c', 'c++']
        cached: ['c', 'c++', 'fortran']
```

The same holds for a system compiler of another version. A machine that installs the compiler from a lockfile of its platform does not concretize it at all, and does not depend on its system compiler. In a test with Spack 1.2.2, a state whose system GCC lacked Fortran concretized the compiler to `/cmawlu4` by itself, and installed the compiler of the cache, `/awyc5sy`, from the lockfile, with a probe that passed.

Seanerstack therefore ships the lockfile of the compiler environment for Rocky Linux 10 and installs from it: see [Why the compiler is installed from a lockfile](compiler-bootstrap.md#why-the-compiler-is-installed-from-a-lockfile). The test used installations without content, so the last step of a real installation from the cache, in which the recipe of gcc looks at the installed compiler, was not exercised.

The compiler is now built in two stages, and the first stage, not the system compiler, is the external that builds it. Its hash then depends on the path of the first stage, which is in the state directory, and no longer on the version or the languages of the system compiler: see [Why the compiler is built in two stages](compiler-bootstrap.md#why-the-compiler-is-built-in-two-stages). No lockfile is shipped any more until the pipeline has built the two stages.

## Known problems of Spack that were not met here

Two problems of Spack 1.2.2 concern a compiler built by a newer one, such as gcc 15.3 built by a system gcc 16:

- [spack/spack#51420](https://github.com/spack/spack/issues/51420): a gcc built by Spack with a newer gcc cannot be used as a compiler; concretization hangs.
- [spack/spack#52440](https://github.com/spack/spack/issues/52440): concretization hangs when a spec asks for a gcc built in another group, and a preference for it is ignored.

Both were fixed on the develop branch on 2026-11-11, by [#53338](https://github.com/spack/spack/pull/53338) and [#53339](https://github.com/spack/spack/pull/53339), after Spack 1.2.2 of 2026-07-20. No release contains the fixes yet.

Rocky Linux 10 is not affected, because its system compiler is older than gcc 15. Arch Linux, Fedora 44 and 45 and Debian forky have a system gcc 16.

On Fedora 44 and 45 the reuse of a compiler that the system gcc 16 built did not finish concretizing, with Spack 1.2.2 and with the develop commit `7188f9d6e0`: `zlib` and `rust` ran out of 300 seconds. The likely cause is a rule in Spack's `gcc` recipe, `runtime_constraints`: whatever a `gcc@X.Y` compiles may depend only on what `gcc@:X.Y` built, and the compiler, a dependency of everything it compiles, records gcc 16. The rule was not switched off to prove it. Seanerstack now builds the compiler in two stages, so that it records only a first gcc 15: see [Why the compiler is built in two stages](compiler-bootstrap.md#why-the-compiler-is-built-in-two-stages). On 2026-11-18 the two stages were not yet run on Fedora.

## What changed in Seanerstack

- The compiler is required with the rule above, written into `packages.yaml` of the state. Setting the target no longer removes the other requirements on all packages, so `seanerstack init` run again keeps the rule.
- A probe that runs out of time reports what Spack printed until then, and how to tell a slow solve from a requirement without a solution.
- `seanerstack buildcache prepare` takes `--probe-timeout`, as `init` and `toolchain bootstrap` do.
- `seanerstack buildcache prepare` pushes the compiler and updates the index of the cache as soon as the compiler is built, before the probe. A failure afterwards no longer costs the build of the compiler again.
- `toolchain bootstrap` and `buildcache prepare` install the compiler from the lockfile that Seanerstack ships for the platform, where there is one.
- The compiler is built in two stages, the first in a Spack instance of its own, and `toolchain bootstrap` takes the compiler of a lockfile from the build caches only.

## How to look into a concretization that does not finish

These steps found the causes above, and apply to the next one.

1. **Run the solve without a limit, and look at the process.** A `spack spec` that uses a whole core is searching; one that uses none is waiting, for a lock or the network. Minutes of searching for a small package mean that the solver is proving that there is no solution.
2. **Ask for the compiler explicitly.** `spack spec zlib %gcc@15` fails within seconds with reasons where plain `zlib` searches without end.
3. **Change the configuration in a copy, and call the real Spack.** The `spack` of an activated state is a wrapper that always sets the state's own configuration. Copy the configuration directory, change the copy, and run `"$SEANERSTACK_REAL_SPACK" -C COPY` with `SPACK_USER_CONFIG_PATH=COPY`. Check with `spack config get packages` that the change is in force before reading a result.
4. **Take the failing spec apart.** Concretize each new package of it alone; the ones that fail by themselves are few.
5. **Reproduce without building.** `spack install --fake` installs a concretized environment in seconds, the compiler included. A state made that way concretizes like the real one, and gave the same hashes as the real build.
6. **Test a rule against the real solver before writing it down.** Three rules that read as correct failed here: the requirement on the language, the toolchain, and the condition `%cxx`.

## Open

- The reuse of the compiler on the platforms with a system gcc 16.
- Lockfiles of the compiler environment for the platforms other than Rocky Linux 10.
- A report to Spack about the condition `%cxx`.
- A complete build of the toolchain and of `seanergys-meta` with the compiler reused alone; so far it was concretized, not built.
