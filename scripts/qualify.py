"""Exercise one authenticated public SpeechPlatform Gateway operation."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
import time
import wave
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from scripts.api_smoke import MAX_STT_BYTES, MAX_TTS_BYTES, _multipart
from scripts.preflight import ROOT, load_env

MAX_JSON_BYTES = 2 * 1024 * 1024
EXIT_REQUEST = 1
EXIT_INPUT = 2
EXIT_OUTPUT = 3


class QualificationError(ValueError):
    def __init__(
        self, classification: str, message: str, *, status=None, api_code=None
    ):
        super().__init__(message)
        self.classification = classification
        self.status = status
        self.api_code = api_code


def _origin(values):
    origin = values.get(
        "SPEECH_API_URL", f"http://127.0.0.1:{values.get('SPEECH_PORT', '')}"
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
    if len(values.get("SPEECH_API_TOKEN", "")) < 32:
        raise QualificationError(
            "authentication", "SPEECH_API_TOKEN is missing or too short"
        )
    return origin, values["SPEECH_API_TOKEN"]


def _private_path(path):
    target = path.absolute()
    private_root = ROOT / "private"
    if private_root.is_symlink():
        raise QualificationError(
            "local_validation", "private output directory must not be a symlink"
        )
    private = private_root.resolve()
    canonical = target.resolve(strict=False)
    if not canonical.is_relative_to(private) or not target.parent.is_dir():
        raise QualificationError(
            "local_validation",
            "evidence and WAV output paths must be under an existing private/ directory",
        )
    if target.exists() or target.is_symlink():
        raise QualificationError(
            "local_validation", "output already exists; choose a new private path"
        )
    return canonical


def _validate_output_paths(args):
    paths = [
        path
        for path in (
            getattr(args, "report", None),
            getattr(args, "evidence", None),
            getattr(args, "output", None),
        )
        if path is not None
    ]
    canonical = [_private_path(path) for path in paths]
    if len(set(canonical)) != len(canonical):
        raise QualificationError(
            "local_validation",
            "report, evidence, and audio outputs need different paths",
        )


def _write_private(path, data):
    try:
        target = _private_path(path)
    except QualificationError:
        raise QualificationError(
            "output_error", "private output destination became unavailable"
        ) from None
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise QualificationError(
            "output_error", "private output already exists"
        ) from None
    except OSError:
        raise QualificationError(
            "output_error", "could not create private output"
        ) from None
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
    except OSError:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            raise QualificationError(
                "output_error", "private output write failed; a partial file may remain"
            ) from None
        raise QualificationError(
            "output_error", "private output write failed; partial file removed"
        ) from None
    return target


def _response_error(status, raw):
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
        classification, f"Gateway returned HTTP {status}", status=status, api_code=code
    )


def _request(url, token, body, content_type, timeout, max_bytes, extra_headers=None):
    request_headers = {"Authorization": f"Bearer {token}", "Content-Type": content_type}
    request_headers.update(extra_headers or {})
    request = Request(url, data=body, headers=request_headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise QualificationError(
                    "invalid_response",
                    "Gateway response exceeded the client size limit",
                    status=response.status,
                )
            return response.status, response.headers, data
    except HTTPError as exc:
        raw = exc.read(min(max_bytes, 65536))
        raise _response_error(exc.code, raw) from None
    except TimeoutError:
        raise QualificationError("timeout", "Gateway request timed out") from None
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise QualificationError("timeout", "Gateway request timed out") from None
        raise QualificationError(
            "connection", "Gateway request could not connect"
        ) from None
    except OSError:
        raise QualificationError(
            "connection", "Gateway request could not connect"
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


def _input_text(args):
    if args.text_file:
        text = args.text_file.read_text(encoding="utf-8")
    elif args.text is not None:
        text = args.text
    else:
        text = sys.stdin.read(10001)
    if not text or len(text) > 10000:
        raise QualificationError(
            "local_validation", "text input must contain 1 to 10000 characters"
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
        "response": {},
        "outcome": "fail",
        "technical_checks": [],
        "artifact": None,
    }


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
    values = load_env()
    origin, token = _origin(values)
    _validate_output_paths(args)
    op = args.operation
    evidence_content = None
    extra_headers = {}
    if op == "stt":
        audio_path = args.audio
        if not audio_path.is_file() or audio_path.stat().st_size > MAX_STT_BYTES:
            raise QualificationError(
                "local_validation",
                "provide an existing audio file within the Gateway request limit",
            )
        body, content_type = _multipart(
            audio_path, args.source_language, args.output_language
        )
        params = {
            "source_language": args.source_language,
            "output_language": args.output_language,
            "provider": args.provider,
            "cloud_audio_consent": args.allow_cloud_audio,
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
            "model": args.model,
            "local_only": not args.allow_cloud,
        }
        body, content_type = (
            json.dumps(payload, ensure_ascii=False).encode(),
            "application/json",
        )
        url, max_bytes = origin + "/v1/text/transformations", MAX_JSON_BYTES
        evidence_content = {"request_text": text}
    else:
        text = _input_text(args)
        params = {
            "language": args.language,
            "mode": args.mode,
            "input_format": "text",
            "audio_processing": args.audio_processing,
        }
        input_meta = {"characters": len(text), "utf8_bytes": len(text.encode("utf-8"))}
        body = json.dumps(
            {
                "text": text,
                "language": args.language,
                "mode": args.mode,
                "input_format": "text",
                "audio_processing": args.audio_processing,
            },
            ensure_ascii=False,
        ).encode()
        content_type, url, max_bytes = (
            "application/json",
            origin + "/v1/tts/speech",
            MAX_TTS_BYTES,
        )
        evidence_content = {"request_text": text}

    report = _base(op, params, input_meta)
    start = time.monotonic()
    try:
        status, headers, raw = _request(
            url, token, body, content_type, args.timeout, max_bytes, extra_headers
        )
        report["http"] = {"status": status, "success": status == 200}
        report["elapsed_seconds"] = round(time.monotonic() - start, 3)
        if op == "stt":
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
            report["artifact"] = {"kind": "wav", "bytes": len(raw), **wav}
            checks = [{"name": "valid_pcm16_wav", "passed": True}]
            report["technical_checks"] = checks
            if args.output:
                report["artifact"]["saved"] = False
                target = _write_private(args.output, raw)
                report["artifact"]["saved"] = True
                report["artifact"]["relative_path"] = str(target.relative_to(ROOT))
        report["technical_checks"] = checks
        report["outcome"] = (
            "pass"
            if report["http"]["success"] and all(c["passed"] for c in checks)
            else "fail"
        )
        if args.evidence:
            _write_private(
                args.evidence, json.dumps(evidence_content, ensure_ascii=False).encode()
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
    stt.add_argument("--allow-cloud-audio", action="store_true")
    transform = sub.add_parser("transform", help="transform or translate text")
    tts = sub.add_parser("tts", help="synthesize one WAV")
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
    tts.add_argument("--language", choices=("auto", "en", "ru", "sv"), default="auto")
    tts.add_argument(
        "--mode",
        choices=("quality", "fast", "auto", "high_quality", "extra_high_quality"),
        default="quality",
    )
    tts.add_argument("--audio-processing", choices=("none", "gentle"), default="none")
    tts.add_argument("--output", type=Path)
    for command in (stt, transform, tts):
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
    return parser


def _failure_report(args, error):
    if args.operation == "stt":
        params = {
            "source_language": args.source_language,
            "output_language": args.output_language,
            "provider": args.provider,
            "cloud_audio_consent": args.allow_cloud_audio,
        }
    elif args.operation == "transform":
        params = {
            "mode": args.mode,
            "format": args.format,
            "target_language": args.target_language,
            "model": args.model,
            "local_only": not args.allow_cloud,
        }
    else:
        params = {
            "language": args.language,
            "mode": args.mode,
            "input_format": "text",
            "audio_processing": args.audio_processing,
        }
    report = _base(args.operation, params, {})
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
    return report


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    if args.timeout <= 0 or args.timeout > 3600:
        parser.error("--timeout must be greater than 0 and at most 3600 seconds")
    if getattr(args, "allow_cloud_audio", False) and args.provider != "groq":
        parser.error("--allow-cloud-audio is valid only with --provider groq")
    if (
        args.operation == "stt"
        and args.provider == "groq"
        and not args.allow_cloud_audio
    ):
        parser.error("Groq requires explicit --allow-cloud-audio consent")
    try:
        report = _execute(args)
    except (OSError, QualificationError) as exc:
        report = _failure_report(args, exc)
    if args.report:
        try:
            _write_private(
                args.report, json.dumps(report, ensure_ascii=False, indent=2).encode()
            )
        except (OSError, QualificationError):
            print(
                f"FAIL {args.operation}: private report write failed; any previously written artifact remains",
                file=sys.stderr,
            )
            return EXIT_OUTPUT
    summary = f"{report['outcome'].upper()} {args.operation}: HTTP {report['http']['status']}; elapsed={report['elapsed_seconds']}s"
    if report["error"]["classification"]:
        summary += f"; error={report['error']['classification']}"
    print(summary)
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
