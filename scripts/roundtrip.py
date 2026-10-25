"""Qualify local public-Gateway TTS-to-STT round trips for text fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from scripts import qualify
from scripts.api_smoke import MAX_STT_BYTES, MAX_TTS_BYTES, _multipart

ROOT = Path(__file__).resolve().parents[1]
TEXT_DIR = ROOT / "samples" / "text"
AUDIO_DIR = ROOT / "samples" / "audio"
LANGUAGES = {"en", "ru", "sv"}
CASE_NAME = re.compile(r"^(?P<language>[a-z]{2})-(?P<case>[a-z0-9]+(?:-[a-z0-9]+)*)$")
EXIT_REQUEST = 1
EXIT_INPUT = 2
EXIT_OUTPUT = 3
NORMALIZATION_VERSION = "speechplatform-roundtrip-text-v1"


class RoundtripError(ValueError):
    def __init__(self, classification, message, *, status=None, api_code=None):
        super().__init__(message)
        self.classification = classification
        self.status = status
        self.api_code = api_code


def normalize(text: str) -> str:
    """NFC, casefold, replace Unicode punctuation with spaces, collapse space."""
    text = unicodedata.normalize("NFC", text).casefold()
    text = "".join(
        " " if unicodedata.category(char).startswith("P") else char for char in text
    )
    return " ".join(text.split())


def edit_distance(reference, hypothesis) -> int:
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for row, ref_char in enumerate(reference, 1):
        current = [row]
        for column, hyp_char in enumerate(hypothesis, 1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (ref_char != hyp_char),
                )
            )
        previous = current
    return previous[-1]


def metrics(reference: str, hypothesis: str) -> dict:
    ref = normalize(reference)
    hyp = normalize(hypothesis)
    words = ref.split()
    if not words or not ref:
        raise RoundtripError("local_validation", "reference has no measurable text")
    return {
        "normalization": {
            "version": NORMALIZATION_VERSION,
            "unicode": "NFC",
            "case": "casefold",
            "punctuation": "replace_with_space",
            "whitespace": "collapse",
        },
        "wer": edit_distance(words, hyp.split()) / len(words),
        "cer": edit_distance(ref, hyp) / len(ref),
        "reference_words": len(words),
        "reference_characters": len(ref),
    }


def discover_fixtures(text_dir: Path | None = None) -> list[dict]:
    if text_dir is None:
        text_dir = TEXT_DIR
    if not text_dir.is_dir():
        raise RoundtripError("local_validation", "fixture directory does not exist")
    if text_dir.is_symlink():
        raise RoundtripError(
            "local_validation", "fixture directory must not be a symlink"
        )
    fixtures = []
    seen = set()
    for path in sorted(text_dir.glob("*.txt"), key=lambda item: item.name):
        match = CASE_NAME.fullmatch(path.stem)
        if match is None or match.group("language") not in LANGUAGES:
            raise RoundtripError(
                "local_validation",
                f"unsupported or ambiguous fixture name: {path.name}",
            )
        case_id = path.stem
        identity = unicodedata.normalize("NFC", case_id).casefold()
        if identity in seen:
            raise RoundtripError(
                "local_validation", "fixture names collide after normalization"
            )
        seen.add(identity)
        if path.is_symlink() or not path.is_file():
            raise RoundtripError(
                "local_validation", f"fixture is not a regular file: {path.name}"
            )
        try:
            if path.stat().st_size > 40000:
                raise RoundtripError(
                    "local_validation",
                    f"fixture exceeds the text input limit: {path.name}",
                )
            raw = path.read_bytes()
            reference = raw.decode("utf-8")
        except RoundtripError:
            raise
        except (OSError, UnicodeDecodeError):
            raise RoundtripError(
                "local_validation", f"fixture is unreadable UTF-8: {path.name}"
            ) from None
        if not reference.strip() or len(reference) > 10000 or not normalize(reference):
            raise RoundtripError(
                "local_validation",
                f"fixture must contain 1 to 10000 measurable characters: {path.name}",
            )
        fixtures.append(
            {
                "case_id": case_id,
                "language": match.group("language"),
                "path": path,
                "reference": reference,
                "reference_sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    if not fixtures:
        raise RoundtripError("local_validation", "no text fixtures were found")
    return fixtures


def _output_targets(fixtures, output_dir: Path, *, regenerate: bool, report_path):
    directory = output_dir.expanduser().absolute()
    if not directory.is_dir():
        raise RoundtripError(
            "local_validation", "audio output directory must already exist"
        )
    directory = directory.resolve()
    targets = []
    for fixture in fixtures:
        target = directory / f"{fixture['case_id']}.wav"
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise RoundtripError(
                "local_validation",
                f"audio destination is not a regular file: {target.name}",
            )
        if target.exists() and not regenerate:
            raise RoundtripError(
                "local_validation",
                f"generated audio already exists: {target.name}; use --regenerate to replace it",
            )
        targets.append(target)
    canonical = [target.resolve(strict=False) for target in targets]
    if len(set(canonical)) != len(canonical):
        raise RoundtripError("local_validation", "generated audio paths collide")
    if report_path:
        report = qualify._output_path(report_path, private=True)
        if report in set(canonical):
            raise RoundtripError(
                "local_validation", "report path collides with generated audio"
            )
    return directory, targets


def _publish_audio(target: Path, data: bytes, *, regenerate: bool):
    fd = None
    temporary = None
    created_target = False
    completed = False
    failure = None
    interrupted = False
    cleanup_failed = False
    try:
        if regenerate:
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{target.stem}.", suffix=".tmp", dir=target.parent
            )
            temporary = Path(temporary_name)
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
    except FileExistsError:
        failure = RoundtripError(
            "output_error", f"generated audio already exists: {target.name}"
        )
    except PermissionError:
        failure = RoundtripError(
            "output_error", "permission denied writing generated audio"
        )
    except OSError:
        failure = RoundtripError("output_error", "could not publish generated audio")
    except KeyboardInterrupt:
        interrupted = True
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                cleanup_failed = True
        try:
            if created_target and not completed:
                target.unlink(missing_ok=True)
        except OSError:
            cleanup_failed = True
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                cleanup_failed = True
    if interrupted:
        if cleanup_failed:
            raise RoundtripError(
                "output_error",
                "interruption occurred; a partial or temporary file may remain",
            ) from None
        raise KeyboardInterrupt
    if failure is not None:
        if cleanup_failed:
            raise RoundtripError(
                "output_error", f"{failure}; a partial or temporary file may remain"
            ) from None
        raise failure from None
    return target


def _stage():
    return {
        "status": "not_run",
        "http_status": None,
        "elapsed_seconds": None,
        "provider": None,
        "metadata": {},
        "error": None,
    }


def _git_state():
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
            timeout=2,
        )
        changes = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    commit = revision.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        return None, None
    return commit, bool(changes.stdout.strip())


def _record_error(stage, error, status=None):
    stage["status"] = "fail"
    stage["http_status"] = (
        status if status is not None else getattr(error, "status", None)
    )
    stage["error"] = {
        "classification": getattr(error, "classification", "local_validation"),
        "api_code": getattr(error, "api_code", None),
        "message": str(error)
        if isinstance(error, (RoundtripError, qualify.QualificationError))
        else "operation failed",
    }


def _progress(message):
    print(message, file=sys.stderr, flush=True)


def _should_stop(error):
    return getattr(error, "classification", None) in {
        "authentication",
        "authorization",
        "connection",
        "timeout",
        "output_error",
        "provider_mismatch",
    } or getattr(error, "status", None) in {429, 500, 502, 503, 504}


def _run_case(fixture, target, origin, token, args, position, total):
    prefix = f"[{position}/{total}] {fixture['case_id']}"
    case = {
        "case_id": fixture["case_id"],
        "language": fixture["language"],
        "reference": {
            "file": f"samples/text/{fixture['path'].name}",
            "sha256": fixture["reference_sha256"],
            "text": fixture["reference"],
        },
        "audio": {"file": target.name, "sha256": None, "wav": None},
        "tts": _stage(),
        "stt": _stage(),
        "transcription": None,
        "metrics": None,
        "technical_status": "FAIL",
        "quality_status": "NOT_MEASURED",
        "human_review_status": "NOT_REVIEWED",
    }
    tts_status = None
    started = time.monotonic()
    try:
        body = json.dumps(
            {
                "text": fixture["reference"],
                "language": fixture["language"],
                "mode": args.tts_mode,
                "input_format": "text",
                "audio_processing": "none",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        _progress(f"{prefix}: TTS starting")
        tts_status, headers, audio = qualify._request(
            origin + "/v1/tts/speech",
            token,
            body,
            "application/json",
            args.timeout,
            MAX_TTS_BYTES,
        )
        case["tts"]["http_status"] = tts_status
        case["tts"]["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if tts_status != 200:
            raise RoundtripError(
                "http_error", f"TTS returned HTTP {tts_status}", status=tts_status
            )
        wav = qualify._wav_metadata(audio)
        case["tts"]["status"] = "pass"
        case["tts"]["provider"] = headers.get("X-Speech-Provider")
        case["tts"]["metadata"] = {
            "content_type": headers.get("Content-Type", "").split(";")[0]
        }
        target = _publish_audio(target, audio, regenerate=args.regenerate)
        case["audio"].update({"sha256": hashlib.sha256(audio).hexdigest(), "wav": wav})
        _progress(f"{prefix}: TTS complete ({case['tts']['elapsed_seconds']:.3f}s)")
    except (RoundtripError, qualify.QualificationError, OSError) as exc:
        if case["tts"]["elapsed_seconds"] is None:
            case["tts"]["elapsed_seconds"] = round(time.monotonic() - started, 3)
        _record_error(case["tts"], exc, tts_status)
        case["error_classification"] = case["tts"]["error"]["classification"]
        _progress(
            f"{prefix}: TTS failed ({case['tts']['error']['classification']}; "
            f"{case['tts']['elapsed_seconds']:.3f}s)"
        )
        return case, _should_stop(exc)
    except KeyboardInterrupt:
        error = RoundtripError("interrupted", "round-trip interrupted")
        _record_error(case["tts"], error, tts_status)
        case["error_classification"] = error.classification
        case["tts"]["elapsed_seconds"] = round(time.monotonic() - started, 3)
        _progress(f"{prefix}: TTS interrupted ({case['tts']['elapsed_seconds']:.3f}s)")
        return case, True

    if len(audio) > MAX_STT_BYTES:
        error = RoundtripError(
            "local_validation",
            "generated WAV exceeds the public STT request limit",
            status=tts_status,
        )
        _record_error(case["stt"], error)
        case["error_classification"] = error.classification
        _progress(f"{prefix}: STT failed before request (local_validation)")
        return case, False

    started = time.monotonic()
    stt_status = None
    try:
        body, content_type = _multipart(
            target, fixture["language"], fixture["language"]
        )
        _progress(f"{prefix}: STT starting")
        stt_status, headers, raw = qualify._request(
            origin + "/v1/stt/transcriptions",
            token,
            body,
            content_type,
            args.timeout,
            qualify.MAX_JSON_BYTES,
            {"X-STT-Provider": "local", "X-Allow-Cloud-Audio": "false"},
        )
        case["stt"]["http_status"] = stt_status
        case["stt"]["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if stt_status != 200:
            raise RoundtripError(
                "http_error", f"STT returned HTTP {stt_status}", status=stt_status
            )
        response = qualify._json_response(raw)
        qualify._validate_stt_response(response, stt_status)
        provider = headers.get("X-Speech-Provider")
        case["stt"]["provider"] = provider
        if provider != "local":
            raise RoundtripError(
                "provider_mismatch",
                "STT serving provider was not local",
                status=stt_status,
            )
        case["stt"]["metadata"] = {
            key: response[key]
            for key in (
                "language",
                "detected_language",
                "source_language",
                "output_language",
                "translated",
            )
            if key in response
        }
        case["stt"]["status"] = "pass"
        case["transcription"] = response["text"]
        case["metrics"] = metrics(fixture["reference"], response["text"])
        case["quality_status"] = "MEASURED"
        _progress(
            f"{prefix}: STT complete ({case['stt']['elapsed_seconds']:.3f}s); "
            f"WER={case['metrics']['wer']:.4f} CER={case['metrics']['cer']:.4f}"
        )
    except (RoundtripError, qualify.QualificationError, OSError) as exc:
        if case["stt"]["elapsed_seconds"] is None:
            case["stt"]["elapsed_seconds"] = round(time.monotonic() - started, 3)
        _record_error(case["stt"], exc, stt_status)
        case["error_classification"] = case["stt"]["error"]["classification"]
        _progress(
            f"{prefix}: STT failed ({case['stt']['error']['classification']}; "
            f"{case['stt']['elapsed_seconds']:.3f}s)"
        )
        return case, _should_stop(exc)
    except KeyboardInterrupt:
        error = RoundtripError("interrupted", "round-trip interrupted")
        _record_error(case["stt"], error, stt_status)
        case["error_classification"] = error.classification
        case["stt"]["elapsed_seconds"] = round(time.monotonic() - started, 3)
        _progress(f"{prefix}: STT interrupted ({case['stt']['elapsed_seconds']:.3f}s)")
        return case, True

    case["technical_status"] = "PASS"
    return case, False


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=sorted(LANGUAGES))
    parser.add_argument("--case", help="run one fixture case, for example en-polite")
    parser.add_argument("--output-dir", type=Path, default=AUDIO_DIR)
    parser.add_argument("--report", type=Path, help="private JSON report path")
    parser.add_argument(
        "--regenerate",
        action="store_true",
        help="atomically replace matching generated WAVs after successful TTS",
    )
    parser.add_argument(
        "--tts-mode",
        choices=("quality", "fast", "auto", "high_quality", "extra_high_quality"),
        default="quality",
    )
    parser.add_argument("--timeout", type=float, default=600)
    return parser


def run(args):
    git_revision, git_worktree_dirty = _git_state()
    report = {
        "schema_version": "1.0",
        "operation": "tts_stt_roundtrip",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "git_revision": git_revision,
        "git_worktree_dirty": git_worktree_dirty,
        "public_api_metadata": {
            "stt": {
                "requested_provider": "local",
                "model": None,
                "model_availability": "not exposed by the transcription response",
            },
            "tts": {
                "provider": None,
                "model": None,
                "availability": "recorded only if returned by public response headers",
            },
        },
        "request": {
            "tts_mode": args.tts_mode,
            "tts_audio_processing": "none",
            "stt_provider": "local",
            "cloud_audio_consent": False,
            "timeout_seconds": args.timeout,
        },
        "cases": [],
        "technical_status": "FAIL",
        "quality_status": "NOT_MEASURED",
        "human_review_status": "NOT_REVIEWED",
        "error": None,
    }
    try:
        fixtures = discover_fixtures()
        if args.language:
            fixtures = [
                fixture for fixture in fixtures if fixture["language"] == args.language
            ]
        if args.case:
            fixtures = [
                fixture for fixture in fixtures if fixture["case_id"] == args.case
            ]
            if not fixtures:
                raise RoundtripError(
                    "local_validation", "requested fixture case was not found"
                )
        elif args.language and not fixtures:
            raise RoundtripError(
                "local_validation", "no fixtures found for requested language"
            )
        output_dir, targets = _output_targets(
            fixtures,
            args.output_dir,
            regenerate=args.regenerate,
            report_path=args.report,
        )
        origin, token = qualify._origin(qualify.load_env())
        stop = False
        total = len(fixtures)
        _progress(f"roundtrip: {total} cases; TTS={args.tts_mode}; STT provider=local")
        for position, (fixture, target) in enumerate(
            zip(fixtures, targets, strict=True), 1
        ):
            _progress(f"[{position}/{total}] {fixture['case_id']}")
            case, stop = _run_case(
                fixture, target, origin, token, args, position, total
            )
            report["cases"].append(case)
            if stop:
                failed_stage = (
                    case["tts"] if case["tts"]["status"] == "fail" else case["stt"]
                )
                report["error"] = {
                    "classification": case.get("error_classification"),
                    "api_code": (failed_stage.get("error") or {}).get("api_code"),
                    "http_status": failed_stage.get("http_status"),
                    "message": "stopped after an infrastructure or resource failure",
                }
                if case.get("error_classification") == "interrupted":
                    report["error"]["message"] = (
                        f"round-trip interrupted during case {case['case_id']}"
                    )
                break
        passed = bool(report["cases"]) and all(
            case["technical_status"] == "PASS" for case in report["cases"]
        )
        report["technical_status"] = "PASS" if passed else "FAIL"
        report["quality_status"] = (
            "MEASURED"
            if passed
            and all(case["quality_status"] == "MEASURED" for case in report["cases"])
            else "PARTIAL"
            if any(case["quality_status"] == "MEASURED" for case in report["cases"])
            else "NOT_MEASURED"
        )
        report["output_dir"] = str(output_dir)
    except KeyboardInterrupt:
        current_case = locals().get("fixture", {}).get("case_id")
        _progress(
            f"roundtrip interrupted{f' during case {current_case}' if current_case else ''}"
        )
        report["error"] = {
            "classification": "interrupted",
            "message": (
                f"round-trip interrupted during case {fixture['case_id']}"
                if "fixture" in locals()
                else "round-trip interrupted before case execution"
            ),
        }
    except (RoundtripError, qualify.QualificationError, OSError) as exc:
        report["error"] = {
            "classification": getattr(exc, "classification", "local_validation"),
            "api_code": getattr(exc, "api_code", None),
            "http_status": getattr(exc, "status", None),
            "message": str(exc)
            if isinstance(exc, (RoundtripError, qualify.QualificationError))
            else "input or configuration could not be read",
        }
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    return report


def main(argv=None):
    started = time.monotonic()
    parser = _parser()
    args = parser.parse_args(argv)
    if args.timeout <= 0 or args.timeout > 3600:
        parser.error("--timeout must be greater than 0 and at most 3600 seconds")
    report_writable = args.report is not None
    if report_writable:
        try:
            qualify._output_path(args.report, private=True)
        except qualify.QualificationError:
            report_writable = False
    report = run(args)
    if report_writable:
        try:
            qualify._write_output(
                args.report,
                json.dumps(report, ensure_ascii=False, indent=2).encode(),
                private=True,
            )
        except (OSError, qualify.QualificationError) as exc:
            message = (
                str(exc)
                if isinstance(exc, qualify.QualificationError)
                else "could not write private report"
            )
            print(f"FAIL roundtrip: report write failed: {message}", file=sys.stderr)
            return EXIT_OUTPUT
    passed = report["technical_status"] == "PASS"
    measured = sum(case["quality_status"] == "MEASURED" for case in report["cases"])
    for case in report["cases"]:
        metric_text = (
            f"WER={case['metrics']['wer']:.4f} CER={case['metrics']['cer']:.4f}"
            if case["metrics"]
            else "metrics=N/A"
        )
        print(
            f"{case['case_id']}: technical={case['technical_status']} "
            f"{metric_text} human_review={case['human_review_status']}"
            + (
                "; "
                + next(
                    f"error={stage['error']['classification']}: {stage['error']['message']}"
                    for stage in (case["tts"], case["stt"])
                    if stage["error"]
                )
                if case["tts"]["error"] or case["stt"]["error"]
                else ""
            )
        )
    error = report.get("error")
    print(
        f"{'PASS' if passed else 'FAIL'} roundtrip: {len(report['cases'])} cases; "
        f"technical={report['technical_status']}; "
        f"successes={sum(case['technical_status'] == 'PASS' for case in report['cases'])}; "
        f"failures={sum(case['technical_status'] != 'PASS' for case in report['cases'])}; "
        f"metrics_measured={measured}; total_elapsed={time.monotonic() - started:.3f}s; "
        f"human_review={report['human_review_status']}"
        + (f"; error={error['classification']}; {error['message']}" if error else "")
    )
    if passed:
        return 0
    error = report.get("error") or {}
    classification = error.get("classification")
    if classification == "output_error":
        return EXIT_OUTPUT
    if classification == "interrupted":
        return 130
    if classification == "local_validation" or (
        classification == "authentication" and error.get("http_status") is None
    ):
        return EXIT_INPUT
    return EXIT_REQUEST


if __name__ == "__main__":
    raise SystemExit(main())
