"""Tests for bounded, private qualification debug evidence."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import compose, diagnostics


class DiagnosticLogTests(unittest.TestCase):
    def test_collects_three_services_in_bounded_window_and_correlates_server_id(self):
        calls = []

        def collect(args, **kwargs):
            calls.append(args)
            service = args[-1]
            line = f'{service}-1 | {{"event":"failure","request_id":"server-id-1","code":"resource_exhausted","text":"private phrase"}}\n'
            other = f'{service}-1 | {{"event":"unrelated","request_id":"other"}}\n'
            return SimpleNamespace(returncode=0, stdout=other + line)

        with patch.object(compose, "run", side_effect=collect):
            result = diagnostics.collect_local_logs(
                "http://127.0.0.1:8080",
                window_seconds=900,
                server_request_ids=["server-id-1"],
            )

        self.assertEqual(len(calls), 3)
        self.assertEqual(result["window_seconds"], 300)
        self.assertTrue(result["window_capped"])
        self.assertTrue(
            all(args[1:4] == ["--since", "300s", "--tail"] for args in calls)
        )
        self.assertEqual(set(result["services"]), set(diagnostics.SERVICES))
        for service in result["services"].values():
            self.assertEqual(service["correlation"], "server_request_id_match")
            self.assertEqual(service["status"], "matched")
            self.assertIn("resource_exhausted", service["log_text"])
            self.assertNotIn("private phrase", service["log_text"])
            self.assertNotIn('"text"', service["log_text"])

    def test_no_server_id_is_reported_as_time_window_only(self):
        with patch.object(
            compose,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="service | startup\n"),
        ):
            result = diagnostics.collect_local_logs(
                "http://localhost:8080", window_seconds=2
            )
        self.assertEqual(result["correlation"], "time_window_only")
        self.assertEqual(result["window_seconds"], 30)
        self.assertEqual(
            result["services"]["tts"]["correlation"],
            "time_window_only_no_server_id",
        )
        self.assertEqual(result["collection"], "matched")
        self.assertEqual(result["services"]["tts"]["status"], "matched")

    def test_since_window_empty_is_successful_no_match_not_collection_failure(self):
        calls = []

        def compose_logs(args, **kwargs):
            calls.append(args)
            # A bounded query excludes historical lines that an unfiltered tail
            # would still return. Keep this deterministic and avoid live Docker.
            if "--since" in args:
                return SimpleNamespace(returncode=0, stdout="")
            return SimpleNamespace(
                returncode=0,
                stdout='gateway-1 | {"time":"2026-10-25T20:00:00Z","msg":"older entry"}\n',
            )

        with patch.object(compose, "run", side_effect=compose_logs):
            bounded = diagnostics.collect_local_logs(
                "http://127.0.0.1:8080", window_seconds=30
            )
            manual_tail = compose.run(
                ["logs", "--tail", "100", "gateway"], capture=True
            )

        self.assertEqual(len(calls), 4)
        self.assertEqual(bounded["collection"], "no_matching_lines")
        self.assertEqual(bounded["services"]["gateway"]["status"], "no_matching_lines")
        self.assertEqual(bounded["services"]["gateway"]["line_count"], 0)
        self.assertIn("--since", calls[0])
        self.assertNotIn("--since", calls[-1])
        self.assertTrue(manual_tail.stdout)

    def test_remote_target_skips_compose_access(self):
        with patch.object(compose, "run") as run:
            result = diagnostics.collect_local_logs(
                "https://gateway.example", window_seconds=30
            )
        run.assert_not_called()
        self.assertEqual(result["collection"], "unavailable")
        self.assertEqual(result["reason"], "target_is_not_loopback")

    def test_compose_failures_are_distinguished_from_empty_successful_logs(self):
        with patch.object(
            compose,
            "run",
            return_value=SimpleNamespace(returncode=1, stdout="", stderr="private"),
        ):
            result = diagnostics.collect_local_logs(
                "http://127.0.0.1:8080", window_seconds=30
            )
        self.assertEqual(result["collection"], "failed")
        self.assertTrue(
            all(
                service["status"] == "failed" for service in result["services"].values()
            )
        )
        self.assertNotIn("private", json.dumps(result))

    def test_log_bytes_are_bounded_and_credentials_redacted(self):
        log = "service | Authorization: Bearer fake-secret-123456\n" + "x" * (
            diagnostics.MAX_LOG_BYTES + 20
        )
        with patch.object(
            compose,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout=log),
        ):
            result = diagnostics.collect_local_logs(
                "http://127.0.0.1:8080",
                window_seconds=10,
                secrets=["fake-secret-123456"],
            )
        entry = result["services"]["gateway"]
        self.assertTrue(entry["truncated"])
        self.assertLessEqual(len(entry["log_text"].encode()), diagnostics.MAX_LOG_BYTES)
        self.assertNotIn("fake-secret-123456", entry["log_text"])

    def test_unstructured_payload_fields_are_redacted(self):
        line = 'tts-1 | request_text="private synthetic phrase" token=some-secret-value'
        redacted = diagnostics._redact_line(line, ())
        self.assertNotIn("private synthetic phrase", redacted)
        self.assertNotIn("some-secret-value", redacted)

    def test_json_secret_fields_are_removed_even_when_names_are_prefixed(self):
        line = 'gateway-1 | {"event":"config","SPEECH_API_TOKEN":"private-token","code":"ready"}'
        redacted = diagnostics._redact_line(line, ())
        self.assertNotIn("private-token", redacted)
        self.assertIn('"code":"ready"', redacted)

    def test_debug_evidence_is_private_and_keeps_failure_code(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private = root / "private"
            private.mkdir(mode=0o700)
            with patch.object(
                diagnostics,
                "collect_local_logs",
                return_value={"collection": "completed", "services": {}},
            ):
                relative = diagnostics.save_debug_evidence(
                    {
                        "operation": "tts",
                        "http": {"status": 503},
                        "elapsed_seconds": 0.286,
                        "error": {
                            "classification": "http_error",
                            "api_code": "resource_exhausted",
                        },
                        "diagnostics": {"failure_stage": "gateway_response"},
                    },
                    target="http://127.0.0.1:8080",
                    window_seconds=1,
                    root=root,
                )
            path = root / relative
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            evidence = json.loads(path.read_text())
            self.assertEqual(
                evidence["result"]["error"]["api_code"], "resource_exhausted"
            )
            self.assertEqual(evidence["result"]["http"]["status"], 503)


if __name__ == "__main__":
    unittest.main()
