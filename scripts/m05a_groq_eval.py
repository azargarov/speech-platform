"""Sequential, private Groq comparison runner for the M05A synthetic corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time

import requests
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import m05a_eval


ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
MODELS = {
    "qwen/qwen3.8-27b": {"reasoning_effort": "none", "include_reasoning": False},
    "openai/gpt-oss-120b": {"reasoning_effort": "low", "include_reasoning": False},
}
TIMEOUT_MAX_SECONDS = 180
MAX_RETRIES = 2


class GroqError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        headers=None,
        fatal: bool = False,
    ):
        super().__init__(message)
        self.status = status
        self.headers = headers or {}
        self.fatal = fatal


def request_payload(model: str, prompt: str, case: dict) -> dict:
    if model not in MODELS:
        raise ValueError(f"unsupported exact Groq model {model!r}")
    content = json.dumps(
        {key: case[key] for key in ("mode", "formatting", "target_language", "text")},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": content},
        ],
        "temperature": 0,
        "top_p": 1,
        "seed": 20261022,
        "max_completion_tokens": 1024,
        **MODELS[model],
    }


def _safe_error(status: int, body: bytes) -> tuple[str, bool]:
    # API error bodies are intentionally not copied to disk or console; they may
    # echo request fields. Parse only a short provider message for classification.
    try:
        data = json.loads(body.decode("utf-8"))
        message = str(data.get("error", {}).get("message", ""))[:300].casefold()
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
        message = ""
    if status == 401 or status == 403:
        return "authentication/authorization failure", True
    if status == 400 and any(
        parameter in message for parameter in ("reasoning_effort", "include_reasoning")
    ):
        return "provider rejected the requested reasoning configuration", True
    if status == 404 or (
        status == 400
        and any(term in message for term in ("model", "not found", "does not exist"))
    ):
        return "invalid model or endpoint", True
    if status == 429:
        quota = any(
            term in message
            for term in (
                "daily",
                "per day",
                "requests per day",
                "tokens per day",
                "insufficient_quota",
                "billing limit",
            )
        )
        return ("nonrecoverable quota/rate limit" if quota else "rate limited"), quota
    if status >= 500:
        return "transient provider error", False
    return f"request rejected (HTTP {status})", True


def call_groq(payload: dict, api_key: str, timeout: int, post=None):
    if not api_key:
        raise ValueError("GROQ_API_KEY is required for cloud evaluation")
    send = post or requests.post
    started = time.monotonic()
    try:
        response = send(
            ENDPOINT,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            timeout=timeout,
        )
    except requests.Timeout:
        raise GroqError("request timeout") from None
    except requests.RequestException:
        raise GroqError("network transport failure") from None
    status_code = response.status_code
    if status_code >= 400:
        message, fatal = _safe_error(status_code, response.content)
        raise GroqError(
            message, status=status_code, headers=response.headers, fatal=fatal
        )
    elapsed = time.monotonic() - started
    try:
        data = response.json()
        choice = data["choices"][0]
        output = choice["message"]["content"]
        if not isinstance(output, str):
            raise TypeError
    except (ValueError, KeyError, IndexError, TypeError):
        raise GroqError("malformed completion response", fatal=True) from None
    usage = data.get("usage") or {}
    return {
        "response": output,
        "provider": "groq",
        "model": data.get("model"),
        "response_id": data.get("id"),
        "system_fingerprint": data.get("system_fingerprint"),
        "http_status": status_code,
        "finish_reason": choice.get("finish_reason"),
        "usage": {
            "input_tokens": usage.get("prompt_tokens"),
            "output_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        },
        "provider_processing_time": response.headers.get("x-groq-processing-time")
        if response.headers
        else None,
        "rate_limits": {
            key: response.headers.get(key)
            for key in (
                "x-ratelimit-limit-requests",
                "x-ratelimit-remaining-requests",
                "x-ratelimit-reset-requests",
                "x-ratelimit-limit-tokens",
                "x-ratelimit-remaining-tokens",
                "x-ratelimit-reset-tokens",
            )
            if response.headers and response.headers.get(key) is not None
        },
        "latency_seconds": elapsed,
    }


def _delay_for(error: GroqError, attempt: int, delay: float) -> float:
    if error.status == 429:
        try:
            return min(
                120.0, max(delay, float(error.headers.get("Retry-After", delay)))
            )
        except (TypeError, ValueError):
            return max(delay, 2 ** (attempt + 1))
    return max(delay, 2 ** (attempt + 1))


def _result(
    case: dict,
    model: str,
    prompt_version: str,
    completion: dict | None,
    error: str | None = None,
    retries: int = 0,
) -> dict:
    return {
        "case_id": case["id"],
        "provider": "groq",
        "model": model,
        "prompt_version": prompt_version,
        "inference_settings": MODELS[model],
        "transformation": {
            key: case[key]
            for key in (
                "input_language",
                "mode",
                "formatting",
                "target_language",
                "text",
                "invariants",
                "review_constraints",
            )
        },
        "length_class": m05a_eval.input_length_class(case["text"]),
        "http_outcome": "success" if completion else "error",
        "response": completion["response"] if completion else None,
        "timing": {"wall_clock_seconds": completion["latency_seconds"]}
        if completion
        else {},
        "provider_processing_time": completion["provider_processing_time"]
        if completion
        else None,
        "usage": completion["usage"] if completion else None,
        "finish_reason": completion["finish_reason"] if completion else None,
        "response_id": completion["response_id"] if completion else None,
        "provider_model_returned": completion["model"] if completion else None,
        "http_status": completion["http_status"] if completion else None,
        "system_fingerprint": completion["system_fingerprint"] if completion else None,
        "rate_limits": completion["rate_limits"] if completion else {},
        "lexical_flags": m05a_eval.invariant_flags(
            completion["response"], case["invariants"]
        )
        if completion
        else [],
        "retries": retries,
        "error": error,
        "request_attempts": retries + 1,
    }


def run(
    model: str,
    run_dir: Path,
    cases: list[dict],
    prompt_path: Path,
    prompt_version: str,
    delay: float,
    timeout: int,
    retries: int,
    resume: bool = False,
    api_key: str | None = None,
) -> int:
    private_root = (m05a_eval.ROOT / "private/m05a").resolve()
    run_dir = run_dir.resolve()
    if not run_dir.is_relative_to(private_root):
        raise ValueError(f"run directory must be under {private_root}")
    if model not in MODELS:
        raise ValueError(f"unsupported exact Groq model {model!r}")
    api_key = api_key if api_key is not None else os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise ValueError("GROQ_API_KEY is required for cloud evaluation")
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(run_dir, 0o700)
    results_path = run_dir / "results.jsonl"
    if results_path.exists() and not resume:
        raise ValueError(f"refusing to overwrite {results_path}; use --resume")
    prompt = m05a_eval.system_prompt(prompt_path)
    config = {
        "provider": "groq",
        "model": model,
        "prompt_version": prompt_version,
        "prompt_sha256": hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
        "settings": MODELS[model],
        "generation": {
            "temperature": 0,
            "top_p": 1,
            "seed": 20261022,
            "max_completion_tokens": 1024,
        },
        "delay_seconds": delay,
        "timeout_seconds": timeout,
        "max_retries": retries,
        "case_ids": [case["id"] for case in cases],
    }
    run_path = run_dir / "run.json"
    if run_path.exists():
        previous = json.loads(run_path.read_text(encoding="utf-8"))
        if not resume or previous.get("configuration") != config:
            raise ValueError("resume configuration does not match existing run")
    else:
        run_path.write_text(
            json.dumps(
                {
                    "started_at_utc": datetime.now(timezone.utc).isoformat(),
                    "configuration": config,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.chmod(run_path, 0o600)
    rows = []
    if results_path.exists():
        rows = [
            json.loads(line)
            for line in results_path.read_text(encoding="utf-8").splitlines()
            if line
        ]
    completed = {row["case_id"] for row in rows if row.get("http_outcome") == "success"}
    results = {row["case_id"]: row for row in rows}
    for index, case in enumerate(cases, 1):
        if case["id"] in completed:
            continue
        payload = request_payload(model, prompt, case)
        result = None
        for attempt in range(retries + 1):
            try:
                completion = call_groq(payload, api_key, timeout)
                result = _result(
                    case, model, prompt_version, completion, retries=attempt
                )
                break
            except GroqError as exc:
                if exc.fatal or attempt >= retries:
                    result = _result(
                        case, model, prompt_version, None, str(exc), attempt
                    )
                    result["http_status"] = exc.status
                    result["rate_limits"] = {
                        key: exc.headers.get(key)
                        for key in (
                            "retry-after",
                            "x-ratelimit-remaining-requests",
                            "x-ratelimit-reset-requests",
                            "x-ratelimit-remaining-tokens",
                            "x-ratelimit-reset-tokens",
                        )
                        if exc.headers.get(key)
                    }
                    break
                wait = _delay_for(exc, attempt, delay)
                print(
                    f"{case['id']}: transient HTTP {exc.status or 'transport'}; retry {attempt + 1}/{retries} after {wait:g}s",
                    flush=True,
                )
                time.sleep(wait)
        results[case["id"]] = result
        ordered = [
            results[case_item["id"]]
            for case_item in cases
            if case_item["id"] in results
        ]
        temp_path = results_path.with_suffix(".jsonl.tmp")
        temp_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in ordered),
            encoding="utf-8",
        )
        os.chmod(temp_path, 0o600)
        temp_path.replace(results_path)
        print(f"{index}/{len(cases)} {case['id']} {result['http_outcome']}", flush=True)
        if result["http_outcome"] == "error":
            if (
                result.get("http_status") == 429
                or result.get("http_status") in (401, 403, 404)
                or result.get("http_status", 0) < 500
            ):
                print(
                    "stopping after nonrecoverable/provider rejection; use --resume after resolving it",
                    file=sys.stderr,
                )
            break
        if index < len(cases) and delay:
            time.sleep(delay)
    ordered = [
        results[case_item["id"]] for case_item in cases if case_item["id"] in results
    ]
    successful = [row for row in ordered if row["http_outcome"] == "success"]
    summary = {
        "started_at_utc": json.loads(run_path.read_text(encoding="utf-8"))[
            "started_at_utc"
        ],
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": "groq",
        "model": model,
        "prompt_version": prompt_version,
        "case_count": len(cases),
        "successful_count": len(successful),
        "failed_count": len(ordered) - len(successful),
        "request_count": sum(row.get("request_attempts", 1) for row in ordered),
        "retry_count": sum(row.get("retries", 0) for row in ordered),
        "latency_seconds": [row["timing"]["wall_clock_seconds"] for row in successful],
        "first_success_latency_seconds": successful[0]["timing"]["wall_clock_seconds"]
        if successful
        else None,
        "subsequent_request_latency_median_seconds": statistics.median(
            [row["timing"]["wall_clock_seconds"] for row in successful[1:]]
        )
        if len(successful) > 1
        else None,
        "input_tokens": sum(row["usage"]["input_tokens"] or 0 for row in successful),
        "output_tokens": sum(row["usage"]["output_tokens"] or 0 for row in successful),
        "total_tokens": sum(row["usage"]["total_tokens"] or 0 for row in successful),
        "results_file": str(results_path),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    os.chmod(run_dir / "summary.json", 0o600)
    return 0 if len(successful) == len(cases) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument(
        "--prompt",
        type=Path,
        default=m05a_eval.ROOT / "docs/milestones/M05A/prompts/v2.md",
    )
    parser.add_argument("--prompt-version", default="v2")
    parser.add_argument("--delay-seconds", type=float, default=2.1)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--retries", type=int, default=MAX_RETRIES)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="validate request plan without network access",
    )
    args = parser.parse_args(argv)
    try:
        if args.delay_seconds < 0 or args.timeout_seconds not in range(
            1, TIMEOUT_MAX_SECONDS + 1
        ):
            parser.error("delay must be nonnegative and timeout must be 1..180 seconds")
        if args.retries not in range(MAX_RETRIES + 1):
            parser.error("retries must be 0..2")
        cases = m05a_eval.read_cases(m05a_eval.CORPUS) + m05a_eval.read_cases(
            m05a_eval.ROOT / "docs/milestones/M05A/unseen-cases.jsonl"
        )
        errors = m05a_eval.validate_cases(cases, require_corpus_coverage=False)
        if len(cases) != 46:
            errors.append(f"expected combined corpus of 46 cases, found {len(cases)}")
        if errors:
            raise ValueError("; ".join(errors))
        m05a_eval.system_prompt(args.prompt)
        if args.preview:
            if not args.model:
                parser.error("--model is required for --preview")
            print(
                json.dumps(
                    {
                        "provider": "groq",
                        "model": args.model,
                        "prompt_version": args.prompt_version,
                        "case_count": len(cases),
                        "planned_requests": len(cases),
                        "max_retries_per_request": args.retries,
                        "maximum_requests_with_retries": len(cases)
                        * (args.retries + 1),
                        "delay_seconds": args.delay_seconds,
                        "reasoning": MODELS[args.model],
                    },
                    indent=2,
                )
            )
            return 0
        if not args.model or not args.run_dir:
            parser.error("--model and --run-dir are required unless --preview is used")
        return run(
            args.model,
            args.run_dir,
            cases,
            args.prompt,
            args.prompt_version,
            args.delay_seconds,
            args.timeout_seconds,
            args.retries,
            args.resume,
        )
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
