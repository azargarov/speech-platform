"""Exercise one authenticated public SpeechPlatform Gateway operation."""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import re
import sys
import time
import uuid
import wave
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from scripts.api_smoke import MAX_STT_BYTES, MAX_TTS_BYTES, _multipart
from scripts import diagnostics
from scripts.preflight import ROOT, load_env

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_TTS_REQUEST_BYTES = 65536
EXIT_REQUEST = 1
EXIT_INPUT = 2
EXIT_OUTPUT = 3
API_ERROR_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class QualificationError(ValueError):
    def __init__(
        self,
        classification: str,
        message: str,
        *,
        status=None,
        api_code=None,
        failure_stage=None,
        response_headers=None,
    ):
        super().__init__(message)
        self.classification = classification
        self.status = status
        self.api_code = api_code
        self.failure_stage = failure_stage
        self.response_headers = response_headers or {}


def _origin(values, gateway_url=None, token_file=None, *, require_token=True):
    origin = (
        gateway_url
        or values.get(
            "SPEECH_API_URL", f"http://127.0.0.1:{values.get('SPEECH_PORT', '')}"
        )
    ).rstrip("/")
    parsed = urlparse(origin)
    try:
        port = parsed.port
    except ValueError:
        raise QualificationError(
            "local_validation", "SPEECH_API_URL contains an invalid port"
        ) from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise QualificationError(
            "local_validation", "SPEECH_API_URL must be an HTTP(S) origin"
        )
    loopback = parsed.hostname.lower() == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme == "http" and not loopback:
        raise QualificationError(
            "local_validation", "non-loopback Gateway URLs must use HTTPS"
        )
    if port is not None and not 1 <= port <= 65535:
        raise QualificationError(
            "local_validation", "SPEECH_API_URL port is out of range"
        )
    token = values.get("SPEECH_API_TOKEN", "")
    if token_file is not None:
        target = token_file.expanduser().absolute()
        if target.is_symlink() or not target.is_file():
            raise QualificationError("authentication", "API token file is unavailable")
        private = (ROOT / "private").resolve()
        if not target.resolve().is_relative_to(private):
            raise QualificationError(
                "authentication", "API token file must be under private/"
            )
        if target.stat().st_mode & 0o177:
            raise QualificationError(
                "authentication", "API token file permissions must be 0600 or stricter"
            )
        token = target.read_text(encoding="utf-8").strip()
    if require_token and len(token) < 32:
        raise QualificationError(
            "authentication", "SPEECH_API_TOKEN is missing or too short"
        )
    return origin, token if len(token) >= 32 else None


def _output_path(path, *, private=False):
    target = path.expanduser().absolute()
    if not target.parent.is_dir():
        raise QualificationError(
            "local_validation", f"output directory does not exist: {target.parent}"
        )
    if target.exists() or target.is_symlink():
        raise QualificationError("local_validation", "output file already exists")
    if private:
        return _private_path(target)
    return target.resolve(strict=False)


def _private_path(path):
    target = path.expanduser().absolute()
    private_root = ROOT / "private"
    if private_root.is_symlink():
        raise QualificationError(
            "local_validation", "private output directory must not be a symlink"
        )
    private = private_root.resolve()
    canonical = target.resolve(strict=False)
    if not canonical.is_relative_to(private):
        raise QualificationError(
            "local_validation",
            "report and evidence paths must be under private/",
        )
    if target.exists() or target.is_symlink():
        raise QualificationError("local_validation", "output file already exists")
    return canonical


def _validate_output_paths(args):
    paths = (
        (getattr(args, "report", None), True),
        (getattr(args, "evidence", None), True),
        (getattr(args, "output", None), False),
    )
    canonical = [
        _output_path(path, private=private)
        for path, private in paths
        if path is not None
    ]
    if len(set(canonical)) != len(canonical):
        raise QualificationError(
            "local_validation",
            "report, evidence, and audio outputs need different paths",
        )


def _write_output(path, data, *, private=False):
    try:
        target = _output_path(path, private=private)
    except QualificationError as exc:
        raise QualificationError("output_error", str(exc)) from None
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise QualificationError("output_error", "output file already exists") from None
    except PermissionError:
        raise QualificationError(
            "output_error", "permission denied creating output file"
        ) from None
    except OSError:
        raise QualificationError(
            "output_error", "could not create output file"
        ) from None
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
    except OSError:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            raise QualificationError(
                "output_error", "output write failed; a partial file may remain"
            ) from None
        raise QualificationError(
            "output_error", "output write failed; partial file removed"
        ) from None
    return target


