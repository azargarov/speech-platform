import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import m05b_stage2a


class M05BStage2AResponseTests(unittest.TestCase):
    def setUp(self):
        self.case = {
            "id": "synthetic-case",
            "input_language": "en",
            "invariants": ["CASE-741", "2026-10-22"],
        }

    def test_completed_response_is_saved_before_explicit_invariant_failure(self):
        body = json.dumps(
            {
                "response": "The case is ready.",
                "done": True,
                "done_reason": "stop",
                "load_duration": 1_000_000,
                "total_duration": 2_000_000,
                "prompt_eval_duration": 300_000,
                "eval_duration": 400_000,
                "prompt_eval_count": 452,
                "eval_count": 24,
            }
        ).encode()
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "response.json"
            row = m05b_stage2a.record_response(
                body=body,
                evidence_path=evidence,
                case=self.case,
                context=4096,
                client_seconds=10.2,
            )

            self.assertEqual(evidence.read_bytes(), body)
            self.assertEqual(stat.S_IMODE(evidence.stat().st_mode), 0o600)
        self.assertEqual(row["completion_status"], "completed")
        self.assertEqual(row["quality_status"], "failed")
        self.assertEqual(row["invariant_failure_count"], 2)
        self.assertEqual(row["client_total_s"], 10.2)
        self.assertEqual(row["server"]["prompt_tokens"], 452)
        self.assertEqual(row["server"]["completion_tokens"], 24)
        self.assertEqual(row["server"]["total_duration_ns"], 2_000_000)
        self.assertEqual(
            row["validation_diagnostics"],
            [
                "lexical invariant 1 missing (expected length 8)",
                "lexical invariant 2 missing (expected length 10)",
            ],
        )
        self.assertNotIn("The case is ready", json.dumps(row))
        self.assertNotIn("CASE-741", json.dumps(row))

    def test_response_is_on_disk_when_invariant_validation_starts(self):
        body = json.dumps(
            {
                "response": "CASE-741 2026-10-22",
                "done": True,
                "done_reason": "stop",
            }
        ).encode()
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "response.json"

            def check_invariants(response, invariants):
                self.assertEqual(evidence.read_bytes(), body)
                return []

            with patch(
                "scripts.m05a_eval.invariant_flags", side_effect=check_invariants
            ):
                row = m05b_stage2a.record_response(
                    body=body,
                    evidence_path=evidence,
                    case=self.case,
                    context=4096,
                    client_seconds=1.0,
                )

        self.assertEqual(row["quality_status"], "passed")

    def test_incomplete_response_retains_metrics_without_quality_check(self):
        body = json.dumps(
            {"response": "partial", "done": False, "eval_count": 7}
        ).encode()
        with tempfile.TemporaryDirectory() as temporary:
            row = m05b_stage2a.record_response(
                body=body,
                evidence_path=Path(temporary) / "response.json",
                case=self.case,
                context=4096,
                client_seconds=1.25,
            )
        self.assertEqual(row["completion_status"], "incomplete")
        self.assertEqual(row["quality_status"], "not_evaluated")
        self.assertEqual(row["server"]["completion_tokens"], 7)
        self.assertIn(
            "completion marker `done` is not true", row["validation_diagnostics"]
        )

    def test_import_failure_during_quality_check_does_not_lose_metrics(self):
        body = json.dumps(
            {
                "response": "CASE-741 2026-10-22",
                "done": True,
                "load_duration": 11,
                "total_duration": 22,
                "prompt_eval_duration": 33,
                "eval_duration": 44,
                "prompt_eval_count": 452,
                "eval_count": 24,
            }
        ).encode()
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "response.json"
            with patch.dict("sys.modules", {"scripts.m05a_eval": None}):
                row = m05b_stage2a.record_response(
                    body=body,
                    evidence_path=evidence,
                    case=self.case,
                    context=4096,
                    client_seconds=10.219,
                )
            self.assertEqual(evidence.read_bytes(), body)
        self.assertEqual(row["completion_status"], "completed")
        self.assertEqual(row["quality_status"], "error")
        self.assertEqual(row["client_total_s"], 10.219)
        self.assertEqual(row["server"]["prompt_tokens"], 452)
        self.assertEqual(row["server"]["completion_tokens"], 24)
        self.assertIn(
            "text-quality validation raised ModuleNotFoundError",
            row["validation_diagnostics"],
        )

    def test_oversized_response_saves_only_bounded_prefix_and_reports_limit(self):
        body = b"x" * (m05b_stage2a.MAX_RESPONSE_BYTES + 10)
        with tempfile.TemporaryDirectory() as temporary:
            evidence = Path(temporary) / "response.json"
            row = m05b_stage2a.record_response(
                body=body,
                evidence_path=evidence,
                case=self.case,
                context=8192,
                client_seconds=4.0,
            )
            self.assertEqual(evidence.stat().st_size, m05b_stage2a.MAX_RESPONSE_BYTES)
        self.assertEqual(row["completion_status"], "unvalidated_oversized_response")
        self.assertEqual(row["client_total_s"], 4.0)
        self.assertEqual(row["quality_status"], "not_evaluated")


if __name__ == "__main__":
    unittest.main()
