"""Offline regressions for the private Stage 2B controller failure paths."""

from __future__ import annotations

import importlib.util
import http.client
import json
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER_PATH = ROOT / "private/m05b/stage2b/run_live.py"
controller = None
if CONTROLLER_PATH.is_file():
    SPEC = importlib.util.spec_from_file_location(
        "stage2b_live_controller", CONTROLLER_PATH
    )
    assert SPEC is not None and SPEC.loader is not None
    controller = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(controller)


class FakeHTTPResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def gpu_row(*, free_mib=8000, apps=None, apps_status="available", used_mib=7000):
    return {
        "total_mib": 15360,
        "used_mib": used_mib,
        "free_mib": free_mib,
        "util_percent": 10,
        "temperature_c": 45,
        "compute_apps": apps or [],
        "compute_apps_status": apps_status,
    }


class SlowGatewayHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def do_POST(self):
        self.server.request_started.set()
        self.server.release_response.wait(3)
        try:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"code":"text_transform_unavailable"}')
        except (BrokenPipeError, ConnectionResetError):
            pass


class SuccessfulGatewayHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        body = b'{"generated":true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@unittest.skipUnless(
    controller is not None,
    "Optional private M05B operator controller is not distributed with the release",
)
class ControllerFailureTests(unittest.TestCase):
    def test_live_controller_is_capped_to_two_sequential_explicit_groq_requests(self):
        self.assertEqual(
            controller.REQUESTS,
            (
                ("groq-qwen", "explicit-groq-qwen.json", "groq-qwen", "groq"),
                ("groq-gpt-oss", "explicit-gpt-oss.json", "groq-gpt-oss", "groq"),
            ),
        )

    def test_completed_request_finalization_copies_enriched_result(self):
        attempt = {"state": "in_progress", "label": "groq-qwen"}
        result = {
            "http_status": 200,
            "latency_seconds": 1.25,
            "public_metadata": {
                "model": "groq-qwen",
                "provider": "groq",
                "generated": True,
                "fallback_occurred": False,
            },
            "response_valid": True,
        }
        controller.finalize_attempt(attempt, result, "success")
        self.assertEqual(attempt["state"], "success")
        self.assertEqual(attempt["http_status"], 200)
        self.assertEqual(attempt["latency_seconds"], 1.25)
        self.assertEqual(attempt["public_metadata"], result["public_metadata"])
        self.assertIn("finalized_at", attempt)

    def test_incomplete_or_interrupted_request_cannot_be_marked_successful(self):
        attempt = {"state": "in_progress"}
        with self.assertRaisesRegex(ValueError, "incomplete request"):
            controller.finalize_attempt(
                attempt, {"http_status": 200, "response_valid": False}, "success"
            )
        controller.finalize_attempt(
            attempt, {"http_status": None, "response_valid": False}, "interrupted"
        )
        self.assertEqual(attempt["state"], "interrupted")
        self.assertIsNone(attempt["http_status"])

    def test_failed_request_finalization_keeps_partial_status_and_latency(self):
        attempt = {"state": "in_progress"}
        controller.finalize_attempt(
            attempt,
            {"http_status": 401, "latency_seconds": 0.04},
            "failed",
        )
        self.assertEqual(attempt["state"], "failed")
        self.assertEqual(attempt["http_status"], 401)
        self.assertEqual(attempt["latency_seconds"], 0.04)

    def test_monitor_failure_aborts_active_request_and_preserves_request_record(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            source = run_dir / "source.json"
            source.write_text('{"text":"offline synthetic input"}')
            original_private = controller.PRIVATE
            controller.PRIVATE = run_dir
            server = ThreadingHTTPServer(("127.0.0.1", 0), SlowGatewayHandler)
            server.request_started = threading.Event()
            server.release_response = threading.Event()
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            monitor = controller.Monitor(run_dir, "http://127.0.0.1:1", {}, {})

            def fail_after_provider_starts(_index):
                if not server.request_started.wait(2):
                    raise AssertionError("fake Gateway did not receive the request")
                raise OSError("offline monitor fault")

            monitor._sample = fail_after_provider_starts
            monitor.start(subprocess.Popen(["sleep", "30"]))
            try:
                result = controller.request_once(
                    run_dir,
                    f"http://127.0.0.1:{server.server_port}",
                    "synthetic-token",
                    "case",
                    "source.json",
                    monitor,
                )
                self.assertTrue(result["aborted_by_monitor"])
                self.assertTrue((run_dir / "case.request.json").exists())
                self.assertEqual(
                    json.loads((run_dir / "case.request.json").read_text())["text"],
                    "offline synthetic input",
                )
            finally:
                monitor.close()
                child_report = {}
                controller.reap_gateway(monitor.process, child_report)
                self.assertTrue(child_report["gateway_reaped"])
                server.release_response.set()
                server.shutdown()
                server.server_close()
                server_thread.join(timeout=2)
                controller.PRIVATE = original_private

    def test_unknown_gpu_name_is_uncertain_then_correlated_by_later_evidence(self):
        monitor = controller.Monitor(Path("unused"), "http://127.0.0.1:1", {}, {})
        monitor.phase = "local_inference"
        snapshots = [
            gpu_row(apps=["44001, [No data], 118"]),
            gpu_row(apps=["44001, /usr/lib/ollama/llama-server, 6418"]),
        ]
        with (
            patch.object(controller, "gpu_sample", side_effect=snapshots),
            patch.object(
                controller,
                "ollama_models",
                side_effect=[[], [{"name": "qwen3.5:9b-q4_K_M"}]],
            ),
            patch.object(controller, "urlopen", return_value=FakeHTTPResponse()),
        ):
            first = monitor._sample(1)
            self.assertFalse(monitor.abort.is_set())
            self.assertTrue(first["gpu_attribution"]["uncertain"])
            self.assertEqual(
                first["gpu_attribution"]["events"][0]["kind"],
                "process_identity_unknown",
            )

            later = monitor._sample(2)
            self.assertFalse(monitor.abort.is_set())
            event = later["gpu_attribution"]["events"][0]
            self.assertEqual(event["kind"], "ollama_process_correlated")
            self.assertEqual(event["previous_names"], ["[No data]"])
            self.assertFalse(event["exclusive_client_attribution"])
            self.assertEqual(monitor.attribution_uncertain_pids, set())

    def test_transient_attribution_uncertainty_does_not_cancel_healthy_request(self):
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            (run_dir / "source.json").write_text('{"text":"offline synthetic"}')
            original_private = controller.PRIVATE
            controller.PRIVATE = run_dir
            monitor = controller.Monitor(run_dir, "http://127.0.0.1:1", {}, {})
            monitor.phase = "local_inference"
            server = ThreadingHTTPServer(("127.0.0.1", 0), SuccessfulGatewayHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with (
                    patch.object(
                        controller,
                        "gpu_sample",
                        return_value=gpu_row(apps=["44004, [No data], 118"]),
                    ),
                    patch.object(controller, "ollama_models", return_value=[]),
                    patch.object(
                        controller, "urlopen", return_value=FakeHTTPResponse()
                    ),
                ):
                    row = monitor._sample(1)
                self.assertTrue(row["gpu_attribution"]["uncertain"])
                self.assertFalse(monitor.abort.is_set())

                result = controller.request_once(
                    run_dir,
                    f"http://127.0.0.1:{server.server_port}",
                    "synthetic-token",
                    "case",
                    "source.json",
                    monitor,
                )
                self.assertEqual(result["http_status"], 200)
                self.assertNotIn("aborted_by_monitor", result)
                self.assertFalse(monitor.abort.is_set())
            finally:
                monitor.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
                controller.PRIVATE = original_private

    def test_additional_process_with_memory_headroom_marks_contamination(self):
        monitor = controller.Monitor(Path("unused"), "http://127.0.0.1:1", {}, {})
        monitor.phase = "local_inference"
        with (
            patch.object(
                controller,
                "gpu_sample",
                return_value=gpu_row(
                    free_mib=7000,
                    apps=["44002, /usr/bin/python, 500"],
                    used_mib=8360,
                ),
            ),
            patch.object(
                controller,
                "ollama_models",
                return_value=[{"name": "qwen3.5:9b-q4_K_M"}],
            ),
            patch.object(controller, "urlopen", return_value=FakeHTTPResponse()),
        ):
            row = monitor._sample(1)
        self.assertFalse(monitor.abort.is_set())
        self.assertTrue(row["gpu_attribution"]["contaminated"])
        self.assertEqual(
            row["gpu_attribution"]["events"][0]["kind"],
            "additional_gpu_process",
        )

    def test_low_free_memory_aborts_even_when_attribution_is_unknown(self):
        monitor = controller.Monitor(Path("unused"), "http://127.0.0.1:1", {}, {})
        monitor.phase = "local_inference"
        with (
            patch.object(
                controller,
                "gpu_sample",
                return_value=gpu_row(
                    free_mib=controller.ABORT_FREE_MIB - 1,
                    apps=["44003, [No data], 118"],
                ),
            ),
            patch.object(controller, "ollama_models", return_value=[]),
            patch.object(controller, "urlopen", return_value=FakeHTTPResponse()),
        ):
            row = monitor._sample(1)
        self.assertTrue(monitor.abort.is_set())
        self.assertIn("free memory", monitor.reason)
        self.assertTrue(row["gpu_attribution"]["uncertain"])

    def test_transient_gpu_measurement_failure_recovers_without_abort(self):
        monitor = controller.Monitor(Path("unused"), "http://127.0.0.1:1", {}, {})
        monitor.phase = "local_inference"
        with (
            patch.object(
                controller,
                "gpu_sample",
                side_effect=[
                    controller.GPUTelemetryError("temporary offline sample"),
                    gpu_row(),
                ],
            ),
            patch.object(controller, "ollama_models", return_value=[]),
            patch.object(controller, "urlopen", return_value=FakeHTTPResponse()),
        ):
            failed = monitor._sample(1)
            recovered = monitor._sample(2)
        self.assertFalse(monitor.abort.is_set())
        self.assertEqual(failed["gpu_resource_measurement"], "temporarily_unavailable")
        self.assertEqual(recovered["gpu_resource_measurement"], "available")
        self.assertEqual(recovered["gpu_measurement_recovered_after_failures"], 1)
        self.assertEqual(monitor.gpu_measurement_gap_samples, 1)

    def test_process_list_failure_is_separate_from_valid_memory_sample(self):
        command = ["nvidia-smi", "--query-compute-apps"]
        with patch.object(
            controller.subprocess,
            "run",
            side_effect=[
                subprocess.CompletedProcess(
                    controller.GPU_QUERY,
                    0,
                    "15360, 7000, 8360, 10, 45\n",
                    "",
                ),
                subprocess.CalledProcessError(
                    1, command, output="", stderr="temporary query failure"
                ),
            ],
        ):
            gpu = controller.gpu_sample()
        monitor = controller.Monitor(Path("unused"), "http://127.0.0.1:1", {}, {})
        monitor.phase = "local_inference"
        with (
            patch.object(controller, "gpu_sample", return_value=gpu),
            patch.object(controller, "ollama_models", return_value=[]),
            patch.object(controller, "urlopen", return_value=FakeHTTPResponse()),
        ):
            row = monitor._sample(1)
        self.assertFalse(monitor.abort.is_set())
        self.assertEqual(row["gpu_resource_measurement"], "available")
        self.assertEqual(gpu["compute_apps_status"], "unavailable")
        self.assertTrue(row["gpu_attribution"]["uncertain"])
        self.assertFalse(row["gpu_attribution"]["contaminated"])

    def test_persistent_gpu_measurement_failure_aborts_at_documented_bound(self):
        monitor = controller.Monitor(Path("unused"), "http://127.0.0.1:1", {}, {})
        monitor.phase = "local_inference"
        with (
            patch.object(
                controller,
                "gpu_sample",
                side_effect=controller.GPUTelemetryError("persistent offline sample"),
            ),
            patch.object(controller, "ollama_models", return_value=[]),
            patch.object(controller, "urlopen", return_value=FakeHTTPResponse()),
        ):
            monitor._sample(1)
            monitor._sample(2)
            third = monitor._sample(3)
        self.assertTrue(monitor.abort.is_set())
        self.assertEqual(third["gpu_measurement_failure_streak"], 3)
        self.assertEqual(monitor.gpu_measurement_gap_samples, 3)

    def test_gpu_driver_error_aborts_immediately(self):
        monitor = controller.Monitor(Path("unused"), "http://127.0.0.1:1", {}, {})
        monitor.phase = "local_inference"
        with (
            patch.object(
                controller,
                "gpu_sample",
                side_effect=controller.GPUTelemetryError(
                    "driver reported Xid", driver_error=True
                ),
            ),
            patch.object(controller, "ollama_models", return_value=[]),
            patch.object(controller, "urlopen", return_value=FakeHTTPResponse()),
        ):
            monitor._sample(1)
        self.assertTrue(monitor.abort.is_set())
        self.assertIn("driver", monitor.reason)

    def test_production_worker_health_failure_aborts_during_inference(self):
        monitor = controller.Monitor(Path("unused"), "http://127.0.0.1:1", {}, {})
        monitor.phase = "local_inference"
        with (
            patch.object(controller, "gpu_sample", return_value=gpu_row()),
            patch.object(controller, "ollama_models", return_value=[]),
            patch.object(controller, "urlopen", return_value=FakeHTTPResponse()),
            patch.object(
                controller,
                "docker_snapshot",
                side_effect=RuntimeError("STT unhealthy"),
            ),
        ):
            row = monitor._sample(5)
        self.assertTrue(monitor.abort.is_set())
        self.assertEqual(row["production_health_error"], "RuntimeError")
        self.assertIn("production service health", monitor.reason)

    def test_keyboard_interrupt_is_recorded_as_stop_not_report_crash(self):
        report = {}
        status = controller.record_stop(report, KeyboardInterrupt())
        self.assertEqual(status, 130)
        self.assertEqual(report["stop_reason_type"], "KeyboardInterrupt")
        self.assertIn("stopped_at", report)

    def test_durable_request_evidence_survives_unexpected_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "request.json"
            controller.durable_write(path, b'{"text":"synthetic"}\n')
            self.assertEqual(path.read_bytes(), b'{"text":"synthetic"}\n')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_gateway_child_is_terminated_waited_and_reaped(self):
        child = subprocess.Popen(["sleep", "30"])
        report = {}
        controller.reap_gateway(child, report)
        self.assertIsNotNone(child.poll())
        self.assertTrue(report["gateway_reaped"])
        self.assertEqual(report["gateway_exit_status"], -15)

    def test_ollama_proxy_forwards_response_and_saves_metadata_only(self):
        provider_body = json.dumps(
            {
                "model": "qwen3.5:9b-q4_K_M",
                "response": "synthetic private completion text",
                "thinking": "synthetic private reasoning",
                "done": True,
                "done_reason": "length",
                "prompt_eval_count": 270,
                "eval_count": 1024,
            }
        ).encode()
        received = {}

        class FakeOllamaHandler(BaseHTTPRequestHandler):
            def log_message(self, _format, *_args):
                return

            def do_POST(self):
                received["path"] = self.path
                received["body"] = self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(provider_body)))
                self.end_headers()
                self.wfile.write(provider_body)

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllamaHandler)
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()

        with tempfile.TemporaryDirectory() as directory:
            capture_path = Path(directory) / "metadata.jsonl"
            proxy, proxy_thread = controller.start_ollama_metadata_proxy(
                f"http://127.0.0.1:{upstream.server_port}/api/generate", capture_path
            )
            try:
                connection = http.client.HTTPConnection(
                    "127.0.0.1", proxy.server_port, timeout=3
                )
                request_body = b'{"prompt":"synthetic request"}'
                connection.request(
                    "POST",
                    "/api/generate",
                    body=request_body,
                    headers={"Content-Type": "application/json"},
                )
                response = connection.getresponse()
                forwarded_body = response.read()
                self.assertEqual(response.status, 200)
                self.assertEqual(forwarded_body, provider_body)
                connection.close()

                self.assertEqual(received["path"], "/api/generate")
                self.assertEqual(received["body"], request_body)
                self.assertEqual(capture_path.stat().st_mode & 0o777, 0o600)
                captured = capture_path.read_text()
                metadata = json.loads(captured)
                self.assertEqual(metadata["done_reason"], "length")
                self.assertEqual(metadata["eval_count"], 1024)
                self.assertEqual(metadata["upstream_http_status"], 200)
                self.assertGreaterEqual(
                    metadata["provider_request_duration_seconds"], 0
                )
                self.assertTrue(metadata["response_present"])
                self.assertEqual(
                    metadata["response_characters"],
                    len("synthetic private completion text"),
                )
                self.assertTrue(metadata["thinking_present"])
                self.assertEqual(
                    metadata["thinking_characters"], len("synthetic private reasoning")
                )
                self.assertNotIn("synthetic private completion text", captured)
                self.assertNotIn("synthetic private reasoning", captured)
                self.assertNotIn("synthetic request", captured)
            finally:
                proxy.shutdown()
                proxy.server_close()
                proxy_thread.join(timeout=2)
                upstream.shutdown()
                upstream.server_close()
                upstream_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
