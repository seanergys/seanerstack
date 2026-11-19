# SPDX-License-Identifier: Apache-2.0
"""How many build jobs this machine, or the container a CI job runs in, can take.

Spack builds with 16 jobs unless told otherwise, whatever the machine has. And
inside a container, the count of CPUs and the free memory that /proc shows are
the host's: a container limited by a CPU quota or a memory limit of its cgroup
sees all 48 cores and 190 GB of a node, and builds with more jobs than it can
run, or runs out of memory. So the limits of the cgroup count too.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
import re


GIB = 1024**3

# Rust with four jobs ran a desktop with 4 GiB free out of memory, and the kernel
# then also killed what else was running there. Two jobs finished.
MEMORY_PER_JOB = 2 * GIB

# Where the kernel shows the process its memory and its control group; the
# tests point these elsewhere.
PROC = Path("/proc")
CGROUP = Path("/sys/fs/cgroup")

# What cgroup v1 shows as the limit of a group that has none: the largest page-aligned number.
_NO_LIMIT_V1 = 2**62


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _cpu_quota() -> int | None:
    """The CPUs that the CPU quota of this process's cgroup allows, rounded up, or None without a quota.

    @return: the number of CPUs, at least 1, or None
    """
    # cgroup v2: "max 100000" without a quota, "400000 100000" for four CPUs.
    quota, _, period = (_read(CGROUP / "cpu.max") or "").partition(" ")
    if quota and quota != "max" and period:
        return max(1, math.ceil(int(quota) / int(period)))
    # cgroup v1: a quota of -1 is none.
    for directory in ("cpu", "cpu,cpuacct"):
        quota, period = _read(CGROUP / directory / "cpu.cfs_quota_us"), _read(CGROUP / directory / "cpu.cfs_period_us")
        if quota and period and int(quota) > 0:
            return max(1, math.ceil(int(quota) / int(period)))
    return None


def available_cpus() -> int:
    """The CPUs that this process may run on, within the CPU quota of its cgroup.

    @return: the number of CPUs, at least 1
    """
    try:
        cpus = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cpus = os.cpu_count() or 1
    quota = _cpu_quota()
    return max(1, min(cpus, quota)) if quota is not None else cpus


def _cgroup_memory_left() -> int | None:
    """What the memory limit of this process's cgroup still allows, or None without a limit.

    @return: bytes
    """
    limit, used = _read(CGROUP / "memory.max"), _read(CGROUP / "memory.current")
    if limit is not None and limit != "max" and used is not None:
        return max(0, int(limit) - int(used))
    limit, used = _read(CGROUP / "memory" / "memory.limit_in_bytes"), _read(CGROUP / "memory" / "memory.usage_in_bytes")
    if limit is not None and used is not None and int(limit) < _NO_LIMIT_V1:
        return max(0, int(limit) - int(used))
    return None


def available_memory() -> int | None:
    """The memory that a build can still use: what the kernel reports free, within the limit of the cgroup.

    @return: bytes, or None when neither is known
    """
    match = re.search(r"^MemAvailable:\s+(\d+) kB", _read(PROC / "meminfo") or "", re.MULTILINE)
    known = [value for value in (int(match.group(1)) * 1024 if match else None, _cgroup_memory_left()) if value is not None]
    return min(known) if known else None


def default_jobs() -> int:
    """The build jobs for this machine: one per CPU it may use, and no more than its free memory takes.

    @return: the number of jobs, at least 1
    """
    cpus = available_cpus()
    memory = available_memory()
    return cpus if memory is None else max(1, min(cpus, memory // MEMORY_PER_JOB))
