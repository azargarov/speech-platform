"""Collect bounded, private diagnostics for explicit qualification debug runs."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("gateway", "stt", "tts")
MAX_LOG_BYTES = 32 * 1024
MAX_LOG_LINES = 100
MIN_LOG_WINDOW_SECONDS = 30
MAX_LOG_WINDOW_SECONDS = 300
SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*")
KEY_VALUE_SECRET = re.compile(
    r"(?i)((?:api[_-]?key|authorization|token|password|secret)\s*[=:]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;}]+)"
)
KEY_VALUE_CONTENT = re.compile(
    r"(?i)((?:request_)?(?:text|transcript|original_text|transformed_text|payload|body|content|audio|prompt)\s*[=:]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^,;}]+)"
)
BARE_API_KEY = re.compile(r"\b(?:gsk_[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{16,})\b")
URI_CREDENTIAL = re.compile(r"(https?://)[^/@\s]+:[^/@\s]+@")
SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "audio",
    "body",
    "content",
    "original_text",
    "password",
    "payload",
    "secret",
    "text",
    "token",
    "transcript",
    "transformed_text",
}


def _is_loopback_target(target: str) -> bool:
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        return False


def _clean_json(value):
    if isinstance(value, dict):
        return {
            key: _clean_json(item)
            for key, item in value.items()
            if not _sensitive_key(key)
        }
    if isinstance(value, list):
        return [_clean_json(item) for item in value]
    return value


def _sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return (
        lowered in SENSITIVE_KEYS
        or any(
            label in lowered
            for label in (
                "authorization",
                "api_key",
                "apikey",
                "token",
                "secret",
                "password",
            )
        )
        or any(
            label in lowered
            for label in (
                "transcript",
                "request_text",
                "original_text",
                "transformed_text",
            )
        )
        or lowered in {"input", "prompt", "message"}
    )


def _redact_line(line: str, secrets: tuple[str, ...]) -> str:
    prefix, separator, message = line.partition("|")
    if separator:
        message = message.lstrip()
        try:
            parsed = json.loads(message)
        except json.JSONDecodeError:
            pass
        else:
            message = json.dumps(
                _clean_json(parsed), ensure_ascii=False, separators=(",", ":")
            )
            line = f"{prefix}| {message}"
    for secret in secrets:
        if len(secret) >= 8:
            line = line.replace(secret, "[REDACTED]")
    line = BEARER.sub(r"\1[REDACTED]", line)
    line = KEY_VALUE_SECRET.sub(r"\1[REDACTED]", line)
    line = KEY_VALUE_CONTENT.sub(r"\1[REDACTED]", line)
    line = BARE_API_KEY.sub("[REDACTED]", line)
    return URI_CREDENTIAL.sub(r"\1[REDACTED]@", line)


def _bounded_window(seconds: int) -> int:
    return max(MIN_LOG_WINDOW_SECONDS, min(int(seconds), MAX_LOG_WINDOW_SECONDS))


def collect_local_logs(
    target: str,
    *,
    window_seconds: int,
    server_request_ids=(),
    secrets=(),
    root: Path = ROOT,
) -> dict:
    """Fetch recent logs only for the repository-owned local Compose project."""
    window = _bounded_window(window_seconds)
    request_ids = sorted(
        {
            value
            for value in server_request_ids
            if isinstance(value, str) and SAFE_ID.fullmatch(value)
        }
    )
    result = {
        "collection": "unavailable",
        "reason": None,
        "window_seconds": window,
        "window_capped": int(window_seconds) > MAX_LOG_WINDOW_SECONDS,
        "max_lines_per_service": MAX_LOG_LINES,
        "max_bytes_per_service": MAX_LOG_BYTES,
        "correlation": "server_request_id" if request_ids else "time_window_only",
        "server_request_ids": request_ids,
        "services": {},
    }
    if not _is_loopback_target(target):
        result["reason"] = "target_is_not_loopback"
        return result

    from scripts import compose

    secret_values = tuple(value for value in secrets if isinstance(value, str))
    for service in SERVICES:
        collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            command = [
                "logs",
                "--since",
                f"{window}s",
                "--tail",
                str(MAX_LOG_LINES),
                service,
            ]
            captured = compose.run(command, root=root, timeout=20, capture=True)
        except (
            OSError,
            RuntimeError,
            ValueError,
            TimeoutError,
            subprocess.SubprocessError,
        ):
            result["services"][service] = {
                "status": "failed",
                "collected_at": collected_at,
                "reason": "local Compose log retrieval failed",
                "lines": [],
            }
            continue
        if captured.returncode:
            result["services"][service] = {
                "status": "failed",
                "collected_at": collected_at,
                "reason": f"local Compose log retrieval exited {captured.returncode}",
                "lines": [],
            }
            continue
        raw = (captured.stdout or "").encode("utf-8", errors="replace")
        truncated = len(raw) > MAX_LOG_BYTES
        bounded = raw[:MAX_LOG_BYTES].decode("utf-8", errors="ignore")
        lines = bounded.splitlines()[-MAX_LOG_LINES:]
        matched = [
            line
            for line in lines
            if request_ids and any(rid in line for rid in request_ids)
        ]
        if matched:
            lines = matched
            correlation = "server_request_id_match"
        else:
            correlation = (
                "time_window_only_request_id_not_found"
                if request_ids
                else "time_window_only_no_server_id"
            )
        clean_lines = [_redact_line(line, secret_values) for line in lines]
        result["services"][service] = {
            "status": "matched" if clean_lines else "no_matching_lines",
            "collected_at": collected_at,
            "correlation": correlation,
            "truncated": truncated,
            "line_count": len(clean_lines),
            "log_text": "\n".join(clean_lines),
        }
    statuses = {entry["status"] for entry in result["services"].values()}
    if statuses <= {"failed"}:
        result["collection"] = "failed"
        result["reason"] = "local Compose log retrieval failed for all services"
    elif "failed" in statuses:
        result["collection"] = "partial"
        result["reason"] = "local Compose log retrieval failed for some services"
    elif "matched" in statuses:
        result["collection"] = "matched"
    else:
        result["collection"] = "no_matching_lines"
    return result


def _server_request_ids(value):
    found = set()
    if isinstance(value, dict):
        request_id = value.get("server_request_id")
        if isinstance(request_id, str) and SAFE_ID.fullmatch(request_id):
            found.add(request_id)
        for item in value.values():
            found.update(_server_request_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_server_request_ids(item))
    return found


def _client_request_ids(value):
    found = set()
    if isinstance(value, dict):
        request_id = value.get("client_request_id")
        if isinstance(request_id, str) and SAFE_ID.fullmatch(request_id):
            found.add(request_id)
        for item in value.values():
            found.update(_client_request_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_client_request_ids(item))
    return found


def _result_summary(report: dict) -> dict:
    summary = {
        "operation": report.get("operation"),
        "http": report.get("http"),
        "elapsed_seconds": report.get("elapsed_seconds"),
        "outcome": report.get("outcome") or report.get("technical_status"),
    }
    error = report.get("error")
    if isinstance(error, dict):
        summary["error"] = {
            key: error[key]
            for key in ("classification", "api_code", "http_status")
            if key in error
        }
    request = report.get("request")
    if isinstance(request, dict):
        summary["request"] = {
            key: request[key]
            for key in ("target", "auth_mode", "parameters", "input", "routing")
            if key in request
        }
    elif report.get("target"):
        summary["target"] = report["target"]
    summary["request_ids"] = {
        "client_local_only": sorted(_client_request_ids(report)),
        "server_returned": sorted(_server_request_ids(report)),
        "client_id_sent_to_gateway": False,
    }
    stages = []

    def visit(value):
        if isinstance(value, dict):
            if "api_code" in value or "http_status" in value:
                stages.append(
                    {
                        key: value[key]
                        for key in (
                            "case_id",
                            "operation",
                            "http_status",
                            "api_code",
                            "error_classification",
                        )
                        if key in value
                    }
                )
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(report)
    if stages:
        summary["stages"] = stages[:100]
    return summary


def save_debug_evidence(
    report: dict,
    *,
    target: str,
    window_seconds: int,
    secrets=(),
    root: Path | None = None,
) -> str:
    root = root or ROOT
    attempted = bool(report.get("http", {}).get("status")) or report.get(
        "diagnostics", {}
    ).get("failure_stage") in {"connect", "request", "response_read"}
    if attempted:
        diagnostics = collect_local_logs(
            target,
            window_seconds=window_seconds,
            server_request_ids=_server_request_ids(report),
            secrets=secrets,
            root=root,
        )
    else:
        diagnostics = {
            "collection": "skipped",
            "reason": "no Gateway request was attempted",
            "window_seconds": _bounded_window(window_seconds),
            "window_capped": int(window_seconds) > MAX_LOG_WINDOW_SECONDS,
            "services": {},
        }
    evidence = {
        "schema_version": "1.0",
        "operation": "qualification_debug_evidence",
        "target": target,
        "result": _result_summary(report),
        "diagnostics": diagnostics,
    }
    private = root / "private"
    if private.is_symlink() or not private.is_dir():
        raise OSError("private evidence directory is unavailable")
    path = private / f"qualification-debug-{uuid.uuid4().hex}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(evidence, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except OSError:
        path.unlink(missing_ok=True)
        raise
    return str(path.relative_to(root))
