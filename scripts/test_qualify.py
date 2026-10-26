from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import yaml

from scripts import qualify


TOKEN = "synthetic-token-that-never-appears-in-reports-123"


class Response:
    status = 200
    headers = {
        "X-Speech-Provider": "local",
        "X-Speech-Prompt-SHA256": "a" * 64,
        "Content-Type": "application/json",
    }

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size):
        return self.body


def wav_bytes():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 1600)
    return buffer.getvalue()


class QualificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "private").mkdir()
        self.env = {
            "SPEECH_API_URL": "http://127.0.0.1:8080",
            "SPEECH_API_TOKEN": TOKEN,
        }

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, argv, body):
        captured = {}

        def open_url(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return Response(body)

        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", side_effect=open_url),
        ):
            status = qualify.main(argv)
        return status, captured

    def test_transform_omits_default_model_and_keeps_report_content_free(self):
        status, seen = self.invoke(
            ["transform", "--text", "private synthetic words"],
            json.dumps(
                {
                    "original_text": "source",
                    "transformed_text": "private output",
                    "options": {
                        "mode": "written",
                        "format": "normal",
                        "target_language": "none",
                        "model": None,
                        "local_only": True,
                    },
                    "provider": "host-ollama",
                    "model": "local-qwen",
                    "generated": True,
                    "fallback_occurred": False,
                }
            ).encode(),
        )
        self.assertEqual(status, 0)
        request = seen["request"]
        self.assertEqual(request.get_header("Authorization"), f"Bearer {TOKEN}")
        payload = json.loads(request.data)
        self.assertNotIn("model", payload)
        self.assertTrue(payload["local_only"])
        self.assertEqual(payload["target_language"], "none")
        self.assertNotIn("private synthetic words", str(seen))

    def test_successful_transform_prints_complete_output_and_preserves_report_evidence(
        self,
    ):
        transformed = "Complete transformed output.\nSecond line."
        report_path = self.root / "private" / "transform-report.json"
        evidence_path = self.root / "private" / "transform-evidence.json"
        response = {
            "original_text": "source",
            "transformed_text": transformed,
            "options": {
                "mode": "written",
                "format": "normal",
                "target_language": "none",
                "model": None,
                "local_only": True,
            },
            "model": "local-qwen",
            "provider": "host-ollama",
            "generated": True,
            "fallback_occurred": False,
        }
        stdout = io.StringIO()
        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(
                qualify, "urlopen", return_value=Response(json.dumps(response).encode())
            ),
            contextlib.redirect_stdout(stdout),
        ):
            status = qualify.main(
                [
                    "transform",
                    "--text",
                    "source",
                    "--report",
                    str(report_path),
                    "--evidence",
                    str(evidence_path),
                ]
            )
        self.assertEqual(status, 0)
        self.assertIn(transformed, stdout.getvalue())
        self.assertEqual(json.loads(report_path.read_text())["outcome"], "pass")
        self.assertEqual(
            json.loads(evidence_path.read_text())["transformed_text"], transformed
        )

    def test_failed_transform_does_not_print_transformation_output(self):
        stdout = io.StringIO()

        def reject(request, timeout):
            raise HTTPError(request.full_url, 503, "Unavailable", {}, io.BytesIO(b"{}"))

        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", side_effect=reject),
            contextlib.redirect_stdout(stdout),
        ):
            status = qualify.main(["transform", "--text", "source"])
        self.assertEqual(status, qualify.EXIT_REQUEST)
        self.assertNotIn("transformed", stdout.getvalue())

    def test_explicit_local_model_is_sent_unchanged(self):
        alias = "synthetic-local-alias"
        body = {
            "original_text": "source",
            "transformed_text": "output",
            "options": {
                "mode": "written",
                "format": "normal",
                "target_language": "none",
                "model": alias,
                "local_only": True,
            },
            "model": alias,
            "provider": "host-ollama",
            "fallback_occurred": False,
            "generated": True,
        }
        status, seen = self.invoke(
            ["transform", "--text", "source", "--model", alias],
            json.dumps(body).encode(),
        )
        payload = json.loads(seen["request"].data)
        self.assertEqual(status, 0)
        self.assertEqual(payload["model"], alias)
        self.assertTrue(payload["local_only"])

    def test_explicit_cloud_model_requires_cli_consent_and_gateway_policy(self):
        alias = "synthetic-cloud-alias"
        body = {
            "original_text": "source",
            "transformed_text": "output",
            "options": {
                "mode": "written",
                "format": "normal",
                "target_language": "none",
                "model": alias,
                "local_only": False,
            },
            "model": alias,
            "provider": "synthetic-cloud-provider",
            "fallback_occurred": False,
            "generated": True,
        }
        status, seen = self.invoke(
            [
                "transform",
                "--text",
                "source",
                "--model",
                alias,
                "--allow-cloud",
            ],
            json.dumps(body).encode(),
        )
        payload = json.loads(seen["request"].data)
        self.assertEqual(status, 0)
        self.assertEqual(payload["model"], alias)
        self.assertFalse(payload["local_only"])

    def test_gateway_authorization_and_alias_errors_are_preserved(self):
        cases = (
            ("synthetic-cloud-alias", (), 403, "cloud_not_allowed", True),
            (
                "synthetic-cloud-alias",
                ("--allow-cloud",),
                403,
                "cloud_disabled",
                False,
            ),
            ("unavailable-alias", (), 400, "unknown_model", True),
        )
        for index, (alias, options, status_code, api_code, local_only) in enumerate(
            cases
        ):
            with self.subTest(alias=alias, options=options):
                report_path = self.root / "private" / f"{alias}-{index}-failure.json"
                captured = {}

                def reject(request, timeout):
                    captured["request"] = request
                    raise HTTPError(
                        request.full_url,
                        status_code,
                        "Gateway error",
                        {},
                        io.BytesIO(
                            json.dumps(
                                {
                                    "code": api_code,
                                    "message": "synthetic private provider detail",
                                }
                            ).encode()
                        ),
                    )

                stdout = io.StringIO()
                with (
                    patch.object(qualify, "ROOT", self.root),
                    patch.object(qualify, "load_env", return_value=self.env),
                    patch.object(qualify, "urlopen", side_effect=reject),
                    contextlib.redirect_stdout(stdout),
                ):
                    result = qualify.main(
                        [
                            "transform",
                            "--text",
                            "source",
                            "--model",
                            alias,
                            *options,
                            "--report",
                            str(report_path),
                        ]
                    )

                payload = json.loads(captured["request"].data)
                report = json.loads(report_path.read_text())
                self.assertEqual(result, qualify.EXIT_REQUEST)
                self.assertEqual(payload["model"], alias)
                self.assertEqual(payload["local_only"], local_only)
                self.assertEqual(report["http"]["status"], status_code)
                self.assertEqual(report["error"]["api_code"], api_code)
                self.assertNotIn(
                    "synthetic private provider detail", report_path.read_text()
                )
                self.assertNotIn("synthetic private provider detail", stdout.getvalue())

    def test_expected_gateway_api_error_is_a_qualified_result(self):
        report_path = self.root / "private" / "expected.json"
        body = json.dumps(
            {"code": "cloud_not_allowed", "message": "not exposed"}
        ).encode()

        def reject(request, timeout):
            del timeout
            raise HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(body))

        stdout = io.StringIO()
        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", side_effect=reject),
            contextlib.redirect_stdout(stdout),
        ):
            status = qualify.main(
                [
                    "transform",
                    "--text",
                    "synthetic input",
                    "--model",
                    "groq-qwen",
                    "--expect-error",
                    "cloud_not_allowed",
                    "--report",
                    str(report_path),
                ]
            )
        report = json.loads(report_path.read_text())
        self.assertEqual(status, 0)
        self.assertFalse(report["http"]["success"])
        self.assertEqual(report["http"]["status"], 403)
        self.assertEqual(report["error"]["api_code"], "cloud_not_allowed")
        self.assertEqual(
            report["expected_api_error"],
            {"code": "cloud_not_allowed", "matched": True},
        )
        self.assertEqual(report["outcome"], "pass")
        self.assertEqual(report["capability_state"], "disabled")
        self.assertIn("expected API error cloud_not_allowed", stdout.getvalue())
        self.assertNotIn("not exposed", report_path.read_text())

    def test_expected_gateway_error_fails_when_request_succeeds(self):
        report_path = self.root / "private" / "unexpected-success.json"
        response = {
            "original_text": "source",
            "transformed_text": "output",
            "options": {
                "mode": "written",
                "format": "normal",
                "target_language": "none",
                "model": None,
                "local_only": True,
            },
            "model": "local-qwen",
            "provider": "host-ollama",
            "generated": True,
            "fallback_occurred": False,
        }
        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(
                qualify, "urlopen", return_value=Response(json.dumps(response).encode())
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status = qualify.main(
                [
                    "transform",
                    "--text",
                    "synthetic input",
                    "--expect-error",
                    "cloud_not_allowed",
                    "--report",
                    str(report_path),
                ]
            )
        report = json.loads(report_path.read_text())
        self.assertEqual(status, qualify.EXIT_REQUEST)
        self.assertTrue(report["http"]["success"])
        self.assertEqual(report["outcome"], "fail")
        self.assertFalse(report["expected_api_error"]["matched"])
        self.assertEqual(
            report["error"]["classification"], "expected_error_not_observed"
        )

    def test_cli_option_choices_match_public_openapi_enums(self):
        root = Path(__file__).resolve().parents[1]
        spec = yaml.safe_load((root / "api/openapi/public-v1.yaml").read_text())
        parser = qualify._parser()
        subparsers = next(
            action.choices
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )

        def choices(command, option):
            action = next(
                action
                for action in subparsers[command]._actions
                if option in action.option_strings
            )
            return set(action.choices)

        stt = spec["paths"]["/v1/stt/transcriptions"]["post"]
        stt_schema = stt["requestBody"]["content"]["multipart/form-data"]["schema"]
        headers = {parameter["name"]: parameter for parameter in stt["parameters"]}
        transform = spec["components"]["schemas"]["TextTransformRequest"]["properties"]
        tts = spec["paths"]["/v1/tts/speech"]["post"]["requestBody"]["content"][
            "application/json"
        ]["schema"]["properties"]

        self.assertEqual(
            choices("stt", "--source-language"),
            set(stt_schema["properties"]["source_language"]["enum"]),
        )
        self.assertEqual(
            choices("stt", "--output-language"),
            set(stt_schema["properties"]["output_language"]["enum"]),
        )
        self.assertEqual(
            choices("stt", "--provider"),
            set(headers["X-STT-Provider"]["schema"]["enum"]),
        )
        self.assertEqual(choices("transform", "--mode"), set(transform["mode"]["enum"]))
        self.assertEqual(
            choices("transform", "--format"), set(transform["format"]["enum"])
        )
        self.assertEqual(
            choices("transform", "--target-language"),
            set(transform["target_language"]["enum"]),
        )
        self.assertEqual(choices("tts", "--language"), set(tts["language"]["enum"]))
        self.assertEqual(choices("tts", "--voice"), set(tts["voice"]["enum"]))
        self.assertEqual(choices("tts", "--mode"), set(tts["mode"]["enum"]))
        self.assertEqual(
            choices("tts", "--audio-processing"), set(tts["audio_processing"]["enum"])
        )
        self.assertEqual(
            choices("tts", "--input-format"), set(tts["input_format"]["enum"])
        )

    def test_every_openapi_operation_has_a_qualification_command(self):
        spec = yaml.safe_load(
            (
                Path(__file__).resolve().parents[1] / "api/openapi/public-v1.yaml"
            ).read_text()
        )
        subparsers = next(
            action.choices
            for action in qualify._parser()._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        operation_commands = {
            "transcribe": "stt",
            "synthesize": "tts",
            "listVoices": "voices",
            "transformText": "transform",
            "warmupModels": "warmup",
        }
        found = {
            operation_id
            for path in spec["paths"].values()
            for operation in path.values()
            if isinstance(operation, dict)
            for operation_id in [operation.get("operationId")]
            if operation_id
        }
        self.assertEqual(found, set(operation_commands))
        self.assertTrue(set(operation_commands.values()).issubset(subparsers))

    def test_request_fields_and_warmup_enum_have_contract_coverage(self):
        parser = qualify._parser()
        subparsers = next(
            action.choices
            for action in parser._actions
            if isinstance(action, argparse._SubParsersAction)
        )

        def options(command):
            return {
                option
                for action in subparsers[command]._actions
                for option in action.option_strings
            }

        self.assertTrue(
            {
                "--audio",
                "--source-language",
                "--output-language",
                "--model",
                "--provider",
                "--allow-cloud-audio",
                "--timestamps",
                "--stream",
            }
            <= options("stt")
        )
        self.assertTrue(
            {
                "--text",
                "--text-file",
                "--mode",
                "--format",
                "--target-language",
                "--model",
                "--allow-cloud",
            }
            <= options("transform")
        )
        self.assertTrue(
            {
                "--text",
                "--text-file",
                "--voice",
                "--language",
                "--mode",
                "--input-format",
                "--audio-processing",
                "--output",
            }
            <= options("tts")
        )
        spec = yaml.safe_load(
            (
                Path(__file__).resolve().parents[1] / "api/openapi/public-v1.yaml"
            ).read_text()
        )
        warmup = spec["components"]["schemas"]["ModelWarmupRequest"]["properties"][
            "operations"
        ]["items"]["enum"]
        operation_action = next(
            action
            for action in subparsers["warmup"]._actions
            if "--operation" in action.option_strings
        )
        self.assertEqual(set(operation_action.choices), set(warmup))

    def test_stt_controls_unsupported_options_without_hiding_gateway_error(self):
        audio = self.root / "probe.wav"
        audio.write_bytes(b"wav")
        seen = {}

        def reject(request, **_kwargs):
            seen["request"] = request
            raise HTTPError(
                request.full_url,
                400,
                "Bad Request",
                {},
                io.BytesIO(b'{"code":"invalid_options","message":"unsupported"}'),
            )

        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", side_effect=reject),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status = qualify.main(
                [
                    "stt",
                    "--audio",
                    str(audio),
                    "--timestamps",
                    "--stream",
                    "--expect-error",
                    "invalid_options",
                ]
            )
        self.assertEqual(status, 0)
        request = seen["request"]
        self.assertIn(b'name="timestamps"\r\n\r\ntrue', request.data)
        self.assertIn(b'name="stream"\r\n\r\ntrue', request.data)

    def test_model_catalog_is_not_advertised_or_exposed_by_gateway_cli(self):
        spec_path = Path(__file__).resolve().parents[1] / "api/openapi/public-v1.yaml"
        spec = yaml.safe_load(spec_path.read_text())
        self.assertNotIn("/v1/stt/models", spec["paths"])
        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            qualify.main(["models"])
        self.assertEqual(raised.exception.code, 2)

    def test_warmup_uses_contract_route_and_authentication(self):
        status, seen = self.invoke(
            ["warmup", "--operation", "stt", "--operation", "tts"],
            b'{"results":[{"operation":"stt","status":"ready"},{"operation":"tts","status":"ready"}],"complete":true}',
        )
        self.assertEqual(status, 0)
        self.assertEqual(
            json.loads(seen["request"].data), {"operations": ["stt", "tts"]}
        )

    def test_metrics_report_names_without_metric_values(self):
        status, _seen = self.invoke(
            ["metrics"],
            b'# HELP speech_ready Ready\nspeech_ready 1\nspeech_requests_total{provider="local"} 9\n',
        )
        self.assertEqual(status, 0)

    def test_missing_auth_probe_requires_expected_unauthorized(self):
        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            qualify.main(["voices", "--auth-mode", "missing"])
        self.assertEqual(raised.exception.code, 2)

    def test_nonfinite_timeout_is_rejected_before_request(self):
        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as raised,
            patch.object(qualify, "urlopen") as opened,
        ):
            qualify.main(["health", "--timeout", "nan"])
        self.assertEqual(raised.exception.code, 2)
        opened.assert_not_called()

    def test_resource_error_code_has_specific_safe_guidance(self):
        guidance = qualify._troubleshooting("http_error", "resource_exhausted")
        self.assertIn("resource exhaustion", guidance)
        self.assertIn("Do not retry automatically", guidance)

    def test_debug_resource_failure_saves_correlated_redacted_local_logs(self):
        output = io.StringIO()
        error = io.StringIO()

        def fail_request(_request, **_kwargs):
            raise HTTPError(
                "http://127.0.0.1:8080/v1/tts/speech",
                503,
                "Service Unavailable",
                {"X-Request-ID": "server-id-42"},
                io.BytesIO(
                    b'{"code":"resource_exhausted","message":"GPU resources are temporarily unavailable"}'
                ),
            )

        def fake_logs(args, **_kwargs):
            service = args[-1]
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    f'{service}-1 | {{"event":"inference_failure","request_id":"server-id-42","code":"resource_exhausted","text":"synthetic private text"}}\n'
                    f'{service}-1 | {{"event":"unrelated","request_id":"other"}}\n'
                ),
            )

        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify.diagnostics, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", side_effect=fail_request),
            patch("scripts.compose.run", side_effect=fake_logs),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(error),
        ):
            status = qualify.main(
                ["tts", "--text", "synthetic private text", "--debug"]
            )

        self.assertEqual(status, qualify.EXIT_REQUEST)
        self.assertIn("HTTP 503", output.getvalue())
        self.assertIn("api_code=resource_exhausted", output.getvalue())
        self.assertIn(
            "debug evidence saved: private/qualification-debug-", error.getvalue()
        )
        evidence_path = next((self.root / "private").glob("qualification-debug-*.json"))
        evidence = json.loads(evidence_path.read_text())
        self.assertEqual(evidence_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(evidence["result"]["error"]["api_code"], "resource_exhausted")
        self.assertEqual(
            evidence["diagnostics"]["services"]["tts"]["correlation"],
            "server_request_id_match",
        )
        serialized = evidence_path.read_text()
        self.assertNotIn(TOKEN, serialized)
        self.assertNotIn("synthetic private text", serialized)

    def test_none_auth_mode_omits_header_for_an_intentionally_open_gateway(self):
        status, seen = self.invoke(
            ["voices", "--auth-mode", "none"],
            b'[{"id":"default","languages":["en"],"streaming":false}]',
        )
        self.assertEqual(status, 0)
        self.assertIsNone(seen["request"].get_header("Authorization"))

    def test_normal_request_does_not_collect_local_compose_logs(self):
        with patch.object(qualify.diagnostics, "collect_local_logs") as collect:
            status, _seen = self.invoke(
                ["voices"],
                b'[{"id":"default","languages":["en"],"streaming":false}]',
            )
        self.assertEqual(status, 0)
        collect.assert_not_called()

    def test_missing_auth_mode_sends_no_authorization_and_requires_expected_401(self):
        def reject(request, **_kwargs):
            self.assertIsNone(request.get_header("Authorization"))
            raise HTTPError(
                request.full_url,
                401,
                "Unauthorized",
                {},
                io.BytesIO(
                    b'{"code":"unauthorized","message":"valid bearer token required"}'
                ),
            )

        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", side_effect=reject),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status = qualify.main(
                [
                    "voices",
                    "--auth-mode",
                    "missing",
                    "--expect-error",
                    "unauthorized",
                ]
            )
        self.assertEqual(status, 0)

    def test_explicit_gateway_target_and_private_token_file(self):
        token_path = self.root / "private" / "target-token"
        token_path.write_text(TOKEN)
        token_path.chmod(0o600)
        body = {
            "original_text": "source",
            "transformed_text": "output",
            "options": {
                "mode": "written",
                "format": "normal",
                "target_language": "none",
                "model": None,
                "local_only": True,
            },
            "model": "local-qwen",
            "provider": "host-ollama",
            "generated": True,
            "fallback_occurred": False,
        }
        status, seen = self.invoke(
            [
                "transform",
                "--text",
                "source",
                "--gateway-url",
                "https://gateway.example",
                "--api-token-file",
                str(token_path),
            ],
            json.dumps(body).encode(),
        )
        self.assertEqual(status, 0)
        self.assertEqual(
            seen["request"].full_url, "https://gateway.example/v1/text/transformations"
        )
        self.assertEqual(seen["request"].get_header("Authorization"), f"Bearer {TOKEN}")

    def test_safe_response_correlation_metadata_is_recorded(self):
        body = {
            "original_text": "source",
            "transformed_text": "output",
            "options": {
                "mode": "written",
                "format": "normal",
                "target_language": "none",
                "model": None,
                "local_only": True,
            },
            "model": "local-qwen",
            "provider": "host-ollama",
            "generated": True,
            "fallback_occurred": False,
        }
        response = Response(json.dumps(body).encode())
        response.headers = {**Response.headers, "X-Request-ID": "safe-id-123"}
        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", return_value=response),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            args = qualify._parser().parse_args(["transform", "--text", "source"])
            report = qualify._execute(args)
        self.assertEqual(report["diagnostics"]["server_request_id"], "safe-id-123")
        self.assertEqual(
            report["diagnostics"]["gateway_logs"], "not_available_via_public_api"
        )

    def test_groq_requires_explicit_consent_before_request(self):
        with (
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen") as opened,
        ):
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                qualify.main(
                    [
                        "stt",
                        "--audio",
                        str(self.root / "missing.wav"),
                        "--provider",
                        "groq",
                    ]
                )
        self.assertEqual(raised.exception.code, 2)
        opened.assert_not_called()

    def test_stt_pins_local_and_extracts_provider_metadata(self):
        audio = self.root / "sample.wav"
        audio.write_bytes(b"audio-fixture")
        _, seen = self.invoke(
            ["stt", "--audio", str(audio)],
            json.dumps(
                {"text": "transcript", "language": "en", "detected_language": "en"}
            ).encode(),
        )
        request = seen["request"]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertEqual(headers["x-stt-provider"], "local")
        self.assertEqual(headers["x-allow-cloud-audio"], "false")

    def test_stt_sends_explicit_local_model_alias_in_multipart_form(self):
        audio = self.root / "sample.wav"
        audio.write_bytes(b"audio-fixture")
        _, seen = self.invoke(
            ["stt", "--audio", str(audio), "--model", "local-whisper-test"],
            json.dumps({"text": "transcript", "language": "en"}).encode(),
        )
        self.assertIn(b'name="model"\r\n\r\nlocal-whisper-test', seen["request"].data)

    def test_stt_model_alias_is_rejected_for_groq_before_request(self):
        audio = self.root / "sample.wav"
        audio.write_bytes(b"audio-fixture")
        with (
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen") as opened,
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            qualify.main(
                [
                    "stt",
                    "--audio",
                    str(audio),
                    "--provider",
                    "groq",
                    "--allow-cloud-audio",
                    "--model",
                    "not-supported-by-groq",
                ]
            )
        self.assertEqual(raised.exception.code, 2)
        opened.assert_not_called()

    def test_tts_validates_wav_and_writes_private_file_exclusively(self):
        output = self.root / "private" / "output.wav"
        status, seen = self.invoke(
            ["tts", "--text", "sample", "--output", str(output)], wav_bytes()
        )
        self.assertEqual(status, 0)
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        self.assertEqual(
            seen["request"].full_url, "http://127.0.0.1:8080/v1/tts/speech"
        )

    def test_tts_supports_contract_ssml_input_format(self):
        status, seen = self.invoke(
            [
                "tts",
                "--text",
                '<speak><prosody rate="slow">Hello.</prosody></speak>',
                "--input-format",
                "ssml",
            ],
            wav_bytes(),
        )
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(seen["request"].data)["input_format"], "ssml")

    def test_tts_writes_relative_absolute_and_non_private_paths(self):
        (self.root / "samples" / "audio").mkdir(parents=True)
        (self.root / "outside").mkdir()
        paths = (
            Path("relative.wav"),
            self.root / "absolute.wav",
            Path("samples/audio/en-polite.wav"),
            self.root / "outside" / "speech.wav",
        )
        original_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            for output in paths:
                with self.subTest(output=str(output)):
                    status, _ = self.invoke(
                        ["tts", "--text", "synthetic", "--output", str(output)],
                        wav_bytes(),
                    )
                    self.assertEqual(status, 0)
                    resolved = output.expanduser().absolute()
                    self.assertTrue(resolved.is_file())
                    self.assertEqual(stat.S_IMODE(resolved.stat().st_mode), 0o600)
        finally:
            os.chdir(original_cwd)

    def test_tts_expands_home_directory_output(self):
        home = self.root / "home"
        (home / "recordings").mkdir(parents=True)
        with patch.dict(os.environ, {"HOME": str(home)}):
            status, _ = self.invoke(
                ["tts", "--text", "synthetic", "--output", "~/recordings/speech.wav"],
                wav_bytes(),
            )
        output = home / "recordings" / "speech.wav"
        self.assertEqual(status, 0)
        self.assertTrue(output.is_file())
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)

    def test_tts_existing_output_collision_fails_before_request_with_safe_message(self):
        output = self.root / "existing.wav"
        output.write_bytes(b"keep")
        stdout = io.StringIO()
        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen") as opened,
            contextlib.redirect_stdout(stdout),
        ):
            status = qualify.main(
                ["tts", "--text", "private words", "--output", str(output)]
            )
        self.assertEqual(status, qualify.EXIT_INPUT)
        self.assertIn("HTTP N/A; elapsed=N/A", stdout.getvalue())
        self.assertIn("output file already exists", stdout.getvalue())
        self.assertNotIn("private words", stdout.getvalue())
        self.assertNotIn(TOKEN, stdout.getvalue())
        opened.assert_not_called()
        self.assertEqual(output.read_bytes(), b"keep")

    def test_tts_missing_output_parent_fails_before_request(self):
        output = self.root / "missing" / "speech.wav"
        stdout = io.StringIO()
        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen") as opened,
            contextlib.redirect_stdout(stdout),
        ):
            status = qualify.main(
                ["tts", "--text", "synthetic", "--output", str(output)]
            )
        self.assertEqual(status, qualify.EXIT_INPUT)
        self.assertIn("output directory does not exist:", stdout.getvalue())
        self.assertIn("HTTP N/A; elapsed=N/A", stdout.getvalue())
        opened.assert_not_called()

    def test_tts_permission_failure_has_safe_actionable_error_and_output_exit(self):
        output = self.root / "forbidden.wav"
        stdout = io.StringIO()
        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", return_value=Response(wav_bytes())),
            patch.object(qualify.os, "open", side_effect=PermissionError),
            contextlib.redirect_stdout(stdout),
        ):
            status = qualify.main(
                ["tts", "--text", "private words", "--output", str(output)]
            )
        self.assertEqual(status, qualify.EXIT_OUTPUT)
        self.assertIn("HTTP 200", stdout.getvalue())
        self.assertIn("permission denied creating output file", stdout.getvalue())
        self.assertNotIn("private words", stdout.getvalue())
        self.assertNotIn(TOKEN, stdout.getvalue())

    def test_report_and_evidence_remain_restricted_to_private(self):
        for option in ("--report", "--evidence"):
            with self.subTest(option=option):
                stdout = io.StringIO()
                with (
                    patch.object(qualify, "ROOT", self.root),
                    patch.object(qualify, "load_env", return_value=self.env),
                    patch.object(qualify, "urlopen") as opened,
                    contextlib.redirect_stdout(stdout),
                ):
                    status = qualify.main(
                        [
                            "tts",
                            "--text",
                            "synthetic",
                            option,
                            str(self.root / "outside.json"),
                        ]
                    )
                self.assertEqual(status, qualify.EXIT_INPUT)
                self.assertIn("under private/", stdout.getvalue())
                self.assertIn("HTTP N/A; elapsed=N/A", stdout.getvalue())
                opened.assert_not_called()

    def test_wav_rejects_truncation_and_incomplete_final_frame(self):
        valid = wav_bytes()
        with self.assertRaises(qualify.QualificationError):
            qualify._wav_metadata(valid[:-1])

        partial = bytearray(valid)
        data_header = partial.index(b"data")
        data_size = struct.unpack_from("<I", partial, data_header + 4)[0]
        partial.extend(b"\x7f\x00")  # One extra data byte and its RIFF pad byte.
        struct.pack_into("<I", partial, data_header + 4, data_size + 1)
        struct.pack_into("<I", partial, 4, len(partial) - 8)
        with self.assertRaises(qualify.QualificationError):
            qualify._wav_metadata(bytes(partial))

    def test_stt_rejects_missing_required_fields_and_invalid_types(self):
        audio = self.root / "sample.wav"
        audio.write_bytes(b"audio")
        for body in (
            {"text": "transcript"},
            {"text": 4, "language": "en"},
            {"text": "transcript", "language": None},
            {"text": "transcript", "language": "en", "translated": "false"},
        ):
            with self.subTest(body=body):
                status, _ = self.invoke(
                    ["stt", "--audio", str(audio)], json.dumps(body).encode()
                )
                self.assertEqual(status, qualify.EXIT_REQUEST)

    def test_transform_rejects_incomplete_response_and_invalid_field_types(self):
        good = {
            "original_text": "source",
            "transformed_text": "output",
            "options": {
                "mode": "written",
                "format": "normal",
                "target_language": "none",
                "model": None,
                "local_only": True,
            },
            "model": "local-qwen",
            "provider": "host-ollama",
            "fallback_occurred": False,
            "generated": True,
        }
        cases = []
        missing = good.copy()
        del missing["original_text"]
        cases.append(missing)
        invalid = good.copy()
        invalid["generated"] = "true"
        cases.append(invalid)
        invalid_options = good.copy()
        invalid_options["options"] = {**good["options"], "local_only": "yes"}
        cases.append(invalid_options)
        for body in cases:
            with self.subTest(body=body):
                status, _ = self.invoke(
                    ["transform", "--text", "source"], json.dumps(body).encode()
                )
                self.assertEqual(status, qualify.EXIT_REQUEST)

    def test_malformed_json_is_classified_as_invalid_response(self):
        status, _ = self.invoke(["transform", "--text", "source"], b"{")
        self.assertEqual(status, qualify.EXIT_REQUEST)

    def test_connection_failure_timeout_and_oversized_response_are_classified(self):
        for exception, expected in (
            (URLError(ConnectionRefusedError()), "connection"),
            (TimeoutError(), "timeout"),
            (URLError(TimeoutError()), "timeout"),
        ):
            with (
                self.subTest(expected=expected),
                patch.object(qualify, "urlopen", side_effect=exception),
            ):
                with self.assertRaises(qualify.QualificationError) as raised:
                    qualify._request(
                        "http://localhost", TOKEN, b"x", "text/plain", 1, 5
                    )
                self.assertEqual(raised.exception.classification, expected)
        with patch.object(qualify, "urlopen", return_value=Response(b"123456")):
            with self.assertRaises(qualify.QualificationError) as raised:
                qualify._request("http://localhost", TOKEN, b"x", "text/plain", 1, 5)
        self.assertEqual(raised.exception.classification, "invalid_response")

    def test_duplicate_canonical_output_paths_fail_before_request(self):
        (self.root / "private" / "nested").mkdir()
        first = self.root / "private" / "result.json"
        alias = self.root / "private" / "nested" / ".." / "result.json"
        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen") as opened,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            status = qualify.main(
                [
                    "tts",
                    "--text",
                    "sample",
                    "--report",
                    str(first),
                    "--output",
                    str(alias),
                ]
            )
        self.assertEqual(status, qualify.EXIT_INPUT)
        opened.assert_not_called()

    def test_file_output_failure_returns_output_exit_code(self):
        output = self.root / "private" / "out.wav"
        report_path = self.root / "private" / "report.json"
        actual_write = qualify._write_output

        def fail_audio(path, data, **kwargs):
            if path == output:
                raise qualify.QualificationError("output_error", "write failed")
            return actual_write(path, data, **kwargs)

        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", return_value=Response(wav_bytes())),
            patch.object(
                qualify,
                "_write_output",
                side_effect=fail_audio,
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status = qualify.main(
                [
                    "tts",
                    "--text",
                    "sample",
                    "--output",
                    str(output),
                    "--report",
                    str(report_path),
                ]
            )
        self.assertEqual(status, qualify.EXIT_OUTPUT)
        report = json.loads(report_path.read_text())
        self.assertEqual(report["http"], {"status": 200, "success": True})
        self.assertEqual(report["outcome"], "fail")
        self.assertEqual(
            report["technical_checks"], [{"name": "valid_pcm16_wav", "passed": True}]
        )
        self.assertFalse(report["artifact"]["saved"])

    def test_previous_audio_artifact_remains_if_report_write_fails(self):
        output = self.root / "private" / "out.wav"
        report = self.root / "private" / "report.json"
        actual_write = qualify._write_output

        def fail_report(path, data, **kwargs):
            if path == report:
                raise qualify.QualificationError("output_error", "write failed")
            return actual_write(path, data, **kwargs)

        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", return_value=Response(wav_bytes())),
            patch.object(qualify, "_write_output", side_effect=fail_report),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            status = qualify.main(
                [
                    "tts",
                    "--text",
                    "sample",
                    "--output",
                    str(output),
                    "--report",
                    str(report),
                ]
            )
        self.assertEqual(status, qualify.EXIT_OUTPUT)
        self.assertTrue(output.is_file())

    def test_http_error_preserves_api_code_without_message_payload(self):
        error = HTTPError(
            "https://gateway.invalid",
            403,
            "no",
            {},
            io.BytesIO(b'{"code":"cloud_disabled","message":"secret text"}'),
        )
        with patch.object(qualify, "urlopen", side_effect=error):
            with self.assertRaises(qualify.QualificationError) as raised:
                qualify._request(
                    "https://gateway.invalid", TOKEN, b"x", "application/json", 1, 1024
                )
        self.assertEqual(raised.exception.classification, "authorization")
        self.assertEqual(raised.exception.api_code, "cloud_disabled")
        self.assertNotIn("secret text", str(raised.exception))

    def test_json_report_is_private_exclusive_and_content_free(self):
        report_path = self.root / "private" / "report.json"
        body = json.dumps(
            {
                "original_text": "source",
                "transformed_text": "private output",
                "options": {
                    "mode": "written",
                    "format": "normal",
                    "target_language": "none",
                    "model": None,
                    "local_only": True,
                },
                "provider": "host-ollama",
                "model": "local-qwen",
                "generated": True,
                "fallback_occurred": False,
            }
        ).encode()
        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen", return_value=Response(body)),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status = qualify.main(
                ["transform", "--text", "secret input", "--report", str(report_path)]
            )
        report_text = report_path.read_text()
        report = json.loads(report_text)
        self.assertEqual(status, 0)
        self.assertEqual(stat.S_IMODE(report_path.stat().st_mode), 0o600)
        self.assertEqual(report["response"]["metadata"]["prompt_sha256"], "a" * 64)
        self.assertNotIn("secret input", report_text)
        self.assertNotIn("private output", report_text)
        self.assertEqual(report["schema_version"], "1.0")
        self.assertEqual(report["capability_state"], "available")

    def test_capability_state_distinguishes_disabled_unavailable_and_execution_failure(
        self,
    ):
        cases = (
            (
                {"api_code": "capability_disabled"},
                {"status": 503, "success": False},
                "fail",
                "disabled",
            ),
            (
                {"api_code": "provider_unavailable"},
                {"status": 503, "success": False},
                "fail",
                "configured_but_unavailable",
            ),
            (
                {"api_code": "worker_unavailable"},
                {"status": 503, "success": False},
                "fail",
                "configured_but_unavailable",
            ),
            (
                {"api_code": "invalid_worker_response"},
                {"status": 502, "success": False},
                "fail",
                "failing_during_execution",
            ),
            ({"api_code": None}, {"status": 200, "success": True}, "pass", "available"),
        )
        for error, http, outcome, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    qualify._capability_state(
                        {"error": error, "http": http, "outcome": outcome}
                    ),
                    expected,
                )

    def test_preflight_failure_can_be_recorded_without_sensitive_input(self):
        report_path = self.root / "private" / "failed.json"
        with (
            patch.object(qualify, "ROOT", self.root),
            patch.object(qualify, "load_env", return_value={}),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status = qualify.main(
                [
                    "transform",
                    "--text",
                    "do not record this",
                    "--report",
                    str(report_path),
                ]
            )
        report_text = report_path.read_text()
        report = json.loads(report_text)
        self.assertEqual(status, qualify.EXIT_INPUT)
        self.assertEqual(report["error"]["classification"], "authentication")
        self.assertNotIn("do not record this", report_text)

    def test_raw_structured_rejected_before_network(self):
        with (
            patch.object(qualify, "load_env", return_value=self.env),
            patch.object(qualify, "urlopen") as opened,
            patch.object(qualify, "ROOT", self.root),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            status = qualify.main(
                ["transform", "--text", "x", "--mode", "raw", "--format", "structured"]
            )
        self.assertEqual(status, qualify.EXIT_INPUT)
        opened.assert_not_called()

    def test_make_verification_keeps_original_smoke_cli_module_entrypoint(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "make",
                "-n",
                "test-stt",
                f"PYTHON={sys.executable}",
                "AUDIO=private/a.wav",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("-m scripts.api_smoke stt", result.stdout)


if __name__ == "__main__":
    unittest.main()
