# Look into a concretization that does not finish

A `spack spec` or `spack install` that runs for minutes on a small package is usually not slow: the solver is proving that there is no solution, and Spack 1.2.2 takes minutes to say so, or never does. These steps find the cause. They found the ones recorded in [What Spack 1.2.2 does with a compiler that is a package](../blog/posts/2026-11-18-compiler-as-a-package.md).

## 1. Run the solve without a limit, and look at the process

The probe of `init` and `toolchain bootstrap` gives up after 300 seconds; `--probe-timeout 0` waits. In another shell, look at the process with `top`. A `spack spec` that uses a whole core is searching; one that uses none is waiting, for a lock or the network.

## 2. Ask for the compiler explicitly

```console
spack spec zlib %gcc@15
```

A spec that names the compiler fails within seconds, with reasons, where the plain spec searches without end.

## 3. Change the configuration in a copy, and call the real Spack

The `spack` of a state is a wrapper that always sets the state's own configuration. Copy the configuration directory, change the copy, and run the pinned Spack on it:

```console
cp -r /opt/seanergys/state/spack/config /tmp/config
SPACK_USER_CONFIG_PATH=/tmp/config "$SEANERSTACK_REAL_SPACK" -C /tmp/config spec zlib
```

Check with `spack config get packages` that the change is in force before reading a result.

## 4. Take the failing spec apart

Concretize each new package of the spec alone, with `spack spec --fresh PACKAGE` for the packages that `spack spec` lists as new. The ones that fail by themselves are few, and name the rule that breaks them.

## 5. Reproduce without building

`spack install --fake` installs a concretized environment in seconds, the compiler included. A state made that way concretizes like the real one, and gave the same hashes as the real build.

## 6. Test a rule against the real solver before writing it down

Three rules that read as correct failed in the case above: the requirement on the language, the toolchain, and the condition `%cxx`. The solver, not the documentation of a rule, decides what it means.
