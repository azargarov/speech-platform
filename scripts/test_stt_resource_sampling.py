from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from scripts.stt_resource_sampling import ResourceSampler


class ResourceSamplerTests(unittest.TestCase):
    def test_aggregates_sampled_peaks_and_separates_cgroup_high_water_mark(self):
        second_sample = threading.Event()
        samples = iter(
            (
                {
                    "device_used_bytes": 100,
                    "device_free_bytes": 900,
                    "device_total_bytes": 1000,
                    "worker_process_used_bytes": 80,
                },
                {
                    "device_used_bytes": 160,
                    "device_free_bytes": 840,
                    "device_total_bytes": 1000,
                    "worker_process_used_bytes": 120,
                },
            )
        )
        rss = iter((1000, 1500))

        def nvml(_index, _pids):
            result = next(samples)
            if result["device_used_bytes"] == 160:
                second_sample.set()
            return result

        sampler = ResourceSampler(
            0.1,
            0,
            maximum_samples=2,
            sample_process_ids=lambda: {1, 2},
            nvml_sample=nvml,
            rss_sample=lambda: next(rss),
            cgroup_sample=lambda: 4096,
        )
        sampler.start()
        self.assertTrue(second_sample.wait(1))
        report = sampler.stop(timeout_seconds=1.0)
        self.assertEqual(report["sample_count"], 2)
        self.assertEqual(report["sampled_peak_label"], "sampled_peak")
        self.assertEqual(report["sampled_peaks"]["sampled_peak_device_used_bytes"], 160)
        self.assertEqual(
            report["sampled_peaks"]["sampled_peak_process_tree_rss_bytes"], 1500
        )
        self.assertEqual(report["cgroup_memory"]["peak_bytes"], 4096)
        self.assertNotEqual(
            report["sampled_peaks"]["sampled_peak_process_tree_rss_bytes"],
            report["cgroup_memory"]["peak_bytes"],
        )
        self.assertEqual(report["nvml_status"], "available")

    def test_missing_nvml_and_cgroup_data_are_reported_without_failing(self):
        def missing_nvml(_index, _pids):
            raise ImportError("host-specific private path must not be retained")

        def missing_rss():
            raise PermissionError("sensitive details")

        def missing_cgroup():
            raise FileNotFoundError("/private/cgroup/path")

        sampler = ResourceSampler(
            1.0,
            0,
            maximum_samples=2,
            sample_process_ids=lambda: {1},
            nvml_sample=missing_nvml,
            rss_sample=missing_rss,
            cgroup_sample=missing_cgroup,
        )
        sampler.start()
        report = sampler.stop(timeout_seconds=1.0)
        self.assertEqual(report["sample_count"], 1)
        self.assertEqual(report["nvml_status"], "unavailable")
        self.assertEqual(report["process_rss_status"], "unavailable")
        self.assertEqual(report["cgroup_memory"]["status"], "unavailable")
        self.assertEqual(report["missing_data"]["nvml"], "dependency_unavailable")
        self.assertEqual(report["missing_data"]["process_rss"], "permission_denied")
        self.assertEqual(
            report["missing_data"]["cgroup_memory_peak"], "interface_unavailable"
        )
        self.assertNotIn("private", repr(report))

    def test_sample_interval_and_count_are_validated(self):
        for interval, count in ((0.01, 1), (1.0, 0)):
            with (
                self.subTest(interval=interval, count=count),
                self.assertRaises(ValueError),
            ):
                ResourceSampler(interval, 0, maximum_samples=count)

    def test_distinguishes_harness_and_descendant_rss_observations(self):
        sampler = ResourceSampler(
            1.0,
            0,
            maximum_samples=1,
            sample_process_ids=lambda: {1, 2},
            nvml_sample=lambda _index, _pids: {},
            rss_sample=lambda: {
                "harness_process_rss_bytes": 100,
                "descendant_process_tree_rss_bytes": 300,
                "process_tree_rss_bytes": 400,
            },
            cgroup_sample=lambda: 500,
        )
        sampler.start()
        report = sampler.stop(timeout_seconds=1.0)
        self.assertEqual(
            report["sampled_peaks"]["sampled_peak_harness_process_rss_bytes"], 100
        )
        self.assertEqual(
            report["sampled_peaks"]["sampled_peak_descendant_process_tree_rss_bytes"],
            300,
        )

    def test_sampler_uses_a_single_bounded_thread(self):
        sampler = ResourceSampler(
            1.0,
            0,
            maximum_samples=1,
            sample_process_ids=lambda: {1},
            nvml_sample=lambda _index, _pids: {},
            rss_sample=lambda: 100,
            cgroup_sample=lambda: 200,
        )
        sampler.start()
        report = sampler.stop(timeout_seconds=1.0)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["sample_count"], 1)
        self.assertIsNone(sampler._thread)

    def test_blocked_nvml_observation_returns_unconfirmed_without_losing_prior_data(
        self,
    ):
        entered = threading.Event()
        release = threading.Event()
        calls = 0

        def nvml(_index, _pids):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"device_used_bytes": 100}
            entered.set()
            release.wait()
            return {"device_used_bytes": 200}

        sampler = ResourceSampler(
            0.1,
            0,
            maximum_samples=4,
            sample_process_ids=lambda: {1},
            nvml_sample=nvml,
            rss_sample=lambda: {"process_tree_rss_bytes": 500},
            cgroup_sample=lambda: 900,
        )
        sampler.start()
        self.assertTrue(entered.wait(1))
        started = time.monotonic()
        report = sampler.stop(timeout_seconds=0.02)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 0.25)
        self.assertEqual(report["status"], "stop_unconfirmed")
        self.assertIs(sampler._thread.is_alive(), True)
        self.assertEqual(report["sampled_peaks"]["sampled_peak_device_used_bytes"], 100)
        self.assertEqual(report["sample_count"], 1)
        self.assertEqual(report["cgroup_memory"]["status"], "not_sampled")
        release.set()
        completed = sampler.stop(timeout_seconds=1)
        self.assertEqual(completed["status"], "stopped")
        self.assertEqual(
            completed["sampled_peaks"]["sampled_peak_device_used_bytes"], 200
        )

    def test_blocked_rss_observation_is_bounded_and_preserves_nvml_data(self):
        entered = threading.Event()
        release = threading.Event()

        def rss():
            entered.set()
            release.wait()
            return {"process_tree_rss_bytes": 600}

        sampler = ResourceSampler(
            1.0,
            0,
            maximum_samples=2,
            sample_process_ids=lambda: {1},
            nvml_sample=lambda _index, _pids: {"device_used_bytes": 42},
            rss_sample=rss,
            cgroup_sample=lambda: 900,
        )
        sampler.start()
        self.assertTrue(entered.wait(1))
        report = sampler.stop(timeout_seconds=0.02)
        self.assertEqual(report["status"], "stop_unconfirmed")
        self.assertEqual(report["sampled_peaks"]["sampled_peak_device_used_bytes"], 42)
        self.assertEqual(
            report["sampled_peaks"].get("sampled_peak_process_tree_rss_bytes"), None
        )
        release.set()
        self.assertEqual(sampler.stop(timeout_seconds=1)["status"], "stopped")

    def test_sampler_start_failure_is_reported_and_stop_does_not_join_unstarted_thread(
        self,
    ):
        sampler = ResourceSampler(
            1.0,
            0,
            maximum_samples=1,
            nvml_sample=lambda _index, _pids: {},
            rss_sample=lambda: {},
            cgroup_sample=lambda: 0,
        )
        with patch(
            "scripts.stt_resource_sampling.threading.Thread.start",
            side_effect=RuntimeError("secret"),
        ):
            with self.assertRaisesRegex(RuntimeError, "secret"):
                sampler.start()
        self.assertEqual(sampler.stop(timeout_seconds=0.01)["status"], "start_failed")

    def test_blocked_cgroup_read_is_inside_bounded_sampler_thread(self):
        entered = threading.Event()
        release = threading.Event()

        def cgroup():
            entered.set()
            release.wait()
            return 99

        sampler = ResourceSampler(
            1.0,
            0,
            maximum_samples=1,
            nvml_sample=lambda _index, _pids: {},
            rss_sample=lambda: {},
            cgroup_sample=cgroup,
        )
        sampler.start()
        sampler._stop.set()
        self.assertTrue(entered.wait(1))
        report = sampler.stop(timeout_seconds=0.01)
        self.assertEqual(report["status"], "stop_unconfirmed")
        self.assertEqual(report["cgroup_memory"]["status"], "not_sampled")
        release.set()
        self.assertEqual(sampler.stop(timeout_seconds=1)["status"], "stopped")

    def test_partial_metrics_survive_unavailable_sources(self):
        sampler = ResourceSampler(
            1.0,
            0,
            maximum_samples=1,
            nvml_sample=lambda _index, _pids: {"device_used_bytes": 77},
            rss_sample=lambda: (_ for _ in ()).throw(PermissionError("private")),
            cgroup_sample=lambda: (_ for _ in ()).throw(FileNotFoundError("private")),
        )
        sampler.start()
        report = sampler.stop(timeout_seconds=1)
        self.assertEqual(report["status"], "stopped")
        self.assertEqual(report["sampled_peaks"]["sampled_peak_device_used_bytes"], 77)
        self.assertEqual(report["process_rss_status"], "unavailable")
        self.assertEqual(report["cgroup_memory"]["status"], "unavailable")
        self.assertNotIn("private", repr(report))

    def test_resource_report_allowlist_discards_arbitrary_values(self):
        from scripts.stt_cuda_diagnostic import _safe_result

        safe = _safe_result(
            {
                "resource_observations": {
                    "status": "stopped",
                    "sampling_interval_seconds": 1.0,
                    "sample_count": 2,
                    "sampled_peak_label": "forged",
                    "sample_counts_by_metric": {"device_used_bytes": 2},
                    "sampled_peaks": {"sampled_peak_device_used_bytes": 42},
                    "nvml_status": "available",
                    "process_rss_status": "available",
                    "cgroup_memory": {
                        "status": "available",
                        "peak_bytes": 99,
                        "observation_count": 1,
                        "path": "/private/cgroup",
                    },
                    "missing_data": {"nvml": "query_failed"},
                    "arbitrary": "private transcript",
                }
            }
        )["resource_observations"]
        self.assertEqual(safe["sampled_peak_label"], "sampled_peak")
        self.assertEqual(safe["sampled_peaks"]["sampled_peak_device_used_bytes"], 42)
        self.assertNotIn("path", repr(safe))
        self.assertNotIn("private", repr(safe))


if __name__ == "__main__":
    unittest.main()
