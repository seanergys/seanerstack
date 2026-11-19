# Compiler bootstrap

SEANERGYS dependencies are normally built with a compiler that is itself installed through Spack.

That creates a construction in stages: the compiler is built twice, and then builds the stack.

<figure style="width: 100%">
<svg style="width: 100%; max-width: 52rem" viewBox="0 0 840 250" role="img" aria-labelledby="compiler-stages-title compiler-stages-desc" xmlns="http://www.w3.org/2000/svg">
  <title id="compiler-stages-title">The stages of the compiler bootstrap</title>
  <desc id="compiler-stages-desc">The system compiler of the platform builds a first gcc 15 in a Spack instance of its own. That first stage builds gcc 15 again, with its libraries, in the compiler environment. The second gcc 15 compiles every package of the stack, and the stack may link against libraries of the compiler environment.</desc>
  <defs>
    <marker id="compiler-stages-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--md-default-fg-color--light)"/>
    </marker>
  </defs>
  <g font-family="var(--md-text-font-family, sans-serif)" fill="var(--md-default-fg-color)">
    <g stroke="var(--md-default-fg-color--lighter)" stroke-width="1.5" fill="var(--md-code-bg-color)">
      <rect x="10" y="40" width="170" height="120" rx="8"/>
      <rect x="226" y="40" width="170" height="120" rx="8"/>
      <rect x="442" y="40" width="170" height="120" rx="8" stroke="var(--md-accent-fg-color)" stroke-width="2"/>
      <rect x="658" y="40" width="170" height="120" rx="8"/>
    </g>
    <g font-size="12" fill="var(--md-default-fg-color--light)" text-anchor="middle">
      <text x="95" y="28">of the platform</text>
      <text x="311" y="28">first stage</text>
      <text x="527" y="28">second stage</text>
      <text x="743" y="28">the stack</text>
    </g>
    <g font-size="16" font-weight="600" text-anchor="middle">
      <text x="95" y="78">System compiler</text>
      <text x="311" y="78">First gcc 15</text>
      <text x="527" y="78">gcc 15</text>
      <text x="743" y="78">Every package</text>
    </g>
    <g font-size="12" text-anchor="middle">
      <text x="95" y="104">gcc 14 of Rocky Linux 10,</text>
      <text x="95" y="122">gcc 16 of Fedora</text>
      <text x="311" y="104">C and C++, in a Spack</text>
      <text x="311" y="122">instance of its own</text>
      <text x="527" y="104">with its own libraries,</text>
      <text x="527" y="122">installed as packages</text>
      <text x="743" y="104">rust, capnproto and</text>
      <text x="743" y="122">the SEANERGYS packages</text>
    </g>
    <g stroke="var(--md-default-fg-color--light)" stroke-width="1.5" fill="none">
      <line x1="184" y1="100" x2="222" y2="100" marker-end="url(#compiler-stages-arrow)"/>
      <line x1="400" y1="100" x2="438" y2="100" marker-end="url(#compiler-stages-arrow)"/>
      <line x1="616" y1="100" x2="654" y2="100" marker-end="url(#compiler-stages-arrow)"/>
      <path d="M 527 164 C 527 215, 743 215, 743 166" stroke-dasharray="5 4" marker-end="url(#compiler-stages-arrow)"/>
    </g>
    <g font-size="11" fill="var(--md-default-fg-color--light)" text-anchor="middle">
      <text x="203" y="92">builds</text>
      <text x="419" y="92">builds</text>
      <text x="635" y="92">compiles</text>
      <text x="635" y="222">zlib-ng and zstd, which gcc links against, are shared</text>
    </g>
  </g>
</svg>
<figcaption>The system compiler builds a first gcc 15, which builds gcc 15 again. Every package of the stack is compiled by that second gcc 15, and identified by its hash.</figcaption>
</figure>

The compiler recipe comes from the normal Spack repositories; Seanerstack does not carry its own GCC or LLVM recipe.

