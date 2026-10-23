"""Offline-safe response handling for the private M05B Stage 2A runner."""

from __future__ import annotations

import json
import os
from pathlib import Path


MAX_RESPONSE_BYTES = 1_048_576


def save_received_response(body: bytes, evidence_path: Path) -> bool:
    """Persist a bounded response body privately before parsing or validation."""
    oversized = len(body) > MAX_RESPONSE_BYTES
    captured = body[:MAX_RESPONSE_BYTES]
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(evidence_path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as evidence:
            evidence.write(captured)
            evidence.flush()
            os.fsync(evidence.fileno())
    except BaseException:
        try:
            evidence_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return oversized


def record_response(
    *, body: bytes, evidence_path: Path, case: dict, context: int, client_seconds: float
) -> dict:
    """Save then interpret a response, keeping operational and quality status separate."""
    oversized = save_received_response(body, evidence_path)
    if oversized:
        return {
            "case_id": case["id"],
            "context": context,
            "http_outcome": "received",
            "completion_status": "unvalidated_oversized_response",
            "client_total_s": client_seconds,
            "server": {},
            "quality_status": "not_evaluated",
            "validation_diagnostics": [
                f"response exceeds {MAX_RESPONSE_BYTES} byte limit; saved bounded prefix"
            ],
            "response_evidence": evidence_path.name,
        }
    try:
        data = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            "case_id": case["id"],
            "context": context,
            "http_outcome": "received",
            "completion_status": "unparseable_response",
            "client_total_s": client_seconds,
            "server": {},
            "quality_status": "not_evaluated",
            "validation_diagnostics": ["response body is not valid JSON"],
            "response_evidence": evidence_path.name,
        }

    if not isinstance(data, dict):
        data = {}
        parse_diagnostic = ["response JSON root is not an object"]
    else:
        parse_diagnostic = []
    response_text = data.get("response", "")
    if not isinstance(response_text, str):
        response_text = ""
        parse_diagnostic.append("response field is not text")
    done = data.get("done") is True
    server = {
        "load_duration_ns": data.get("load_duration"),
        "total_duration_ns": data.get("total_duration"),
        "prompt_eval_duration_ns": data.get("prompt_eval_duration"),
        "eval_duration_ns": data.get("eval_duration"),
        "prompt_tokens": data.get("prompt_eval_count"),
        "completion_tokens": data.get("eval_count"),
    }
    diagnostics = list(parse_diagnostic)
    if data.get("error"):
        diagnostics.append("provider response contains an API error")
    if not done:
        diagnostics.append("completion marker `done` is not true")
    flags = []
    quality_error = None
    if not diagnostics and done:
        try:
            from scripts.m05a_eval import invariant_flags

            flags = invariant_flags(response_text, case["invariants"])
            diagnostics.extend(
                f"lexical invariant {index} missing (expected length {len(token)})"
                for index, token in enumerate(case["invariants"], 1)
                if token in flags
            )
        except (
            Exception
        ) as exc:  # Keep operational measurements if quality checks fail.
            quality_error = type(exc).__name__
            diagnostics.append(f"text-quality validation raised {quality_error}")
    return {
        "case_id": case["id"],
        "language": case.get("input_language"),
        "context": context,
        "http_outcome": "received",
        "completion_status": "completed"
        if done and not data.get("error")
        else "incomplete",
        "client_total_s": client_seconds,
        "server": server,
        "quality_status": "error"
        if quality_error
        else "failed"
        if flags
        else "passed"
        if done and not diagnostics
        else "not_evaluated",
        "validation_diagnostics": diagnostics,
        "invariant_failure_count": len(flags),
        "response_evidence": evidence_path.name,
    }
