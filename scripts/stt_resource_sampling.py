"""Bounded, privacy-safe resource observations for STT experiments."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path


def _process_tree_rss_bytes(root_pid: int | None = None) -> dict[str, int]:
    """Return harness, descendant and combined RSS, without process identifiers."""
    root_pid = os.getpid() if root_pid is None else root_pid
    pending = [root_pid]
    visited = set()
    rss_by_pid = {}
    while pending:
        pid = pending.pop()
        if pid in visited:
            continue
        visited.add(pid)
        proc = Path("/proc") / str(pid)
        try:
            children = (proc / "task" / str(pid) / "children").read_text().split()
            pending.extend(int(child) for child in children if child.isdecimal())
            status = (proc / "status").read_text()
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                fields = line.split()
                if len(fields) >= 2 and fields[1].isdecimal():
                    rss_by_pid[pid] = int(fields[1]) * 1024
                break
    if root_pid not in rss_by_pid:
        raise OSError("process RSS is unavailable")
    root_rss = rss_by_pid[root_pid]
    descendants_rss = sum(value for pid, value in rss_by_pid.items() if pid != root_pid)
    return {
        "harness_process_rss_bytes": root_rss,
        "descendant_process_tree_rss_bytes": descendants_rss,
        "process_tree_rss_bytes": root_rss + descendants_rss,
    }


def _nvml_sample(
    device_index: int, process_ids: frozenset[int]
) -> dict[str, int | str | None]:
    import pynvml

    pynvml.nvmlInit()
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
        memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
        process_bytes = 0
        process_data_available = False
        process_missing_code = "not_supported"
        getter = getattr(pynvml, "nvmlDeviceGetComputeRunningProcesses", None)
        if getter is None:
            getter = getattr(pynvml, "nvmlDeviceGetComputeRunningProcesses_v2", None)
        if getter is not None:
            try:
                processes = getter(handle)
                for process in processes:
                    used = getattr(process, "usedGpuMemory", None)
                    if (
                        process.pid in process_ids
                        and type(used) is int
                        and used >= 0
                        and used < (1 << 63)
                    ):
                        process_bytes += used
                        process_data_available = True
                if not process_data_available:
                    process_missing_code = "process_not_visible"
            except Exception:
                process_data_available = False
                process_missing_code = "query_failed"
        sample = {
            "device_used_bytes": int(memory.used),
            "device_free_bytes": int(memory.free),
            "device_total_bytes": int(memory.total),
            "worker_process_used_bytes": process_bytes
            if process_data_available
            else None,
            "worker_process_memory_missing_code": process_missing_code,
        }
        return sample
    finally:
        pynvml.nvmlShutdown()


def _cgroup_peak_bytes() -> int:
    candidates = (
        Path("/sys/fs/cgroup/memory.peak"),
        Path("/sys/fs/cgroup/memory/memory.max_usage_in_bytes"),
    )
    for path in candidates:
        try:
            value = path.read_text().strip()
        except FileNotFoundError:
            continue
        if value.isdecimal():
            return int(value)
        raise ValueError("cgroup memory peak is unavailable")
    raise FileNotFoundError("cgroup memory peak is unavailable")


class ResourceSampler:
    """One bounded sampler thread with O(1) aggregation and no raw samples."""

    def __init__(
        self,
        interval_seconds: float,
        device_index: int,
        *,
        sample_process_ids=None,
        nvml_sample=_nvml_sample,
        rss_sample=_process_tree_rss_bytes,
        cgroup_sample=_cgroup_peak_bytes,
        maximum_samples: int,
    ):
        if type(interval_seconds) not in (int, float) or interval_seconds < 0.1:
            raise ValueError("resource sample interval must be at least 0.1 seconds")
        if type(device_index) is not int or device_index < 0:
            raise ValueError("resource sampling device index is invalid")
        if type(maximum_samples) is not int or maximum_samples < 1:
            raise ValueError("maximum resource sample count must be positive")
        self.interval_seconds = float(interval_seconds)
        self.device_index = device_index
        self.maximum_samples = maximum_samples
        self._sample_process_ids = sample_process_ids or self._current_process_tree
        self._nvml_sample = nvml_sample
        self._rss_sample = rss_sample
        self._cgroup_sample = cgroup_sample
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._stop_lock = threading.Lock()
        self._started = False
        self._start_failed = False
        self._sample_count = 0
        self._field_counts: dict[str, int] = {}
        self._sampled_peaks: dict[str, int] = {}
        self._missing: dict[str, str] = {}
        self._nvml_status = "pending"
        self._rss_status = "pending"
        self._cgroup_memory = {
            "status": "not_sampled",
            "peak_bytes": None,
            "observation_count": 0,
        }

    @staticmethod
    def _current_process_tree():
        ids = {os.getpid()}
        pending = list(ids)
        while pending:
            pid = pending.pop()
            try:
                children = (
                    (Path("/proc") / str(pid) / "task" / str(pid) / "children")
                    .read_text()
                    .split()
                )
            except (FileNotFoundError, PermissionError, OSError):
                continue
            for value in children:
                if value.isdecimal() and int(value) not in ids:
                    ids.add(int(value))
                    pending.append(int(value))
        return frozenset(ids)

    def start(self):
        if self._thread is not None:
            raise RuntimeError("resource sampler already started")
        thread = threading.Thread(
            target=self._run, name="stt-resource-sampler", daemon=True
        )
        self._thread = thread
        try:
            thread.start()
        except BaseException:
            self._thread = None
            self._start_failed = True
            raise
        self._started = True

    def _record_missing(self, key, exc):
        if isinstance(exc, ImportError):
            code = "dependency_unavailable"
        elif isinstance(exc, PermissionError):
            code = "permission_denied"
        elif isinstance(exc, FileNotFoundError):
            code = "interface_unavailable"
        elif isinstance(exc, ValueError):
            code = "invalid_observation"
        else:
            code = "query_failed"
        with self._lock:
            self._missing.setdefault(key, code)

    def _observe(self):
        with self._lock:
            if self._sample_count >= self.maximum_samples:
                return
        try:
            process_ids = frozenset(self._sample_process_ids())
            gpu = self._nvml_sample(self.device_index, process_ids)
            self._nvml_status = "available"
            for key, value in gpu.items():
                if key == "worker_process_memory_missing_code":
                    if value in {
                        "not_supported",
                        "process_not_visible",
                        "query_failed",
                    }:
                        with self._lock:
                            self._missing.setdefault("nvml_process_memory", value)
                    continue
                if key == "worker_process_used_bytes" and value is None:
                    with self._lock:
                        self._missing.setdefault(
                            "nvml_process_memory", "process_not_visible"
                        )
                    continue
                if type(value) is int and value >= 0:
                    field = f"sampled_peak_{key}"
                    with self._lock:
                        self._field_counts[key] = self._field_counts.get(key, 0) + 1
                        self._sampled_peaks[field] = max(
                            value, self._sampled_peaks.get(field, 0)
                        )
        except Exception as exc:
            self._nvml_status = "unavailable"
            self._record_missing("nvml", exc)
        try:
            rss = self._rss_sample()
            if type(rss) is int:
                rss = {"process_tree_rss_bytes": rss}
            if not isinstance(rss, dict) or not rss:
                raise ValueError("RSS observation is invalid")
            self._rss_status = "available"
            with self._lock:
                for name, value in rss.items():
                    if (
                        not isinstance(name, str)
                        or not name.endswith("_rss_bytes")
                        or type(value) is not int
                        or value < 0
                    ):
                        continue
                    self._field_counts[name] = self._field_counts.get(name, 0) + 1
                    key = f"sampled_peak_{name}"
                    self._sampled_peaks[key] = max(
                        value, self._sampled_peaks.get(key, 0)
                    )
        except Exception as exc:
            self._rss_status = "unavailable"
            self._record_missing("process_rss", exc)
        with self._lock:
            self._sample_count += 1

    def _run(self):
        while True:
            with self._lock:
                if self._sample_count >= self.maximum_samples:
                    break
            self._observe()
            if self._stop.wait(self.interval_seconds):
                break
        self._collect_cgroup_peak()

    def _collect_cgroup_peak(self):
        try:
            peak = self._cgroup_sample()
            if type(peak) is not int or peak < 0:
                raise ValueError("cgroup peak is invalid")
            self._cgroup_memory = {
                "status": "available",
                "peak_bytes": peak,
                "observation_count": 1,
            }
        except Exception as exc:
            self._record_missing("cgroup_memory_peak", exc)
            self._cgroup_memory = {
                "status": "unavailable",
                "peak_bytes": None,
                "observation_count": 0,
            }

    def stop(self, timeout_seconds: float):
        timeout = max(0.0, float(timeout_seconds))
        deadline = time.monotonic() + timeout
        if not self._stop_lock.acquire(timeout=timeout):
            return self.report(status_override="stop_unconfirmed")
        try:
            thread = self._thread
            if thread is None:
                return self.report()
            self._stop.set()
            thread.join(max(0.0, deadline - time.monotonic()))
            if thread.is_alive():
                return self.report(status_override="stop_unconfirmed")
            self._thread = None
            return self.report()
        finally:
            self._stop_lock.release()

    def report(self, cgroup=None, status_override=None):
        with self._lock:
            peaks = dict(self._sampled_peaks)
            counts = dict(self._field_counts)
            missing = dict(self._missing)
            sample_count = self._sample_count
        if status_override is not None:
            status = status_override
        elif self._start_failed:
            status = "start_failed"
        elif self._thread is None and not self._started:
            status = "not_started"
        elif self._thread is None:
            status = "stopped"
        else:
            status = "running"
        return {
            "status": status,
            "device_index": self.device_index,
            "sampling_interval_seconds": self.interval_seconds,
            "sample_count": sample_count,
            "sampled_peak_label": "sampled_peak",
            "sample_counts_by_metric": counts,
            "sampled_peaks": peaks,
            "nvml_status": self._nvml_status,
            "process_rss_status": self._rss_status,
            "cgroup_memory": dict(cgroup or self._cgroup_memory),
            "missing_data": missing,
            "limitations": [
                "GPU and RSS maxima are periodic samples, not instrumented peaks.",
                "cgroup memory peak is a cgroup high-water mark, not process RSS.",
                "NVML process attribution is limited to visible worker descendants.",
            ],
        }
