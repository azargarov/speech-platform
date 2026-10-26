"""Transcribe sample WAVs once and qualify local text transformations."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

from scripts import qualify
from scripts.api_smoke import MAX_STT_BYTES, _multipart

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ("en", "ru", "sv")
MODES = ("written", "polite", "diplomatic")
TEXT_PROVIDER = "host-ollama"
MAX_TRANSFORM_BYTES = 65536
EXIT_REQUEST = 1
EXIT_INPUT = 2
EXIT_OUTPUT = 3


class BatchError(ValueError):
    def __init__(self, classification, message, *, status=None, api_code=None):
        super().__init__(message)
        self.classification = classification
        self.status = status
        self.api_code = api_code


def _progress(message):
    print(message, file=sys.stderr, flush=True)


def discover_audio(audio_dir: Path | None = None) -> list[dict]:
    directory = ROOT / "samples" / "audio" if audio_dir is None else audio_dir
    if directory.is_symlink() or not directory.is_dir():
        raise BatchError("local_validation", "sample audio directory is unavailable")
    fixtures = []
    seen = set()
    for path in sorted(directory.glob("*.wav"), key=lambda item: item.name):
        parts = path.stem.split("-", 1)
        if len(parts) != 2 or parts[0] not in LANGUAGES or not parts[1]:
            raise BatchError(
                "local_validation", f"unsupported sample audio filename: {path.name}"
            )
        case_id = path.stem
        if case_id.casefold() in seen:
            raise BatchError("local_validation", "sample audio filenames collide")
        seen.add(case_id.casefold())
        if path.is_symlink() or not path.is_file():
            raise BatchError(
                "local_validation", f"sample audio is not a regular file: {path.name}"
            )
        try:
            size = path.stat().st_size
        except OSError:
            raise BatchError(
                "local_validation", f"sample audio cannot be read: {path.name}"
            ) from None
        if size <= 0 or size > MAX_STT_BYTES:
            raise BatchError(
                "local_validation",
                f"sample audio is empty or exceeds the STT request limit: {path.name}",
            )
        try:
            qualify._wav_metadata(path.read_bytes())
        except (OSError, qualify.QualificationError):
            raise BatchError(
                "local_validation", f"sample audio is invalid WAV: {path.name}"
            ) from None
        fixtures.append({"case_id": case_id, "language": parts[0], "path": path})
    if not fixtures:
        raise BatchError("local_validation", "no sample WAV fixtures were found")
    return fixtures


def output_names(language: str) -> list[dict]:
    if language not in LANGUAGES:
        raise BatchError("local_validation", "unsupported fixture language")
    outputs = [{"operation": "stt", "target_language": None, "name": "raw.txt"}]
    for mode in MODES:
        outputs.append(
            {"operation": mode, "target_language": "none", "name": f"{mode}.txt"}
        )
        for target in LANGUAGES:
            if target != language:
                outputs.append(
                    {
                        "operation": mode,
                        "target_language": target,
                        "name": f"{mode}-{target}.txt",
                    }
                )
    return outputs


def _prepare_outputs(fixtures, *, regenerate: bool):
    samples_dir = ROOT / "samples"
    output_dir = ROOT / "samples" / "transformed"
    if samples_dir.is_symlink() or output_dir.is_symlink():
        raise BatchError(
            "local_validation", "transformed output directory is a symlink"
        )
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    targets = {}
    for fixture in fixtures:
        case_dir = output_dir / fixture["case_id"]
        if case_dir.is_symlink():
            raise BatchError("local_validation", "case output directory is a symlink")
        case_dir.mkdir(mode=0o700, exist_ok=True)
        case_targets = {}
        for output in output_names(fixture["language"]):
            target = case_dir / output["name"]
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise BatchError(
                    "local_validation",
                    f"output is not a regular file: {output['name']}",
                )
            if target.exists() and not regenerate:
                raise BatchError(
                    "output_error",
                    f"output already exists for {fixture['case_id']}; use --regenerate",
                )
            case_targets[output["name"]] = target
        targets[fixture["case_id"]] = case_targets
    return targets


def _write_text(target: Path, text: str, *, regenerate: bool):
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        raise BatchError(
            "output_error", "response text could not be saved as UTF-8"
        ) from None
    fd = None
    temporary = None
    created_target = False
    completed = False
    try:
        if regenerate:
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
            )
            temporary = Path(temp_name)
        else:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            created_target = True
        stream = os.fdopen(fd, "wb")
        fd = None
        with stream:
            stream.write(data)
            stream.flush()
        if regenerate:
            os.replace(temporary, target)
        completed = True
        return target
    except FileExistsError:
        raise BatchError(
            "output_error", f"output already exists: {target.name}"
        ) from None
    except PermissionError:
        raise BatchError("output_error", "permission denied writing output") from None
    except OSError:
        raise BatchError("output_error", "could not write output file") from None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if not completed:
            cleanup = (
                temporary
                if temporary is not None
                else target
                if created_target
                else None
            )
            if cleanup is not None:
                try:
                    cleanup.unlink(missing_ok=True)
                except OSError:
                    pass


def _operation(operation, output, *, target_language=None):
    return {
        "operation": operation,
        "target_language": target_language,
        "output": output,
        "status": "not_attempted",
        "http_status": None,
        "provider": None,
        "model": None,
        "prompt_sha256": None,
        "elapsed_seconds": None,
        "error_classification": None,
        "api_code": None,
        "diagnostics": {
            "client_request_id": str(uuid.uuid4()),
            "server_request_id": None,
            "failure_stage": None,
            "response_headers": {},
            "troubleshooting": None,
            "gateway_logs": "not_available_via_public_api",
        },
    }


def _transcribe(fixture, token, origin, timeout):
    path = fixture["path"]
    body, content_type = _multipart(path, fixture["language"], fixture["language"])
    return qualify._request(
        origin + "/v1/stt/transcriptions",
        token,
        body,
        content_type,
        timeout,
        qualify.MAX_JSON_BYTES,
        {"X-STT-Provider": "local", "X-Allow-Cloud-Audio": "false"},
    )


def _transform(raw_text, mode, target_language, token, origin, timeout):
    if not raw_text.strip() or len(raw_text) > 10000:
        raise BatchError(
            "local_validation", "transcription is empty or exceeds text input limit"
        )
    payload = {
        "text": raw_text,
        "mode": mode,
        "format": "normal",
        "target_language": target_language,
        "local_only": True,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_TRANSFORM_BYTES:
        raise BatchError(
            "local_validation", "transformation request exceeds size limit"
        )
    status, headers, data = qualify._request(
        origin + "/v1/text/transformations",
        token,
        body,
        "application/json",
        timeout,
        qualify.MAX_JSON_BYTES,
    )
    if status != 200:
        raise BatchError(
            "http_error", f"transformation returned HTTP {status}", status=status
        )
    try:
        response = qualify._json_response(data)
        qualify._validate_transform_response(response, status)
    except qualify.QualificationError as exc:
        if exc.status is None:
            exc.status = status
        raise
    expected_options = {
        "mode": mode,
        "format": "normal",
        "target_language": target_language,
        "model": None,
        "local_only": True,
    }
    if response["original_text"] != raw_text or any(
        response["options"].get(key) != value for key, value in expected_options.items()
    ):
        raise BatchError(
            "invalid_response",
            "Gateway response did not match transformation request",
            status=status,
        )
    if response["provider"] != TEXT_PROVIDER or response["fallback_occurred"]:
        raise BatchError(
            "provider_mismatch",
            "transformation was not served by the local provider",
            status=status,
        )
    if not response["generated"] or not response["transformed_text"].strip():
        raise BatchError(
            "invalid_response",
            "Gateway returned no generated transformation",
            status=status,
        )
    return (
        status,
        response["provider"],
        response["model"],
        response["transformed_text"],
        headers.get("X-Speech-Prompt-SHA256"),
        qualify._safe_headers(headers),
    )


def _should_stop(error):
    status = getattr(error, "status", None)
    return (isinstance(status, int) and 400 <= status <= 599) or getattr(
        error, "classification", None
    ) in {
        "authentication",
        "authorization",
        "connection",
        "timeout",
        "provider_mismatch",
        "output_error",
    }


def _record_failure(result, error):
    result["status"] = "fail"
    status = getattr(error, "status", None)
    if status is not None or result["http_status"] is None:
        result["http_status"] = status
    result["error_classification"] = getattr(
        error, "classification", "local_validation"
    )
    result["api_code"] = getattr(error, "api_code", None)
    headers = getattr(error, "response_headers", {})
    result["diagnostics"].update(
        {
            "failure_stage": getattr(error, "failure_stage", None)
            or "response_validation",
            "response_headers": headers,
            "server_request_id": next(
                (
                    headers.get(k)
                    for k in ("x-request-id", "x-correlation-id", "traceparent")
                    if headers.get(k)
                ),
                None,
            ),
            "troubleshooting": qualify._troubleshooting(
                result["error_classification"], result["api_code"]
            ),
        }
    )


def run(args):
    started = time.monotonic()
    report = {
        "schema_version": "1.0",
        "operation": "batch_stt_text_transformations",
        "routing": {
            "stt_provider": "local",
            "cloud_audio_consent": False,
            "text_local_only": True,
            "text_cloud_authorized": False,
            "text_provider_expected": TEXT_PROVIDER,
        },
        "target": None,
        "diagnostics": {
            "gateway_logs": "not_available_via_public_api",
            "request_correlation": "server correlation headers recorded only when returned",
        },
        "cases": [],
        "operations_attempted": 0,
        "operations_succeeded": 0,
        "operations_failed": 0,
        "missing_outputs": [],
        "error": None,
    }
    fixtures = []
    targets = {}
    try:
        fixtures = discover_audio()
        if args.case:
            fixtures = [
                fixture for fixture in fixtures if fixture["case_id"] == args.case
            ]
            if not fixtures:
                raise BatchError(
                    "local_validation", "requested sample case was not found"
                )
        targets = _prepare_outputs(fixtures, regenerate=args.regenerate)
        env = qualify.load_env()
        origin, token = qualify._origin(env, args.gateway_url, args.api_token_file)
        report["target"] = origin
        if args.verbose:
            _progress(
                f"target={origin}; timeout={args.timeout:g}s; STT=local; cloud_audio=false; text_local_only=true"
            )
        _progress(
            f"batch: {len(fixtures)} cases; 1 STT + 9 local-only transformations per case"
        )
        stop = False
        for position, fixture in enumerate(fixtures, 1):
            case = {
                "case_id": fixture["case_id"],
                "language": fixture["language"],
                "audio": fixture["path"].name,
                "operations": [],
            }
            report["cases"].append(case)
            _progress(f"[{position}/{len(fixtures)}] {fixture['case_id']}")
            stt_result = _operation("stt", f"{fixture['case_id']}/raw.txt")
            case["operations"].append(stt_result)
            report["operations_attempted"] += 1
            started_op = time.monotonic()
            _progress(f"{fixture['case_id']}: STT starting (provider=local)")
            if args.debug:
                _progress(
                    f"{fixture['case_id']}: STT request_id={stt_result['diagnostics']['client_request_id']}"
                )
            try:
                status, headers, data = _transcribe(
                    fixture, token, origin, args.timeout
                )
                stt_result["http_status"] = status
                stt_result["diagnostics"]["response_headers"] = qualify._safe_headers(
                    headers
                )
                stt_result["diagnostics"]["server_request_id"] = next(
                    (
                        headers.get(k)
                        for k in ("X-Request-ID", "X-Correlation-ID", "Traceparent")
                        if headers.get(k)
                    ),
                    None,
                )
                if args.debug:
                    _progress(
                        f"{fixture['case_id']}: STT response_headers={stt_result['diagnostics']['response_headers']}"
                    )
                stt_result["elapsed_seconds"] = round(time.monotonic() - started_op, 3)
                if status != 200:
                    raise BatchError(
                        "http_error", f"STT returned HTTP {status}", status=status
                    )
                response = qualify._json_response(data)
                qualify._validate_stt_response(response, status)
                provider = headers.get("X-Speech-Provider")
                stt_result["provider"] = provider
                if provider != "local":
                    raise BatchError(
                        "provider_mismatch",
                        "STT serving provider was not local",
                        status=status,
                    )
                raw_text = response["text"]
                if not raw_text.strip():
                    raise BatchError(
                        "invalid_response",
                        "Gateway returned empty transcription",
                        status=status,
                    )
                _write_text(
                    targets[fixture["case_id"]]["raw.txt"],
                    raw_text,
                    regenerate=args.regenerate,
                )
                stt_result["status"] = "pass"
                report["operations_succeeded"] += 1
                _progress(
                    f"{fixture['case_id']}: STT complete ({stt_result['elapsed_seconds']:.3f}s)"
                )
            except KeyboardInterrupt:
                error = BatchError("interrupted", "operation interrupted")
                stt_result["elapsed_seconds"] = round(time.monotonic() - started_op, 3)
                _record_failure(stt_result, error)
                report["operations_failed"] += 1
                report["error"] = {
                    "classification": "interrupted",
                    "case_id": fixture["case_id"],
                }
                _progress(
                    f"{fixture['case_id']}: STT interrupted ({stt_result['elapsed_seconds']:.3f}s)"
                )
                break
            except (BatchError, qualify.QualificationError, OSError) as exc:
                stt_result["elapsed_seconds"] = round(time.monotonic() - started_op, 3)
                _record_failure(stt_result, exc)
                report["operations_failed"] += 1
                _progress(
                    f"{fixture['case_id']}: STT failed ({stt_result['error_classification']}; api_code={stt_result['api_code'] or 'N/A'}; {stt_result['elapsed_seconds']:.3f}s)"
                )
                if _should_stop(exc):
                    report["error"] = {
                        "classification": stt_result["error_classification"],
                        "case_id": fixture["case_id"],
                    }
                    stop = True
            if stt_result["status"] != "pass":
                if stop:
                    break
                continue

            raw_text = response["text"]
            for mode in MODES:
                targets_for_mode = [
                    "none",
                    *[lang for lang in LANGUAGES if lang != fixture["language"]],
                ]
                for target_language in targets_for_mode:
                    name = (
                        f"{mode}.txt"
                        if target_language == "none"
                        else f"{mode}-{target_language}.txt"
                    )
                    result = _operation(
                        mode,
                        f"{fixture['case_id']}/{name}",
                        target_language=target_language,
                    )
                    case["operations"].append(result)
                    report["operations_attempted"] += 1
                    started_op = time.monotonic()
                    target_label = (
                        fixture["language"]
                        if target_language == "none"
                        else target_language
                    )
                    _progress(
                        f"{fixture['case_id']}: {mode} → {target_label} starting (local_only=true)"
                    )
                    if args.debug:
                        _progress(
                            f"{fixture['case_id']}: {mode} request_id={result['diagnostics']['client_request_id']}"
                        )
                    try:
                        (
                            status,
                            provider,
                            model,
                            transformed,
                            prompt_sha256,
                            safe_headers,
                        ) = _transform(
                            raw_text,
                            mode,
                            target_language,
                            token,
                            origin,
                            args.timeout,
                        )
                        result["http_status"] = status
                        result["provider"] = provider
                        result["model"] = model
                        result["prompt_sha256"] = prompt_sha256
                        result["diagnostics"]["response_headers"] = safe_headers
                        result["diagnostics"]["server_request_id"] = next(
                            (
                                safe_headers.get(k.lower())
                                for k in (
                                    "X-Request-ID",
                                    "X-Correlation-ID",
                                    "Traceparent",
                                )
                                if safe_headers.get(k.lower())
                            ),
                            None,
                        )
                        if args.debug:
                            _progress(
                                f"{fixture['case_id']}: {mode} response_headers={safe_headers}"
                            )
                        result["elapsed_seconds"] = round(
                            time.monotonic() - started_op, 3
                        )
                        _write_text(
                            targets[fixture["case_id"]][name],
                            transformed,
                            regenerate=args.regenerate,
                        )
                        result["status"] = "pass"
                        report["operations_succeeded"] += 1
                        _progress(
                            f"{fixture['case_id']}: {mode} → {target_label} complete ({result['elapsed_seconds']:.3f}s; {provider}/{model or 'model unavailable'})"
                        )
                    except KeyboardInterrupt:
                        error = BatchError("interrupted", "operation interrupted")
                        result["elapsed_seconds"] = round(
                            time.monotonic() - started_op, 3
                        )
                        _record_failure(result, error)
                        report["operations_failed"] += 1
                        report["error"] = {
                            "classification": "interrupted",
                            "case_id": fixture["case_id"],
                            "operation": mode,
                        }
                        _progress(
                            f"{fixture['case_id']}: {mode} → {target_label} interrupted ({result['elapsed_seconds']:.3f}s)"
                        )
                        stop = True
                        break
                    except (BatchError, qualify.QualificationError, OSError) as exc:
                        result["elapsed_seconds"] = round(
                            time.monotonic() - started_op, 3
                        )
                        _record_failure(result, exc)
                        report["operations_failed"] += 1
                        _progress(
                            f"{fixture['case_id']}: {mode} → {target_label} failed ({result['error_classification']}; api_code={result['api_code'] or 'N/A'}; {result['elapsed_seconds']:.3f}s)"
                        )
                        if _should_stop(exc):
                            report["error"] = {
                                "classification": result["error_classification"],
                                "case_id": fixture["case_id"],
                                "operation": mode,
                            }
                            stop = True
                            break
                if stop:
                    break
            if stop:
                break
    except (BatchError, qualify.QualificationError, OSError) as exc:
        report["error"] = {
            "classification": getattr(exc, "classification", "local_validation"),
            "api_code": getattr(exc, "api_code", None),
            "http_status": getattr(exc, "status", None),
            "message": str(exc)
            if isinstance(exc, (BatchError, qualify.QualificationError))
            else "input or configuration could not be read",
        }
        report["diagnostics"].update(
            {
                "failure_stage": getattr(exc, "failure_stage", None) or "preflight",
                "response_headers": getattr(exc, "response_headers", {}),
                "troubleshooting": qualify._troubleshooting(
                    report["error"]["classification"], report["error"]["api_code"]
                ),
            }
        )
    except KeyboardInterrupt:
        report["error"] = {"classification": "interrupted"}
        report["diagnostics"].update(
            {
                "failure_stage": "interrupted",
                "troubleshooting": "The sequence stopped without retry; inspect completed outputs before rerunning.",
            }
        )
        _progress("batch interrupted")

    for fixture in fixtures:
        for output in output_names(fixture["language"]):
            target = (
                ROOT / "samples" / "transformed" / fixture["case_id"] / output["name"]
            )
            if not target.is_file():
                report["missing_outputs"].append(str(target.relative_to(ROOT)))
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    report["outcome"] = (
        "pass"
        if fixtures
        and report["operations_failed"] == 0
        and report["operations_succeeded"] == len(fixtures) * 10
        else "fail"
    )
    _progress(
        f"batch finished: {report['operations_succeeded']} succeeded, "
        f"{report['operations_failed']} failed; total {report['elapsed_seconds']:.3f}s"
    )
    return report


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="run one fixture, for example en-polite")
    parser.add_argument(
        "--regenerate", action="store_true", help="atomically replace expected outputs"
    )
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument(
        "--gateway-url",
        help="target Gateway origin; non-loopback targets require HTTPS",
    )
    parser.add_argument(
        "--api-token-file",
        type=Path,
        help="private token file under private/ (mode 0600)",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="show safe request progress"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="show diagnostics and save bounded local logs under private/",
    )
    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0 or args.timeout > 3600:
        parser.error("--timeout must be greater than 0 and at most 3600 seconds")
    report = run(args)
    if args.debug:
        evidence = qualify._collect_debug_evidence(
            report,
            args,
            report.get("target") or args.gateway_url or "",
            report.get("elapsed_seconds") or 1,
        )
        if evidence is None:
            _progress("debug evidence could not be saved under private/")
            return EXIT_OUTPUT
        _progress(f"debug evidence saved: {evidence}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["outcome"] == "pass":
        return 0
    classification = (report.get("error") or {}).get("classification")
    if classification == "output_error":
        return EXIT_OUTPUT
    if classification == "local_validation":
        return EXIT_INPUT
    if classification == "interrupted":
        return 130
    return EXIT_REQUEST


if __name__ == "__main__":
    raise SystemExit(main())