`seanerstack toolchain bootstrap` performs the project-specific transition from the initially available compiler to the Spack-installed production compiler, the compiler of `[toolchain]` in `config.toml`. It runs after `seanerstack init` has set up the state and checked access, so the compiler comes from the project build cache where the cache holds it. The compiler is established before package development environments are concretized, so compiler setup is separate from environment definitions.

For normal SEANERGYS work, this is a workstation setup operation rather than a per-environment choice.

## Why the compiler is reused as an installed package

Spack 1.x has no separate notion of a compiler: `c`, `cxx` and `fortran` are virtual packages, and `gcc` is one provider among others. Directing the stack at a compiler therefore means requiring a provider for those virtuals, for every package that uses them:

```yaml
packages:
  all:
    require:
    - any_of: ["%c=gcc@15", "%c=gcc@15"]
      when: "%c=gcc"
    - any_of: ["%cxx=gcc@15", "%cxx=gcc@15"]
      when: "%cxx=gcc"
    - any_of: ["%fortran=gcc@15", "%fortran=gcc@15"]
      when: "%fortran=gcc"
```

[How the compiler is required](#how-the-compiler-is-required) explains why the rule has this form.

Spack takes a compiler only when it is an external or a concrete spec that the concretizer may reuse. A Seanerstack state concretizes everything fresh, so that the same recipes give the same hashes on every machine, and with reuse switched off an installed gcc@15 is neither: the requirement can then only be met by building gcc@15 with gcc@15, which is circular.

`seanerstack toolchain bootstrap` therefore installs the compiler in a Spack environment of its own, `environments/compiler` in the state, and lets the concretizer reuse the compiler of that environment, and nothing else:

```yaml
concretizer:
  reuse:
    from:
    - type: environment
      path: /opt/seanergys/state/spack/environments/compiler
      include: ["gcc@15"]
```

`include` matters. The environment also holds what the compiler was built with, such as `ncurses`, `readline` and `gmake`, which the system compiler compiled. Spack prefers an installed package to a new one, so without `include` every package of the stack that needs one of them would take the compiler's. With it, the stack builds its own with the project compiler. Only what the compiler itself links against, `zlib-ng` and `zstd`, is shared.

The compiler environment is always concretized as a new state concretizes it. Before `bootstrap` concretizes it again, it takes the compiler rule and the reuse out of the configuration, and writes both back once the compiler is installed. With them in place, the dependencies of the compiler would be new packages compiled by the earlier compiler, and the result a compiler with another hash.

The compiler then enters every build as the installed package it is, by its hash.

### Why not an external

Registering the installed compiler as an external also satisfies the requirement, and Seanerstack did so before. An external is hashed by its path, because Spack knows nothing else about it. The path of the compiler contains the state directory and the hash of the compiler's own build, and every package built with the compiler inherited both. A state in another directory, or a compiler built by another system compiler, therefore matched nothing in the build cache.

A package is hashed by its recipe, version, variants, target and dependencies, and not by where it is installed. Reused as a package, the compiler enters everything it builds by its own hash. Installed from the lockfile of its platform, the compiler has the same hash in every state directory, and so has everything built with it. `bootstrap` removes the external record that an earlier Seanerstack wrote.

The first stage of the compiler is an external after all, and is hashed by its path, but only the compiler depends on it, and the lockfile fixes the hash of the compiler: see [Why the compiler is built in two stages](#why-the-compiler-is-built-in-two-stages).

### How the compiler is required

The rule reads: a package that takes C from a gcc takes it from gcc@15, and the same for C++ and Fortran. Each part of its form answers something that Spack 1.2.2 does with a compiler that is reused as a package. The develop branch of Spack of 2026-11-18 fails the first point in the same way.

- **A requirement on every package, not on the language.** `packages:c:require:gcc@15` also holds for the compiler's own dependencies, such as its `gcc-runtime`, which the system compiler built. Nothing satisfies it, and Spack searches for minutes before it says so, or without end. A requirement under `all` that names a compiler is not applied to compilers and their runtime libraries, so the compiler's own tree is left alone.
- **The condition `%cxx=gcc`, not `%cxx`.** `%cxx` also holds for a package that has no C++ itself but depends directly on one that has. A C library built with CMake is such a package, because CMake is written in C++, and Spack then refuses it with "Only external, or concrete, compilers are allowed". `%cxx=gcc`, "takes C++ from a gcc", holds only for the package itself.
- **`any_of` with the same spec twice.** Spack warns on every command about a single spec with a compiler under `all`, and suggests the requirement on the language, which is the form that has no solution. `any_of` means the same and has no such warning.

The rule is hard: a spec that asks for another gcc, such as `zlib %gcc@14`, has no solution. Spack 1.2.2 takes minutes to say so.

A new package that needs `zlib-ng` or `zstd` links against the installation that the compiler itself uses, which the system compiler built. Every other package of the stack is compiled by the project compiler.

## Why the compiler is built in two stages

Spack's own `gcc` recipe lets whatever a `gcc@X.Y` compiles depend only on what `gcc@:X.Y` built. Spack records which compiler built each package, and with the compiler reused as a package, the compiler is itself a dependency of everything it compiles. Built by the system compiler directly, gcc 15 records the GCC 16 of Fedora 44 and 45, and the runtime library of that GCC 16. Then no package can be compiled with it, and Spack searches for a solution without end instead of saying so. Rocky Linux 10, whose system compiler is GCC 14, is not affected; every platform whose system compiler is newer than the project compiler is.

`seanerstack toolchain bootstrap` therefore builds the compiler twice:

1. A second Spack instance of the state, the bootstrap instance below `<state>/bootstrap`, registers the system compilers, and the system compiler builds a first gcc 15 there: for C and C++ only, without GCC's own three-stage bootstrap and without binutils, which is much quicker than a full build. It only has to compile the second stage.
2. The state's own Spack, which builds the stack, forgets its gcc compilers and registers the first stage as the one gcc it knows, an external. The first stage then builds `gcc@15 %c,cxx=gcc@15` in the compiler environment, with everything that gcc links against. Afterwards the system compilers are registered again, and the compiler rule keeps them from the stack.

An external records nothing about what built it. No record of the compiler environment names the system compiler, and the rule of the recipe holds.

The bootstrap instance has its own configuration and install tree, with the same Spack, recipes and source cache, so nothing that the system compiler built enters the Spack of the stack. It installs the first stage at `<state>/bootstrap/store/gcc-15.3.0`, without a hash in the path. The compiler is hashed with the path of the external that built it, so its hash depends on the state directory, and no longer on the version of the system compiler. A first stage built earlier by another system compiler has another hash at the same path, and is uninstalled first.

## Using a compiler that is already installed

A machine may already have the compiler the stack needs: GCC 16 from the distribution, or a GCC toolset in `/opt/rh`. `seanerstack init` finds it, on `PATH` or below a prefix given with `--find`, and `--external` makes it the project compiler instead of building one:

```console
$ seanerstack toolchain bootstrap --external gcc@16
```

This is the second half of the bootstrap on its own: `spack compiler find PREFIX` registers what the prefix that `init` found the compiler in holds as externals, and the same language requirements are written. Nothing is built.

The compiler spec has to resolve to that installation. Spack does not refuse a spec it has no external for: a spec that matched GCC 15 only would concretize to a GCC built from source, and the requirement would start that build at the next install. Seanerstack therefore asks Spack what the spec resolves to before writing any requirement, and stops unless it is the external in the prefix:

```text
'gcc@16' does not name the compiler in /usr: Spack resolves it to gcc@16.2.0 built from source.
```

After the requirements, the probe checks that its compiler is that external too.

An external compiler changes the hash of everything built with it, so a stack built with the GCC of `/usr` shares no binaries with one built with the Spack-installed gcc@15. `seanerstack buildcache prepare` keeps building its compiler for that reason: the project build cache is for machines bootstrapped the normal way, and an external compiler suits a workstation or a CI job that does not push to it.

## Why the compiler is installed from a lockfile

The compiler is built by its first stage, an external that is hashed by its path, and that path contains the state directory. A machine that concretized the compiler in another state directory would get another hash, find nothing in the build cache, and build both stages for hours.

Seanerstack therefore ships the concretized compiler environment of a platform as a lockfile, `share/seanerstack/toolchain/<operating system>/spack.lock`, made where the cache is filled. `toolchain bootstrap` copies it into the compiler environment and installs exactly its specs from the build caches, with `spack install --cache-only`, without concretizing and without a first stage: a package installed as a binary needs none of its build dependencies, and the first stage is one of them. The machine that fills the cache and every machine that reads it install the same compiler, whatever their state directory and system compiler are. `bootstrap` prints which happened:

```text
concretized: by the lockfile of rocky10, as the project build cache holds it
```

When the build caches do not hold the compiler of the lockfile, `toolchain bootstrap` stops and says so, rather than build it for hours; `--concretize` builds it on the machine, in two stages. `buildcache prepare`, which fills the cache, builds it from the lockfile with a first stage of its own. That works only in the state directory that made the lockfile, because the lockfile names the first stage by its path, and `prepare` refuses a lockfile of another one.

No lockfile is shipped yet; the first comes from the pipeline that builds the compiler in two stages. Without one, with `--source-compiler`, or with a `--compiler` other than the one of the lockfile, the compiler is concretized on the machine, and `bootstrap` says so. `--concretize` asks for that on purpose.

The lockfile changes only through a commit. A newer system compiler in the image of a platform changes neither the compiler nor the stack. After a change of the pinned Spack, the recipes or the compiler of `[toolchain]`, the lockfile is made again: see [Renew the lockfile of the compiler](../how-to/use-the-build-cache.md#renew-the-lockfile-of-the-compiler).

## Why the compiler is built even when the system has one

The bootstrap instance registers the system compilers before it builds the first stage, because that build needs a C compiler. An external that satisfies the requested spec would then be taken instead of a build: on Ubuntu 26.04, whose system GCC is 15.2.0, `spack install gcc@15` installs nothing. Seanerstack therefore asks for `gcc@15 languages:=c,c++ ~bootstrap ~binutils %c`. An external is a leaf without dependencies, so asking for a C compiler as a dependency rules it out, while the system compiler can still be that C compiler. The second stage, `gcc@15 %c,cxx=gcc@15`, rules out the first stage in the same way. The compiler is built whatever version the system has, the same version included.

After the second stage, the system compilers come back, and every registered compiler that the spec matches, such as a system gcc 15.2.0 for `gcc@15`, is removed, so that only the installed compiler satisfies the language requirements. Otherwise a system compiler of a matching version could build packages instead. Other compilers, such as a system gcc 16 or clang, stay registered.

## Choosing the compilers

`seanerstack init` registers every compiler it finds, on `PATH` and below the prefixes given with `--find`, and prints them. `seanerstack toolchain bootstrap` chooses among them by name, never by path:

- `--source-compiler gcc@14` builds the first stage of the toolchain compiler with the gcc 14 that `init` found, as `gcc@15 languages:=c,c++ ~bootstrap ~binutils %c,cxx=gcc@14.2.1`; by default Spack chooses. Both Spack instances know the compilers that `init` found, also those below `--find`.
- `--external gcc@16` uses the gcc 16 that `init` found as the toolchain compiler instead of building one.

A name that matches none of them, or more than one, is refused with the list of what `init` found. Packages work the same way: `init` detects them without registering them, because a registered external would replace every build of the package, and `--external rust` registers the one it found and stops Spack from building rust. Anything external makes the hashes of what depends on it local to the machine.
