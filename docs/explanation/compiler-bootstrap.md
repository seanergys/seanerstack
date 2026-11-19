# Compiler bootstrap

SEANERGYS dependencies are normally built with a compiler that is itself installed through Spack.

That creates a construction in three stages:

<figure style="width: 100%">
<svg style="width: 100%; max-width: 48rem" viewBox="0 0 780 250" role="img" aria-labelledby="compiler-stages-title compiler-stages-desc" xmlns="http://www.w3.org/2000/svg">
  <title id="compiler-stages-title">The three stages of the compiler bootstrap</title>
  <desc id="compiler-stages-desc">The system compiler of the platform builds gcc 15 and its libraries in the compiler environment. That gcc 15 compiles every package of the stack, and the stack may link against libraries of the compiler environment.</desc>
  <defs>
    <marker id="compiler-stages-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="var(--md-default-fg-color--light)"/>
    </marker>
  </defs>
  <g font-family="var(--md-text-font-family, sans-serif)" fill="var(--md-default-fg-color)">
    <g stroke="var(--md-default-fg-color--lighter)" stroke-width="1.5" fill="var(--md-code-bg-color)">
      <rect x="10" y="40" width="200" height="120" rx="8"/>
      <rect x="290" y="40" width="200" height="120" rx="8" stroke="var(--md-accent-fg-color)" stroke-width="2"/>
      <rect x="570" y="40" width="200" height="120" rx="8"/>
    </g>
    <g font-size="12" fill="var(--md-default-fg-color--light)" text-anchor="middle">
      <text x="110" y="28">1 · of the platform</text>
      <text x="390" y="28">2 · the compiler environment</text>
      <text x="670" y="28">3 · the stack</text>
    </g>
    <g font-size="16" font-weight="600" text-anchor="middle">
      <text x="110" y="78">System compiler</text>
      <text x="390" y="78">gcc 15</text>
      <text x="670" y="78">Every package</text>
    </g>
    <g font-size="13" text-anchor="middle">
      <text x="110" y="104">gcc 14 of Rocky Linux 10,</text>
      <text x="110" y="122">registered as an external</text>
      <text x="390" y="104">with its own libraries,</text>
      <text x="390" y="122">installed as packages</text>
      <text x="670" y="104">rust, capnproto and</text>
      <text x="670" y="122">the SEANERGYS packages</text>
    </g>
    <g stroke="var(--md-default-fg-color--light)" stroke-width="1.5" fill="none">
      <line x1="214" y1="100" x2="284" y2="100" marker-end="url(#compiler-stages-arrow)"/>
      <line x1="494" y1="100" x2="564" y2="100" marker-end="url(#compiler-stages-arrow)"/>
      <path d="M 390 164 C 390 215, 670 215, 670 166" stroke-dasharray="5 4" marker-end="url(#compiler-stages-arrow)"/>
    </g>
    <g font-size="12" fill="var(--md-default-fg-color--light)" text-anchor="middle">
      <text x="249" y="92">builds</text>
      <text x="529" y="92">compiles</text>
      <text x="530" y="222">libraries such as zlib-ng and ncurses are reused</text>
    </g>
  </g>
</svg>
<figcaption>The system compiler builds gcc 15 once. Every package of the stack is then compiled by that gcc 15, and identified by its hash.</figcaption>
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

`seanerstack toolchain bootstrap` therefore installs the compiler in a Spack environment of its own, `environments/compiler` in the state, and lets the concretizer reuse what that environment holds, and nothing else:

```yaml
concretizer:
  reuse:
    from:
    - type: environment
      path: /opt/seanergys/state/spack/environments/compiler
```

The compiler then enters every build as the installed package it is, by its hash.

### Why not an external

Registering the installed compiler as an external also satisfies the requirement, and Seanerstack did so before. An external is hashed by its path, because Spack knows nothing else about it. The path of the compiler contains the state directory and the hash of the compiler's own build, and every package built with the compiler inherited both. A state in another directory, or a compiler built by another system compiler, therefore matched nothing in the build cache.

A package is hashed by its recipe, version, variants, target and dependencies, and not by where it is installed. Reused as a package, the compiler has the same hash in every state directory, and so has everything built with it. `bootstrap` removes the external record that an earlier Seanerstack wrote.

### How the compiler is required

The rule reads: a package that takes C from a gcc takes it from gcc@15, and the same for C++ and Fortran. Each part of its form answers something that Spack 1.2.2 does with a compiler that is reused as a package. The develop branch of Spack of 2026-11-18 fails the first point in the same way.

- **A requirement on every package, not on the language.** `packages:c:require:gcc@15` also holds for the compiler's own dependencies, such as its `gcc-runtime`, which the system compiler built. Nothing satisfies it, and Spack searches for minutes before it says so, or without end. A requirement under `all` that names a compiler is not applied to compilers and their runtime libraries, so the compiler's own tree is left alone.
- **The condition `%cxx=gcc`, not `%cxx`.** `%cxx` also holds for a package that has no C++ itself but depends directly on one that has. A C library built with CMake is such a package, because CMake is written in C++, and Spack then refuses it with "Only external, or concrete, compilers are allowed". `%cxx=gcc`, "takes C++ from a gcc", holds only for the package itself.
- **`any_of` with the same spec twice.** Spack warns on every command about a single spec with a compiler under `all`, and suggests the requirement on the language, which is the form that has no solution. `any_of` means the same and has no such warning.

The rule is hard: a spec that asks for another gcc, such as `zlib %gcc@14`, has no solution. Spack 1.2.2 takes minutes to say so.

What the compiler environment holds can be reused by every package, not only the compiler. A new package that needs a library of the compiler's own tree, such as `zlib-ng`, `ncurses` or `xz`, links against that installation, which the system compiler built. The hashes are still the same on every machine of a platform, because the compiler's tree is.

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

## Why the compiler is built even when the system has one

The system compiler is registered as an external before the build, because building the new compiler needs a C compiler. An external that satisfies the requested spec would then be taken instead of a build: on Ubuntu 26.04, whose system GCC is 15.2.0, `spack install gcc@15` installs nothing. Seanerstack therefore installs `gcc@15 %c`. An external is a leaf without dependencies, so asking for a C compiler as a dependency rules it out, while the system compiler can still be that C compiler. The compiler is built whatever version the system has, the same version included.

Afterwards, every registered compiler that the spec matches, such as a system gcc 15.2.0 for `gcc@15`, is removed, so that only the installed compiler satisfies the language requirements. Otherwise a system compiler of a matching version could build packages instead. Other compilers, such as a system gcc 16 or clang, stay registered.

## Choosing the compilers

`seanerstack init` registers every compiler it finds, on `PATH` and below the prefixes given with `--find`, and prints them. `seanerstack toolchain bootstrap` chooses among them by name, never by path:

- `--source-compiler gcc@14` builds the toolchain compiler with the gcc 14 that `init` found, as `gcc@15 %c,cxx=gcc@14.2.1`; by default Spack chooses.
- `--external gcc@16` uses the gcc 16 that `init` found as the toolchain compiler instead of building one.

A name that matches none of them, or more than one, is refused with the list of what `init` found. Packages work the same way: `init` detects them without registering them, because a registered external would replace every build of the package, and `--external rust` registers the one it found and stops Spack from building rust. Anything external makes the hashes of what depends on it local to the machine.