def _response_error(status, raw, headers=None):
    code = None
    try:
        body = json.loads(raw)
        if isinstance(body, dict) and isinstance(body.get("code"), str):
            code = body["code"][:64]
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    classification = (
        "authentication"
        if status == 401
        else "authorization"
        if status == 403
        else "http_error"
    )
    return QualificationError(
        classification,
        f"Gateway returned HTTP {status}",
        status=status,
        api_code=code,
        failure_stage="gateway_response",
        response_headers=_safe_headers(headers or {}),
    )


def _safe_headers(headers):
    names = (
        "X-Request-ID",
        "X-Correlation-ID",
        "Traceparent",
        "Retry-After",
        "X-Speech-Provider",
        "X-Speech-Model",
        "X-Speech-Prompt-SHA256",
    )
    return {
        name.lower(): headers.get(name)
        for name in names
        if headers.get(name) is not None
    }


def _troubleshooting(classification, api_code=None):
    code_hints = {
        "resource_exhausted": "The selected worker reported resource exhaustion; check available GPU/worker capacity and service logs. Do not retry automatically.",
        "provider_unavailable": "The selected provider is disabled or unavailable. Check its enablement and private credential configuration; the Gateway did not substitute another provider.",
        "cloud_not_allowed": "Gateway cloud text policy denied this request; no CLI consent flag can override server policy.",
        "cloud_audio_not_authorized": "Groq STT requires explicit X-Allow-Cloud-Audio consent and an enabled provider.",
        "deadline_exceeded": "The Gateway deadline expired; inspect service readiness and configured request deadlines before retrying.",
        "unauthorized": "The Gateway rejected the bearer credential; check target and token source without printing the value.",
        "invalid_options": "One or more request options are unsupported or incompatible; compare them with the public API contract.",
        "unknown_model": "The supplied model alias is not configured; use an alias from trusted Gateway configuration.",
        "model_disabled": "The selected model is configured but disabled on this Gateway.",
    }
    if api_code in code_hints:
        return code_hints[api_code]
    hints = {
        "authentication": "Check the selected Gateway token and authentication configuration.",
        "authorization": "Check Gateway policy and explicit per-request cloud consent.",
        "connection": "Check the Gateway URL, network route, TLS endpoint and service health.",
        "timeout": "Check Gateway readiness and configured provider deadlines; avoid automatic retries.",
        "invalid_response": "Check Gateway and worker compatibility and inspect authorized service logs.",
        "http_error": "Use the preserved API error code and inspect authorized Gateway/provider logs.",
        "provider_mismatch": "Check the requested provider/policy and the Gateway serving-provider response header.",
        "warmup_incomplete": "Check per-operation warmup status and service readiness; a ready result does not guarantee continued residency.",
        "output_error": "Check destination permissions and free space; verify whether a previously completed artifact remains.",
        "local_validation": "Check the request options, input file and configured Gateway target.",
    }
    return hints.get(
        classification,
        f"Inspect the public API contract and the {api_code or classification} failure.",
    )


