# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import pytest

import seanerstack.jobs as jobs


@pytest.fixture
def machine(monkeypatch, tmp_path: Path):
    """A /proc and a /sys/fs/cgroup to write into, and 16 CPUs of affinity."""
    proc, cgroup = tmp_path / "proc", tmp_path / "cgroup"
    proc.mkdir()
    cgroup.mkdir()
    monkeypatch.setattr(jobs, "PROC", proc)
    monkeypatch.setattr(jobs, "CGROUP", cgroup)
    monkeypatch.setattr(jobs.os, "sched_getaffinity", lambda pid: set(range(16)))

    def write(name: str, text: str) -> None:
        path = (proc if name == "meminfo" else cgroup) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")

    return write


def test_a_machine_without_limits_takes_a_job_per_cpu_its_memory_allows(machine):
    machine("meminfo", f"MemTotal: 999 kB\nMemAvailable: {64 * 1024 * 1024} kB")
    assert (jobs.available_cpus(), jobs.default_jobs()) == (16, 16)
    machine("meminfo", f"MemAvailable: {8 * 1024 * 1024} kB")
    assert jobs.default_jobs() == 4
    machine("meminfo", "MemAvailable: 1024 kB")
    assert jobs.default_jobs() == 1


def test_unknown_memory_leaves_the_cpus(machine):
    assert jobs.available_memory() is None and jobs.default_jobs() == 16


def test_a_cpu_quota_of_cgroup_v2_limits_the_cpus(machine):
    # The affinity of a container limited with --cpus is still every core of the host.
    machine("cpu.max", "250000 100000")
    assert jobs.available_cpus() == 3
    machine("cpu.max", "max 100000")
    assert jobs.available_cpus() == 16


def test_a_cpu_quota_of_cgroup_v1_limits_the_cpus(machine):
    machine("cpu,cpuacct/cpu.cfs_quota_us", "400000")
    machine("cpu,cpuacct/cpu.cfs_period_us", "100000")
    assert jobs.available_cpus() == 4
    machine("cpu,cpuacct/cpu.cfs_quota_us", "-1")
    assert jobs.available_cpus() == 16


def test_the_memory_limit_of_the_cgroup_counts_and_not_the_free_memory_of_the_host(machine):
    machine("meminfo", f"MemAvailable: {190 * 1024 * 1024} kB")
    machine("memory.max", str(10 * jobs.GIB))
    machine("memory.current", str(4 * jobs.GIB))
    assert jobs.available_memory() == 6 * jobs.GIB and jobs.default_jobs() == 3
    machine("memory.max", "max")
    assert jobs.available_memory() == 190 * jobs.GIB


def test_the_memory_limit_of_cgroup_v1_counts_unless_it_is_none(machine):
    machine("memory/memory.limit_in_bytes", str(4 * jobs.GIB))
    machine("memory/memory.usage_in_bytes", str(jobs.GIB))
    assert jobs.available_memory() == 3 * jobs.GIB
    machine("memory/memory.limit_in_bytes", str(9223372036854771712))
    assert jobs.available_memory() is None
