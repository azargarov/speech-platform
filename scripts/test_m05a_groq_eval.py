import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from scripts import m05a_eval, m05a_groq_eval as groq

PROMPT = m05a_eval.ROOT / "docs/milestones/M05A/prompts/v2.md"


class Response:
    def __init__(self, payload, headers=None, status=200):
        self.content = json.dumps(payload).encode()
        self.headers = headers or {}
        self.status_code = status

    def json(self):
        return json.loads(self.content)


class GroqEvalTests(unittest.TestCase):
    def setUp(self):
        self.case = m05a_eval.read_cases()[0]
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "private").mkdir(mode=0o700)
        (root / "private/m05a").mkdir(mode=0o700)
        corpus = root / "docs/milestones/M05A"
        corpus.mkdir(parents=True)
        for name in ("cases.jsonl", "unseen-cases.jsonl"):
            shutil.copyfile(
                m05a_eval.ROOT / "docs/milestones/M05A" / name, corpus / name
            )
        (corpus / "prompts").mkdir()
        shutil.copyfile(PROMPT, corpus / "prompts/v2.md")
        self.enterContext(patch.object(m05a_eval, "ROOT", root))

    def test_missing_key_is_rejected_before_network(self):
        with self.assertRaisesRegex(ValueError, "GROQ_API_KEY"):
            groq.call_groq({}, "", 3)

    def test_serialization_uses_exact_model_and_shared_case_fields(self):
        payload = groq.request_payload("qwen/qwen3.8-27b", "prompt-v2", self.case)
        self.assertEqual(payload["model"], "qwen/qwen3.8-27b")
        self.assertEqual(
            payload["messages"][0], {"role": "system", "content": "prompt-v2"}
        )
        user = json.loads(payload["messages"][1]["content"])
        self.assertEqual(user["text"], self.case["text"])
        self.assertEqual(user["target_language"], self.case["target_language"])
        self.assertEqual(payload["reasoning_effort"], "none")

    def test_model_specific_reasoning_configuration(self):
        qwen = groq.request_payload("qwen/qwen3.8-27b", "p", self.case)
        gpt = groq.request_payload("openai/gpt-oss-120b", "p", self.case)
        self.assertEqual(qwen["reasoning_effort"], "none")
        self.assertEqual(gpt["reasoning_effort"], "low")
        self.assertFalse(qwen["include_reasoning"])
        self.assertFalse(gpt["include_reasoning"])

    def test_success_parsing_records_usage_and_headers(self):
        response = Response(
            {
                "id": "resp-1",
                "model": "qwen/qwen3.8-27b",
                "choices": [{"message": {"content": "Hej"}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                },
            },
            {
                "x-groq-processing-time": "0.03s",
                "x-ratelimit-remaining-requests": "999",
            },
        )
        result = groq.call_groq(
            {"model": "qwen/qwen3.8-27b"},
            "secret-value",
            3,
            post=lambda *args, **kwargs: response,
        )
        self.assertEqual(result["response"], "Hej")
        self.assertEqual(result["usage"]["total_tokens"], 12)
        self.assertEqual(result["rate_limits"]["x-ratelimit-remaining-requests"], "999")

    def test_429_retry_after_is_respected_with_cap(self):
        error = groq.GroqError("rate limited", status=429, headers={"Retry-After": "7"})
        self.assertEqual(groq._delay_for(error, 0, 2.1), 7)
        huge = groq.GroqError(
            "rate limited", status=429, headers={"Retry-After": "500"}
        )
        self.assertEqual(groq._delay_for(huge, 0, 1), 120)

    def test_http_429_response_is_classified_without_body_or_secret_leak(self):
        error = Response(
            {"error": {"message": "daily quota exhausted"}},
            {"Retry-After": "4"},
            status=429,
        )
        with self.assertRaises(groq.GroqError) as caught:
            groq.call_groq(
                {"model": "qwen/qwen3.8-27b"},
                "secret-value",
                2,
                post=lambda *args, **kwargs: error,
            )
        self.assertEqual(caught.exception.status, 429)
        self.assertTrue(caught.exception.fatal)
        self.assertEqual(caught.exception.headers.get("Retry-After"), "4")
        self.assertNotIn("daily quota", str(caught.exception))

    def test_run_rejects_missing_key_before_creating_artifacts(self):
        with tempfile.TemporaryDirectory(
            dir=groq.m05a_eval.ROOT / "private/m05a"
        ) as tmp:
            run_dir = Path(tmp) / "missing-key"
            with self.assertRaisesRegex(ValueError, "GROQ_API_KEY"):
                groq.run(
                    "qwen/qwen3.8-27b",
                    run_dir,
                    [self.case],
                    PROMPT,
                    "v2",
                    0,
                    5,
                    0,
                    api_key="",
                )
            self.assertFalse(run_dir.exists())

    def test_auth_invalid_model_and_quota_classification(self):
        self.assertTrue(groq._safe_error(401, b"")[1])
        self.assertEqual(groq._safe_error(404, b"")[0], "invalid model or endpoint")
        self.assertTrue(
            groq._safe_error(429, b'{"error":{"message":"daily quota exceeded"}}')[1]
        )
        self.assertFalse(
            groq._safe_error(
                429, b'{"error":{"message":"request rate limit reached per minute"}}'
            )[1]
        )

    def test_rejected_reasoning_setting_is_reported_without_fallback(self):
        message, fatal = groq._safe_error(
            400,
            b'{"error":{"message":"reasoning_effort low is unsupported"}}',
        )
        self.assertEqual(
            message, "provider rejected the requested reasoning configuration"
        )
        self.assertTrue(fatal)

    def test_transient_5xx_is_retryable_without_provider_body_leak(self):
        message, fatal = groq._safe_error(
            503, b'{"error":{"message":"secret payload"}}'
        )
        self.assertEqual(message, "transient provider error")
        self.assertFalse(fatal)
        self.assertNotIn("secret payload", message)

    def test_run_retries_transient_failure_then_persists_single_success(self):
        completion = {
            "response": "out",
            "latency_seconds": 0.3,
            "provider_processing_time": None,
            "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "finish_reason": "stop",
            "response_id": "response-2",
            "system_fingerprint": None,
            "http_status": 200,
            "model": "qwen/qwen3.8-27b",
            "rate_limits": {},
        }
        with tempfile.TemporaryDirectory(
            dir=groq.m05a_eval.ROOT / "private/m05a"
        ) as tmp:
            run_dir = Path(tmp) / "retry"
            with (
                patch.object(
                    groq,
                    "call_groq",
                    side_effect=[
                        groq.GroqError("transient provider error", status=503),
                        completion,
                    ],
                ),
                patch.object(groq.time, "sleep"),
            ):
                self.assertEqual(
                    groq.run(
                        "qwen/qwen3.8-27b",
                        run_dir,
                        [self.case],
                        PROMPT,
                        "v2",
                        0,
                        5,
                        1,
                        api_key="secret-value",
                    ),
                    0,
                )
            row = json.loads((run_dir / "results.jsonl").read_text().strip())
            summary = json.loads((run_dir / "summary.json").read_text())
            self.assertEqual(row["response"], "out")
            self.assertEqual(row["retries"], 1)
            self.assertEqual(summary["request_count"], 2)
            self.assertEqual(summary["successful_count"], 1)

    def test_timeout_is_sanitized(self):
        with self.assertRaisesRegex(groq.GroqError, "request timeout") as caught:
            with patch.object(
                groq.requests, "post", side_effect=requests.Timeout("secret-value")
            ):
                groq.call_groq({"model": "qwen/qwen3.8-27b"}, "secret-value", 1)
        self.assertNotIn("secret-value", str(caught.exception))

    def test_malformed_api_response_is_a_provider_error(self):
        with self.assertRaisesRegex(groq.GroqError, "malformed completion"):
            groq.call_groq(
                {},
                "secret-value",
                1,
                post=lambda *args, **kwargs: Response({"choices": []}),
            )

    def test_preview_validates_and_summarizes_without_key_or_network(self):
        output = io.StringIO()
        with (
            patch.dict("os.environ", {"GROQ_API_KEY": ""}),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(groq.main(["--preview", "--model", "qwen/qwen3.8-27b"]), 0)
        planned = json.loads(output.getvalue())
        self.assertEqual(planned["case_count"], 46)
        self.assertEqual(planned["planned_requests"], 46)

    def test_result_persistence_and_resume_skip_completed_case(self):
        cases = [self.case]
        with tempfile.TemporaryDirectory(
            dir=groq.m05a_eval.ROOT / "private/m05a"
        ) as tmp:
            run_dir = Path(tmp)
            completion = {
                "response": "out",
                "latency_seconds": 0.2,
                "provider_processing_time": "0.1s",
                "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
                "finish_reason": "stop",
                "response_id": "r1",
                "system_fingerprint": None,
                "http_status": 200,
                "model": "qwen/qwen3.8-27b",
                "rate_limits": {},
            }
            with patch.object(groq, "call_groq", return_value=completion):
                self.assertEqual(
                    groq.run(
                        "qwen/qwen3.8-27b",
                        run_dir,
                        cases,
                        PROMPT,
                        "v2",
                        0,
                        5,
                        0,
                        api_key="secret-value",
                    ),
                    0,
                )
            result_text = (run_dir / "results.jsonl").read_text()
            self.assertIn('"case_id": "' + self.case["id"] + '"', result_text)
            self.assertNotIn("secret-value", result_text)
            with patch.object(
                groq, "call_groq", side_effect=AssertionError("should skip")
            ):
                self.assertEqual(
                    groq.run(
                        "qwen/qwen3.8-27b",
                        run_dir,
                        cases,
                        PROMPT,
                        "v2",
                        0,
                        5,
                        0,
                        resume=True,
                        api_key="secret-value",
                    ),
                    0,
                )


if __name__ == "__main__":
    unittest.main()