def _request(
    url,
    token,
    body,
    content_type,
    timeout,
    max_bytes,
    extra_headers=None,
    *,
    method=None,
):
    request_headers = {"Content-Type": content_type} if content_type else {}
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    request_headers.update(extra_headers or {})
    request = Request(url, data=body, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise QualificationError(
                    "invalid_response",
                    "Gateway response exceeded the client size limit",
                    status=response.status,
                    failure_stage="response_read",
                )
            return response.status, response.headers, data
    except HTTPError as exc:
        raw = exc.read(min(max_bytes, 65536))
        raise _response_error(exc.code, raw, exc.headers) from None
    except TimeoutError:
        raise QualificationError(
            "timeout", "Gateway request timed out", failure_stage="request"
        ) from None
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise QualificationError(
                "timeout", "Gateway request timed out", failure_stage="request"
            ) from None
        raise QualificationError(
            "connection", "Gateway request could not connect", failure_stage="connect"
        ) from None
    except OSError:
        raise QualificationError(
            "connection", "Gateway request could not connect", failure_stage="connect"
        ) from None


def _json_response(raw):
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise QualificationError(
            "invalid_response", "Gateway returned malformed JSON"
        ) from None
    if not isinstance(value, dict):
        raise QualificationError(
            "invalid_response", "Gateway returned an unexpected JSON response"
        )
    return value


def _input_text(args, max_characters=10000):
    if args.text_file:
        text = args.text_file.read_text(encoding="utf-8")
    elif args.text is not None:
        text = args.text
    else:
        text = sys.stdin.read(max_characters + 1)
    if not text or len(text) > max_characters:
        raise QualificationError(
            "local_validation",
            f"input must contain 1 to {max_characters} characters",
        )
    return text


def _wav_metadata(raw):
    try:
        import io
        import struct

        if (
            len(raw) < 12
            or raw[:4] != b"RIFF"
            or raw[8:12] != b"WAVE"
            or struct.unpack_from("<I", raw, 4)[0] + 8 != len(raw)
        ):
            raise ValueError
        data_size = None
        offset = 12
        while offset + 8 <= len(raw):
            chunk_id = raw[offset : offset + 4]
            chunk_size = struct.unpack_from("<I", raw, offset + 4)[0]
            chunk_end = offset + 8 + chunk_size
            if chunk_end > len(raw):
                raise ValueError
            if chunk_id == b"data":
                data_size = chunk_size
                break
            offset = chunk_end + (chunk_size & 1)
        if data_size is None:
            raise ValueError

        with wave.open(io.BytesIO(raw), "rb") as wav:
            if (
                wav.getcomptype() != "NONE"
                or wav.getsampwidth() != 2
                or wav.getnframes() <= 0
            ):
                raise ValueError
            frame_size = wav.getnchannels() * wav.getsampwidth()
            if data_size % frame_size:
                raise ValueError
            frames = wav.getnframes()
            decoded = wav.readframes(frames)
            if len(decoded) != frames * frame_size or wav.readframes(1):
                raise ValueError
            return {
                "duration_seconds": round(frames / wav.getframerate(), 3),
                "sample_rate_hz": wav.getframerate(),
                "channels": wav.getnchannels(),
                "frames": frames,
            }
    except (wave.Error, EOFError, ValueError, ZeroDivisionError):
        raise QualificationError(
            "invalid_response",
            "Gateway returned invalid or unsupported WAV audio",
            status=200,
        ) from None


def _base(operation, params, input_meta):
    return {
        "schema_version": "1.0",
        "operation": operation,
        "request": {"parameters": params, "input": input_meta},
        "http": {"status": None, "success": False},
        "elapsed_seconds": None,
        "error": {"classification": None, "api_code": None},
        "diagnostics": {
            "client_request_id": str(uuid.uuid4()),
            "server_request_id": None,
            "failure_stage": None,
            "troubleshooting": None,
            "gateway_logs": "not_available_via_public_api",
        },
        "response": {},
        "outcome": "fail",
        "technical_checks": [],
        "artifact": None,
    }


def _expect_api_error(report, expected):
    if expected is None:
        return
    status = report["http"]["status"]
    matched = (
        status is not None and status >= 400 and report["error"]["api_code"] == expected
    )
    report["expected_api_error"] = {"code": expected, "matched": matched}
    report["technical_checks"].append({"name": "expected_api_error", "passed": matched})
    report["outcome"] = "pass" if matched else "fail"
    if not matched and report["error"]["classification"] is None:
        report["error"]["classification"] = "expected_error_not_observed"
        report["message"] = f"expected API error {expected} was not returned"
        report["diagnostics"].update(
            {
                "failure_stage": "expectation",
                "troubleshooting": "Check whether the target configuration and request actually exercise the expected rejection.",
            }
        )


def _validate_stt_response(response, status):
    if not isinstance(response.get("text"), str) or not isinstance(
        response.get("language"), str
    ):
        raise QualificationError(
            "invalid_response",
            "Gateway response omitted required STT fields or used invalid field types",
            status=status,
        )
    for key in (
        "transcription",
        "detected_language",
        "source_language",
        "output_language",
    ):
        if key in response and not isinstance(response[key], str):
            raise QualificationError(
                "invalid_response",
                "Gateway returned an invalid STT field type",
                status=status,
            )
    if "translated" in response and not isinstance(response["translated"], bool):
        raise QualificationError(
            "invalid_response",
            "Gateway returned an invalid STT field type",
            status=status,
        )
    probability = response.get("language_probability")
    if "language_probability" in response and (
        not isinstance(probability, (int, float))
        or isinstance(probability, bool)
        or not 0 <= probability <= 1
    ):
        raise QualificationError(
            "invalid_response",
            "Gateway returned an invalid STT field type",
            status=status,
        )


def _validate_transform_response(response, status):
    required = {
        "original_text": str,
        "transformed_text": str,
        "options": dict,
        "model": (str, type(None)),
        "provider": (str, type(None)),
        "fallback_occurred": bool,
        "generated": bool,
    }
    if any(
        key not in response or not isinstance(response[key], kind)
        for key, kind in required.items()
    ):
        raise QualificationError(
            "invalid_response",
            "Gateway response omitted required transformation fields or used invalid field types",
            status=status,
        )
    options = response["options"]
    if "model" not in options:
        raise QualificationError(
            "invalid_response",
            "Gateway omitted the transformation model option",
            status=status,
        )
    expected = {
        "mode": str,
        "format": str,
        "target_language": str,
        "local_only": bool,
    }
    if any(not isinstance(options.get(key), kind) for key, kind in expected.items()):
        raise QualificationError(
            "invalid_response",
            "Gateway returned invalid transformation options",
            status=status,
        )
    if options.get("model") is not None and not isinstance(options["model"], str):
        raise QualificationError(
            "invalid_response",
            "Gateway returned invalid transformation options",
            status=status,
        )
    if (
        options["mode"] not in {"raw", "written", "polite", "diplomatic"}
        or options["format"] not in {"normal", "concise", "structured"}
        or options["target_language"] not in {"none", "en", "sv", "ru"}
    ):
        raise QualificationError(
            "invalid_response",
            "Gateway returned unsupported transformation options",
            status=status,
        )


def _execute(args):
    op = args.operation
    values = load_env()
    auth_mode = args.auth_mode
    origin, token = _origin(
        values,
        args.gateway_url,
        args.api_token_file if auth_mode == "configured" else None,
        require_token=auth_mode == "configured"
        and op not in {"health", "ready", "metrics"},
    )
    if auth_mode in {"missing", "none"} or op in {"health", "ready", "metrics"}:
        token = None
    _validate_output_paths(args)
    evidence_content = None
    extra_headers = {}
    method = "POST"
    if op in {"health", "ready", "metrics", "voices", "warmup"}:
        params = {"operations": args.operations} if op == "warmup" else {}
        input_meta = {}
        method = "POST" if op == "warmup" else "GET"
        paths = {
            "health": "/healthz",
            "ready": "/readyz",
            "metrics": "/metrics",
            "voices": "/v1/tts/voices",
            "warmup": "/v1/models/warmup",
        }
        if op == "warmup":
            body = json.dumps({"operations": args.operations}).encode()
            content_type = "application/json"
        else:
            body, content_type = None, None
        url, max_bytes = origin + paths[op], MAX_JSON_BYTES
        extra_headers = {}
    elif op == "stt":
        audio_path = args.audio
        if not audio_path.is_file() or audio_path.stat().st_size > MAX_STT_BYTES:
            raise QualificationError(
                "local_validation",
                "provide an existing audio file within the Gateway request limit",
            )
        body, content_type = _multipart(
            audio_path,
            args.source_language,
            args.output_language,
            args.model,
            timestamps=args.timestamps,
            stream=args.stream,
        )
        params = {
            "source_language": args.source_language,
            "output_language": args.output_language,
            "provider": args.provider,
            "model": args.model,
            "cloud_audio_consent": args.allow_cloud_audio,
            "timestamps": args.timestamps,
            "stream": args.stream,
        }
        input_meta = {"audio_bytes": audio_path.stat().st_size}
        url, max_bytes = origin + "/v1/stt/transcriptions", MAX_JSON_BYTES
        extra_headers = {
            "X-STT-Provider": args.provider,
            "X-Allow-Cloud-Audio": "true" if args.allow_cloud_audio else "false",
        }
    elif op == "transform":
        text = _input_text(args)
        if args.mode == "raw" and args.format != "normal":
            raise QualificationError(
                "local_validation", "raw mode requires normal formatting"
            )
        params = {
            "mode": args.mode,
            "format": args.format,
            "target_language": args.target_language,
            "model": args.model,
            "local_only": not args.allow_cloud,
        }
        input_meta = {"characters": len(text), "utf8_bytes": len(text.encode("utf-8"))}
        payload = {
            "text": text,
            "mode": args.mode,
            "format": args.format,
            "target_language": args.target_language,
            "local_only": not args.allow_cloud,
        }
        if args.model is not None:
            payload["model"] = args.model
        body, content_type = (
            json.dumps(payload, ensure_ascii=False).encode(),
            "application/json",
        )
        url, max_bytes = origin + "/v1/text/transformations", MAX_JSON_BYTES
        evidence_content = {"request_text": text}
    elif op == "tts":
        text = _input_text(args, 49152 if args.input_format == "ssml" else 10000)
        params = {
            "voice": args.voice,
            "language": args.language,
            "mode": args.mode,
            "input_format": args.input_format,
            "audio_processing": args.audio_processing,
        }
        input_meta = {"characters": len(text), "utf8_bytes": len(text.encode("utf-8"))}
        body = json.dumps(
            {
                "text": text,
                "voice": args.voice,
                "language": args.language,
                "mode": args.mode,
                "input_format": args.input_format,
                "audio_processing": args.audio_processing,
            },
            ensure_ascii=False,
        ).encode()
        if len(body) > MAX_TTS_REQUEST_BYTES:
            raise QualificationError(
                "local_validation", "TTS request exceeds the public API size limit"
            )
        content_type, url, max_bytes = (
            "application/json",
            origin + "/v1/tts/speech",
            MAX_TTS_BYTES,
        )
        evidence_content = {"request_text": text}

    report = _base(op, params, input_meta)
    report["request"]["target"] = origin
    report["request"]["auth_mode"] = auth_mode
    start = time.monotonic()
    try:
        if args.verbose or args.debug:
            print(
                f"request: {method} {url.removeprefix(origin)} operation={op}",
                file=sys.stderr,
                flush=True,
            )
        status, headers, raw = _request(
            url,
            token,
            body,
            content_type,
            args.timeout,
            max_bytes,
            extra_headers,
            method=method,
        )
        if args.verbose or args.debug:
            print(
                f"response: HTTP {status}; bytes={len(raw)}",
                file=sys.stderr,
                flush=True,
            )
        report["http"] = {"status": status, "success": status == 200}
        report["elapsed_seconds"] = round(time.monotonic() - start, 3)
        report["diagnostics"]["server_request_id"] = next(
            (
                headers.get(k)
                for k in ("X-Request-ID", "X-Correlation-ID", "Traceparent")
                if headers.get(k)
            ),
            None,
        )
        report["diagnostics"]["response_headers"] = _safe_headers(headers)
        report["diagnostics"]["failure_stage"] = "response_validation"
        if op == "metrics":
            if status != 200:
                raise _response_error(status, raw, headers)
            try:
                lines = raw.decode("utf-8").splitlines()
            except UnicodeDecodeError:
                raise QualificationError(
                    "invalid_response",
                    "Gateway returned invalid metrics text",
                    status=status,
                ) from None
            names = sorted(
                {
                    line.split(" ", 1)[0].split("{", 1)[0]
                    for line in lines
                    if line and not line.startswith("#")
                }
            )
            report["response"] = {
                "metadata": {"line_count": len(lines), "metric_names": names}
            }
            checks = [{"name": "metrics_text_valid", "passed": True}]
        elif op in {"health", "ready"}:
            response = _json_response(raw)
            expected = "alive" if op == "health" else "ready"
            passed = status == 200 and response.get("status") == expected
            if status != 200:
                raise _response_error(status, raw, headers)
            if not passed:
                raise QualificationError(
                    "invalid_response",
                    "Gateway health response did not match its contract",
                    status=status,
                )
            report["response"] = {"metadata": {"status": expected}}
            checks = [{"name": f"{op}_status", "passed": True}]
        elif op == "voices":
            if status != 200:
                raise _response_error(status, raw, headers)
            try:
                response = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise QualificationError(
                    "invalid_response", "Gateway returned malformed JSON", status=status
                ) from None
            if not isinstance(response, list) or any(
                not isinstance(item, dict) for item in response
            ):
                raise QualificationError(
                    "invalid_response",
                    "Gateway returned an invalid catalog",
                    status=status,
                )
            required = {"id": str, "languages": list, "streaming": bool}
            if any(
                any(
                    not isinstance(item.get(key), kind)
                    for key, kind in required.items()
                )
                or any(not isinstance(language, str) for language in item["languages"])
                for item in response
            ):
                raise QualificationError(
                    "invalid_response",
                    "Gateway catalog fields did not match the public contract",
                    status=status,
                )
            report["response"] = {"metadata": {"items": response}}
            checks = [{"name": f"{op}_catalog_valid", "passed": True}]
        elif op == "warmup":
            if status != 200:
                raise _response_error(status, raw, headers)
            response = _json_response(raw)
            results = response.get("results")
            valid_statuses = {
                "ready",
                "warming",
                "unavailable",
                "resource_unavailable",
                "overloaded",
                "timed_out",
                "not_attempted",
            }
            valid_ops = {"stt", "tts", "text_transform"}
            if (
                not isinstance(response.get("complete"), bool)
                or not isinstance(results, list)
                or not results
                or any(
                    not isinstance(item, dict)
                    or item.get("operation") not in valid_ops
                    or item.get("status") not in valid_statuses
                    for item in results
                )
            ):
                raise QualificationError(
                    "invalid_response",
                    "Gateway warmup response did not match its public contract",
                    status=status,
                )
            report["response"] = {"metadata": response}
            checks = [{"name": "warmup_complete", "passed": response["complete"]}]
        elif op == "stt":
            response = _json_response(raw)
            _validate_stt_response(response, status)
            provider = headers.get("X-Speech-Provider")
            report["response"] = {
                "provider": provider,
                "metadata": {
                    k: response[k]
                    for k in (
                        "detected_language",
                        "language",
                        "source_language",
                        "output_language",
                        "translated",
                        "language_probability",
                    )
                    if k in response
                },
            }
            evidence_content = {"transcript": response["text"]}
            checks = [
                {
                    "name": "transcription_text_nonempty",
                    "passed": bool(response["text"].strip()),
                },
                {
                    "name": "serving_provider_reported",
                    "passed": provider in {"local", "groq"},
                },
            ]
        elif op == "transform":
            response = _json_response(raw)
            _validate_transform_response(response, status)
            transformed = response.get("transformed_text")
            report["response"] = {
                "provider": response.get("provider"),
                "model": response.get("model"),
                "metadata": {
                    k: response[k]
                    for k in ("generated", "fallback_occurred")
                    if k in response
                },
            }
            prompt_sha256 = headers.get("X-Speech-Prompt-SHA256")
            if prompt_sha256 is not None:
                report["response"]["metadata"]["prompt_sha256"] = prompt_sha256
            evidence_content["transformed_text"] = transformed
            checks = [
                {
                    "name": "transformed_text_nonempty",
                    "passed": bool(transformed.strip()),
                },
                {
                    "name": "provenance_fields_present",
                    "passed": all(
                        k in response
                        for k in ("provider", "model", "generated", "fallback_occurred")
                    ),
                },
            ]
        else:
            wav = _wav_metadata(raw)
            report["response"] = {
                "metadata": {
                    "content_type": headers.get("Content-Type", "").split(";")[0]
                }
            }
            if headers.get("X-Speech-Provider") is not None:
                report["response"]["provider"] = headers.get("X-Speech-Provider")
            if headers.get("X-Speech-Model") is not None:
                report["response"]["model"] = headers.get("X-Speech-Model")
            report["artifact"] = {"kind": "wav", "bytes": len(raw), **wav}
            checks = [{"name": "valid_pcm16_wav", "passed": True}]
            report["technical_checks"] = checks
            if args.output:
                report["artifact"]["saved"] = False
                target = _write_output(args.output, raw)
                report["artifact"]["saved"] = True
                report["artifact"]["relative_path"] = os.path.relpath(target, ROOT)
        report["technical_checks"] = checks
        report["outcome"] = (
            "pass"
            if report["http"]["success"] and all(c["passed"] for c in checks)
            else "fail"
        )
        if report["outcome"] == "pass":
            report["diagnostics"]["failure_stage"] = None
        if args.evidence:
            _write_output(
                args.evidence,
                json.dumps(evidence_content, ensure_ascii=False).encode(),
                private=True,
            )
    except QualificationError as exc:
        if exc.status is not None:
            report["http"]["status"] = exc.status
        if report["elapsed_seconds"] is None:
            report["elapsed_seconds"] = round(time.monotonic() - start, 3)
        report["error"] = {
            "classification": exc.classification,
            "api_code": exc.api_code,
        }
        report["diagnostics"].update(
            {
                "server_request_id": next(
                    (
                        exc.response_headers.get(k)
                        for k in ("x-request-id", "x-correlation-id", "traceparent")
                        if exc.response_headers.get(k)
                    ),
                    report["diagnostics"]["server_request_id"],
                ),
                "failure_stage": exc.failure_stage
                or report["diagnostics"].get("failure_stage")
                or ("output" if exc.classification == "output_error" else "preflight"),
                "response_headers": exc.response_headers,
                "troubleshooting": _troubleshooting(exc.classification, exc.api_code),
            }
        )
        report["outcome"] = "fail"
        report["message"] = str(exc)
    return report


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    stt = sub.add_parser("stt", help="transcribe one audio file")
    stt.add_argument("--audio", type=Path, required=True)
    stt.add_argument(
        "--source-language", choices=("auto", "ru", "en", "sv"), default="auto"
    )
    stt.add_argument(
        "--output-language", choices=("auto", "ru", "en", "sv"), default="auto"
    )
    stt.add_argument("--provider", choices=("local", "groq"), default="local")
    stt.add_argument("--model", help="optional local STT model alias")
    stt.add_argument("--allow-cloud-audio", action="store_true")
    stt.add_argument(
        "--timestamps",
        action="store_true",
        help="request timestamps (currently unsupported by the Gateway)",
    )
    stt.add_argument(
        "--stream",
        action="store_true",
        help="request reserved streaming mode (currently unsupported by the Gateway)",
    )
    transform = sub.add_parser("transform", help="transform or translate text")
    tts = sub.add_parser("tts", help="synthesize one WAV")
    health = sub.add_parser("health", help="check unauthenticated Gateway liveness")
    ready = sub.add_parser("ready", help="check unauthenticated Gateway readiness")
    metrics = sub.add_parser(
        "metrics", help="summarize public Gateway Prometheus metrics"
    )
    voices = sub.add_parser("voices", help="list public TTS voice capabilities")
    warmup = sub.add_parser("warmup", help="explicitly warm configured operations")
    warmup.add_argument(
        "--operation",
        dest="operations",
        action="append",
        required=True,
        choices=("stt", "tts", "text_transform"),
        help="repeat to select multiple warmup operations",
    )
    for command in (transform, tts):
        group = command.add_mutually_exclusive_group()
        group.add_argument("--text")
        group.add_argument("--text-file", type=Path)
    transform.add_argument(
        "--mode", choices=("raw", "written", "polite", "diplomatic"), default="written"
    )
    transform.add_argument(
        "--format", choices=("normal", "concise", "structured"), default="normal"
    )
    transform.add_argument(
        "--target-language", choices=("none", "en", "sv", "ru"), default="none"
    )
    transform.add_argument("--model")
    transform.add_argument(
        "--allow-cloud",
        action="store_true",
        help="allow configured cloud routing; server policy still applies",
    )
    tts.add_argument("--voice", choices=("default",), default="default")
    tts.add_argument("--language", choices=("auto", "en", "ru", "sv"), default="auto")
    tts.add_argument(
        "--mode",
        choices=("quality", "fast", "auto", "high_quality", "extra_high_quality"),
        default="quality",
    )
    tts.add_argument("--input-format", choices=("text", "ssml"), default="text")
    tts.add_argument("--audio-processing", choices=("none", "gentle"), default="none")
    tts.add_argument("--output", type=Path)
    for command in (
        stt,
        transform,
        tts,
        health,
        ready,
        metrics,
        voices,
        warmup,
    ):
        command.add_argument(
            "--gateway-url",
            help="target HTTP(S) Gateway origin; non-loopback targets require HTTPS",
        )
        command.add_argument(
            "--api-token-file",
            type=Path,
            help="private token file under private/ (mode 0600)",
        )
        command.add_argument(
            "--auth-mode",
            choices=("configured", "none", "missing"),
            default="configured",
            help="none tests an intentionally unauthenticated target; missing is a negative probe requiring --expect-error unauthorized",
        )
        command.add_argument(
            "--verbose",
            action="store_true",
            help="show safe request progress on stderr",
        )
        command.add_argument(
            "--debug",
            action="store_true",
            help="show safe diagnostics and save bounded local logs under private/",
        )
        command.add_argument(
            "--timeout", type=float, default=600, help="client wait timeout in seconds"
        )
        command.add_argument(
            "--report", type=Path, help="exclusive-create JSON report under private/"
        )
        command.add_argument(
            "--evidence",
            type=Path,
            help="explicitly retain request/response text under private/",
        )
        command.add_argument(
            "--expect-error",
            help="pass only when the Gateway returns this API error code",
        )
    return parser


def _failure_report(args, error):
    if args.operation == "stt":
        params = {
            "source_language": args.source_language,
            "output_language": args.output_language,
            "provider": args.provider,
            "model": args.model,
            "cloud_audio_consent": args.allow_cloud_audio,
            "timestamps": args.timestamps,
            "stream": args.stream,
        }
    elif args.operation == "transform":
        params = {
            "mode": args.mode,
            "format": args.format,
            "target_language": args.target_language,
            "model": args.model,
            "local_only": not args.allow_cloud,
        }
    elif args.operation == "tts":
        params = {
            "voice": args.voice,
            "language": args.language,
            "mode": args.mode,
            "input_format": args.input_format,
            "audio_processing": args.audio_processing,
        }
    else:
        params = {"operations": args.operations} if args.operation == "warmup" else {}
    report = _base(args.operation, params, {})
    report["request"]["target"] = args.gateway_url or "configured_gateway"
    report["request"]["auth_mode"] = args.auth_mode
    report["error"] = {
        "classification": getattr(error, "classification", "local_validation"),
        "api_code": getattr(error, "api_code", None),
    }
    report["http"]["status"] = getattr(error, "status", None)
    report["message"] = (
        str(error)
        if isinstance(error, QualificationError)
        else "local input or configuration could not be read"
    )
    report["diagnostics"].update(
        {
            "failure_stage": getattr(error, "failure_stage", None)
            or (
                "output"
                if report["error"]["classification"] == "output_error"
                else "preflight"
            ),
            "troubleshooting": _troubleshooting(
                report["error"]["classification"], report["error"]["api_code"]
            ),
        }
    )
    return report


def _collect_debug_evidence(report, args, target, window_seconds):
    secret = None
    try:
        _, secret = _origin(
            load_env(),
            args.gateway_url,
            getattr(args, "api_token_file", None)
            if getattr(args, "auth_mode", "configured") == "configured"
            else None,
            require_token=False,
        )
    except (OSError, ValueError, QualificationError):
        pass
    try:
        path = diagnostics.save_debug_evidence(
            report,
            target=target,
            window_seconds=window_seconds,
            secrets=(secret,) if secret else (),
        )
    except OSError:
        report.setdefault("diagnostics", {})["local_debug_evidence"] = "save_failed"
        return None
    report.setdefault("diagnostics", {})["local_debug_evidence"] = path
    return path


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    if args.expect_error and not API_ERROR_CODE.fullmatch(args.expect_error):
        parser.error("--expect-error must be a lowercase API error code")
    if not math.isfinite(args.timeout) or args.timeout <= 0 or args.timeout > 3600:
        parser.error("--timeout must be greater than 0 and at most 3600 seconds")
    if getattr(args, "allow_cloud_audio", False) and args.provider != "groq":
        parser.error("--allow-cloud-audio is valid only with --provider groq")
    if (
        args.operation == "stt"
        and args.provider == "groq"
        and not args.allow_cloud_audio
    ):
        parser.error("Groq requires explicit --allow-cloud-audio consent")
    if args.operation == "stt" and args.provider == "groq" and args.model:
        parser.error("--model is supported only with the local STT provider")
    if args.auth_mode == "missing" and args.expect_error != "unauthorized":
        parser.error("--auth-mode missing requires --expect-error unauthorized")
    if args.auth_mode == "missing" and args.operation != "voices":
        parser.error(
            "missing-auth negative probes are limited to the read-only voices endpoint"
        )
    if args.auth_mode != "configured" and args.api_token_file is not None:
        parser.error("--api-token-file is valid only with --auth-mode configured")
    report_writable = args.report is not None
    if report_writable:
        try:
            _output_path(args.report, private=True)
        except QualificationError:
            report_writable = False
    try:
        report = _execute(args)
    except (OSError, QualificationError) as exc:
        report = _failure_report(args, exc)
    _expect_api_error(report, args.expect_error)
    debug_evidence_error = False
    if args.debug:
        debug_path = _collect_debug_evidence(
            report,
            args,
            report["request"].get("target", ""),
            math.ceil(report.get("elapsed_seconds") or 1),
        )
        if debug_path is None:
            debug_evidence_error = True
            print(
                "debug evidence could not be saved under private/",
                file=sys.stderr,
                flush=True,
            )
        else:
            print(f"debug evidence saved: {debug_path}", file=sys.stderr, flush=True)
    if report_writable:
        try:
            _write_output(
                args.report,
                json.dumps(report, ensure_ascii=False, indent=2).encode(),
                private=True,
            )
        except (OSError, QualificationError) as exc:
            message = (
                str(exc)
                if isinstance(exc, QualificationError)
                else "could not write private report"
            )
            print(
                f"FAIL {args.operation}: private report write failed: {message}; any previously written artifact remains",
                file=sys.stderr,
            )
            return EXIT_OUTPUT
    status = report["http"]["status"]
    elapsed = report["elapsed_seconds"]
    http_text = str(status) if status is not None else "N/A"
    elapsed_text = f"{elapsed}s" if elapsed is not None else "N/A"
    summary = f"{report['outcome'].upper()} {args.operation}: HTTP {http_text}; elapsed={elapsed_text}"
    if report.get("expected_api_error", {}).get("matched"):
        summary = (
            f"PASS {args.operation}: expected API error {args.expect_error}; "
            f"HTTP {http_text}; elapsed={elapsed_text}"
        )
    if report["error"]["classification"]:
        summary += f"; error={report['error']['classification']}"
    if report["error"].get("api_code"):
        summary += f"; api_code={report['error']['api_code']}"
    if report.get("message"):
        summary += f"; {report['message']}"
    if args.operation == "voices" and report["http"]["success"]:
        items = report.get("response", {}).get("metadata", {}).get("items", [])
        summary += f"; items={len(items)}"
    if args.operation == "warmup" and report.get("response", {}).get("metadata"):
        summary += "; " + ", ".join(
            f"{item['operation']}={item['status']}"
            for item in report["response"]["metadata"].get("results", [])
        )
    if report["outcome"] != "pass" and report["diagnostics"].get("troubleshooting"):
        print(
            f"guidance: {report['diagnostics']['troubleshooting']}",
            file=sys.stderr,
            flush=True,
        )
    if args.verbose or args.debug:
        print(
            f"diagnostics: request_id={report['diagnostics']['client_request_id']} "
            f"stage={report['diagnostics']['failure_stage'] or 'complete'} "
            f"server_request_id={report['diagnostics']['server_request_id'] or 'unavailable'}",
            file=sys.stderr,
            flush=True,
        )
        if args.debug and report["diagnostics"].get("response_headers"):
            print(
                f"response headers: {report['diagnostics']['response_headers']}",
                file=sys.stderr,
                flush=True,
            )
    print(summary)
    if debug_evidence_error:
        return EXIT_OUTPUT
    if report["outcome"] == "pass":
        return 0
    if report["error"]["classification"] == "output_error":
        return EXIT_OUTPUT
    if report["error"]["classification"] == "local_validation" or (
        report["error"]["classification"] == "authentication"
        and report["http"]["status"] is None
    ):
        return EXIT_INPUT
    return EXIT_REQUEST


if __name__ == "__main__":
    raise SystemExit(main())
