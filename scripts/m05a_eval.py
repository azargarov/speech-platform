"""Small, sequential Ollama runner for the M05A synthetic evaluation corpus."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs/milestones/M05A/cases.jsonl"
PROMPT = ROOT / "docs/milestones/M05A/prompts/v1.md"
MODES = {"raw", "written", "polite", "diplomatic"}
FORMATS = {"normal", "concise", "structured"}
LANGUAGES = {"en", "sv", "ru"}
SETTINGS = {
    "num_ctx": 4096,
    "num_predict": 512,
    "temperature": 0,
    "top_p": 1,
    "seed": 20261022,
    "num_batch": 128,
    "num_thread": 8,
}
TIMEOUT_SECONDS = 300


def read_cases(path: Path = CORPUS) -> list[dict]:
    cases = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        cases.append(case)
    return cases


def validate_cases(
    cases: list[dict], require_corpus_coverage: bool = True
) -> list[str]:
    errors: list[str] = []
    if require_corpus_coverage and not 30 <= len(cases) <= 40:
        errors.append(f"expected 30–40 cases, found {len(cases)}")
    seen: set[str] = set()
    for index, case in enumerate(cases, 1):
        prefix = f"case {index}"
        required = {
            "id",
            "input_language",
            "text",
            "mode",
            "formatting",
            "target_language",
            "invariants",
            "review_constraints",
        }
        missing = required - case.keys()
        if missing:
            errors.append(f"{prefix}: missing fields {sorted(missing)}")
            continue
        case_id = case["id"]
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"{prefix}: id must be a non-empty string")
        elif case_id in seen:
            errors.append(f"{prefix}: duplicate id {case_id}")
        else:
            seen.add(case_id)
        if case["mode"] not in MODES:
            errors.append(f"{case_id}: invalid mode {case['mode']!r}")
        if case["formatting"] not in FORMATS:
            errors.append(f"{case_id}: invalid formatting {case['formatting']!r}")
        if case["mode"] == "raw" and case["formatting"] != "normal":
            errors.append(f"{case_id}: raw mode requires normal formatting")
        target = case["target_language"]
        if target is not None and target not in LANGUAGES:
            errors.append(f"{case_id}: invalid target language {target!r}")
        if not isinstance(case["text"], str) or not case["text"].strip():
            errors.append(f"{case_id}: text must be non-empty")
        if not isinstance(case["invariants"], list) or not case["invariants"]:
            errors.append(f"{case_id}: invariants must be a non-empty list")
        if (
            not isinstance(case["review_constraints"], str)
            or not case["review_constraints"].strip()
        ):
            errors.append(f"{case_id}: review_constraints must be non-empty")

    ids = {case.get("id") for case in cases}
    if len(ids) != len(cases):
        pass  # The per-case duplicate diagnostic is more useful.
    if require_corpus_coverage:
        input_languages = {
            case.get("input_language", "").split("+")[0] for case in cases
        }
        for language in LANGUAGES:
            if language not in input_languages:
                errors.append(f"corpus lacks {language} input")
        if not any("+" in case.get("input_language", "") for case in cases):
            errors.append("corpus lacks mixed-language input")
        for fmt in FORMATS:
            if not any(case.get("formatting") == fmt for case in cases):
                errors.append(f"corpus lacks {fmt} formatting")
        for language in LANGUAGES:
            if not any(case.get("target_language") == language for case in cases):
                errors.append(f"corpus lacks translation target {language}")
    return errors


def system_prompt(path: Path = PROMPT) -> str:
    quoted = [
        line[1:].lstrip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith(">")
    ]
    prompt = " ".join(part.strip() for part in quoted if part.strip())
    if not prompt:
        raise ValueError(f"no blockquote prompt found in {path}")
    return prompt


def invariant_flags(output: str, invariants: list[str]) -> list[str]:
    normalized = " ".join(output.casefold().split())
    flags = []
    for token in invariants:
        expected = " ".join(token.casefold().split())
        if not re.search(rf"(?<!\w){re.escape(expected)}(?!\w)", normalized):
            flags.append(token)
    return flags


def post_json(base_url: str, path: str, payload: dict | None = None) -> dict:
    body = (
        None
        if payload is None
        else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    )
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def model_identity(base_url: str, model: str) -> dict:
    tags = post_json(base_url, "/api/tags")
    matches = [item for item in tags.get("models", []) if item.get("name") == model]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one installed model named {model!r}")
    details = post_json(base_url, "/api/show", {"model": model})
    return {
        "name": matches[0].get("name"),
        "digest": matches[0].get("digest"),
        "size_bytes": matches[0].get("size"),
        "details": matches[0].get("details", {}),
        "capabilities": details.get("capabilities"),
        "model_info": details.get("model_info", {}),
    }


def generate_one(
    base_url: str, model: str, prompt: str, case: dict
) -> tuple[dict, float]:
    user_content = json.dumps(
        {
            "mode": case["mode"],
            "formatting": case["formatting"],
            "target_language": case["target_language"],
            "text": case["text"],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    payload = {
        "model": model,
        "system": prompt,
        "prompt": user_content,
        "stream": True,
        "think": False,
        "keep_alive": "10m",
        "options": SETTINGS,
    }
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    first_fragment_seconds = None
    fragments: list[str] = []
    thinking: list[str] = []
    final: dict = {}
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        for raw_line in response:
            if not raw_line.strip():
                continue
            event = json.loads(raw_line.decode("utf-8"))
            if event.get("error"):
                raise RuntimeError(event["error"])
            fragment = event.get("response", "")
            if fragment:
                if first_fragment_seconds is None:
                    first_fragment_seconds = time.monotonic() - started
                fragments.append(fragment)
            if event.get("thinking"):
                thinking.append(event["thinking"])
            if event.get("done"):
                final = event
    elapsed = time.monotonic() - started
    output = "".join(fragments)
    result = {
        "case_id": case["id"],
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
        "input_length_chars": len(case["text"]),
        "length_class": input_length_class(case["text"]),
        "prompt_version": "v1",
        "generation_settings": {"think": False, "keep_alive": "10m", **SETTINGS},
        "response": output,
        "thinking_output": "".join(thinking),
        "lexical_flags": invariant_flags(output, case["invariants"]),
        "timing": {
            "request_seconds": elapsed,
            "first_fragment_seconds": first_fragment_seconds,
            "ollama_total_duration_ns": final.get("total_duration"),
            "ollama_load_duration_ns": final.get("load_duration"),
            "ollama_prompt_eval_duration_ns": final.get("prompt_eval_duration"),
            "ollama_eval_duration_ns": final.get("eval_duration"),
            "prompt_tokens": final.get("prompt_eval_count"),
            "output_tokens": final.get("eval_count"),
            "tokens_per_second": (
                final["eval_count"] / (final["eval_duration"] / 1_000_000_000)
                if final.get("eval_count") and final.get("eval_duration")
                else None
            ),
        },
        "error": None,
    }
    return result, elapsed


def unload(base_url: str, model: str) -> dict:
    return post_json(
        base_url,
        "/api/generate",
        {"model": model, "keep_alive": 0, "stream": False},
    )


def input_length_class(text: str) -> str:
    length = len(text)
    if length < 100:
        return "short"
    if length < 300:
        return "medium"
    return "long"


def is_cold_request(row: dict) -> bool:
    """Treat model load duration above one second as a cold load."""
    return row["timing"].get("ollama_load_duration_ns", 0) > 1_000_000_000


def summarize(
    path: Path,
    identity: dict,
    rows: list[dict],
    started_at: str,
    loaded_models: list[dict],
    placement_error: str | None,
) -> dict:
    successful = [row for row in rows if row.get("error") is None]
    cold = [
        row["timing"]["request_seconds"] for row in successful if is_cold_request(row)
    ]
    warm = [
        row["timing"]["request_seconds"]
        for row in successful
        if not is_cold_request(row)
    ]
    tokens_per_second = [
        row["timing"]["tokens_per_second"]
        for row in successful
        if row["timing"].get("tokens_per_second") is not None
    ]
    summary = {
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": identity,
        "loaded_model_placement": loaded_models,
        "loaded_model_placement_error": placement_error,
        "prompt_version": "v1",
        "case_count": len(rows),
        "successful_count": len(successful),
        "failed_count": len(rows) - len(successful),
        "lexical_flag_count": sum(bool(row.get("lexical_flags")) for row in successful),
        "cold_request_seconds": cold,
        "warm_request_median_seconds": statistics.median(warm) if warm else None,
        "warm_request_range_seconds": [min(warm), max(warm)] if warm else None,
        "tokens_per_second_median": statistics.median(tokens_per_second)
        if tokens_per_second
        else None,
        "latency_by_length_class_seconds": {
            label: {
                "count": len(values),
                "median": statistics.median(values),
                "range": [min(values), max(values)],
            }
            for label in ("short", "medium", "long")
            if (
                values := [
                    row["timing"]["request_seconds"]
                    for row in successful
                    if row.get("length_class") == label
                ]
            )
        },
        "gpu_samples": gpu_summary(path / "gpu-samples.csv"),
        "ollama_container_samples": docker_stats_summary(path / "docker-samples.csv"),
        "host_memory_samples": host_memory_summary(path / "host-memory-samples.csv"),
        "settings": {"think": False, "timeout_seconds": TIMEOUT_SECONDS, **SETTINGS},
        "results_file": str(path / "results.jsonl"),
    }
    (path / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def gpu_summary(path: Path) -> dict:
    if not path.exists():
        return {"sample_count": 0, "error": "GPU sampler did not create output"}
    samples = []
    try:
        with path.open(encoding="utf-8", newline="") as sample_file:
            for row in csv.reader(sample_file):
                if len(row) != 4:
                    continue
                timestamp, used, free, utilization = (field.strip() for field in row)
                try:
                    samples.append(
                        {
                            "timestamp": timestamp,
                            "memory_used_mib": int(used),
                            "memory_free_mib": int(free),
                            "gpu_utilization_percent": int(utilization),
                        }
                    )
                except ValueError:
                    continue
    except OSError as exc:
        return {"sample_count": 0, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "sample_count": len(samples),
        "peak_memory_used_mib": max(
            (s["memory_used_mib"] for s in samples), default=None
        ),
        "minimum_memory_free_mib": min(
            (s["memory_free_mib"] for s in samples), default=None
        ),
        "peak_gpu_utilization_percent": max(
            (s["gpu_utilization_percent"] for s in samples), default=None
        ),
        "first_sample": samples[0] if samples else None,
        "last_sample": samples[-1] if samples else None,
    }


def parse_memory_bytes(value: str) -> int:
    match = re.fullmatch(r"\s*([0-9.]+)\s*(B|kB|KB|KiB|MB|MiB|GB|GiB|TB|TiB)\s*", value)
    if not match:
        raise ValueError(f"unrecognized Docker memory value {value!r}")
    scale = {
        "B": 1,
        "kB": 1000,
        "KB": 1000,
        "KiB": 1024,
        "MB": 1000**2,
        "MiB": 1024**2,
        "GB": 1000**3,
        "GiB": 1024**3,
        "TB": 1000**4,
        "TiB": 1024**4,
    }[match.group(2)]
    return int(float(match.group(1)) * scale)


def sample_docker_stats(
    path: Path, host_path: Path, stop_event: threading.Event
) -> None:
    with (
        path.open("x", encoding="utf-8") as samples_file,
        host_path.open("x", encoding="utf-8") as host_file,
    ):
        while not stop_event.is_set():
            timestamp = datetime.now(timezone.utc).isoformat()
            try:
                result = subprocess.run(
                    [
                        "docker",
                        "stats",
                        "--no-stream",
                        "--format",
                        "{{.MemUsage}},{{.CPUPerc}}",
                        "ollama",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True,
                )
                memory, cpu = result.stdout.strip().split(",", maxsplit=1)
                used, limit = memory.split("/", maxsplit=1)
                samples_file.write(
                    f"{timestamp},{parse_memory_bytes(used)},{parse_memory_bytes(limit)},"
                    f"{cpu.strip().removesuffix('%')}\n"
                )
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                samples_file.write(f"{timestamp},ERROR,{type(exc).__name__}\n")
            samples_file.flush()
            try:
                memory_info = {}
                for line in (
                    Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
                ):
                    key, value = line.split(":", maxsplit=1)
                    if key in {"MemTotal", "MemAvailable"}:
                        memory_info[key] = int(value.strip().split()[0]) * 1024
                total = memory_info["MemTotal"]
                available = memory_info["MemAvailable"]
                host_file.write(
                    f"{timestamp},{total},{available},{total - available}\n"
                )
            except (OSError, KeyError, ValueError) as exc:
                host_file.write(f"{timestamp},ERROR,{type(exc).__name__}\n")
            host_file.flush()
            stop_event.wait(1)


def docker_stats_summary(path: Path) -> dict:
    values = []
    errors = 0
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            fields = line.split(",")
            if len(fields) == 4 and fields[1] != "ERROR":
                try:
                    values.append(
                        {
                            "timestamp": fields[0],
                            "memory_used_bytes": int(fields[1]),
                            "memory_limit_bytes": int(fields[2]),
                            "cpu_percent": float(fields[3]),
                        }
                    )
                except ValueError:
                    errors += 1
            else:
                errors += 1
    return {
        "sample_count": len(values),
        "error_count": errors,
        "peak_memory_used_bytes": max(
            (sample["memory_used_bytes"] for sample in values), default=None
        ),
        "first_sample": values[0] if values else None,
        "last_sample": values[-1] if values else None,
    }


def host_memory_summary(path: Path) -> dict:
    values = []
    errors = 0
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            fields = line.split(",")
            if len(fields) == 4 and fields[1] != "ERROR":
                try:
                    values.append(
                        {
                            "timestamp": fields[0],
                            "total_bytes": int(fields[1]),
                            "available_bytes": int(fields[2]),
                            "used_bytes": int(fields[3]),
                        }
                    )
                except ValueError:
                    errors += 1
            else:
                errors += 1
    return {
        "sample_count": len(values),
        "error_count": errors,
        "peak_used_bytes": max(
            (sample["used_bytes"] for sample in values), default=None
        ),
        "minimum_available_bytes": min(
            (sample["available_bytes"] for sample in values), default=None
        ),
        "first_sample": values[0] if values else None,
        "last_sample": values[-1] if values else None,
    }


def run(
    model: str,
    base_url: str,
    run_dir: Path,
    cases: list[dict],
    prompt_path: Path = PROMPT,
    prompt_version: str = "v1",
    case_file: Path = CORPUS,
) -> int:
    private_root = (ROOT / "private/m05a").resolve()
    run_dir = run_dir.resolve()
    if not run_dir.is_relative_to(private_root):
        raise ValueError(f"run directory must be under {private_root}")
    run_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(run_dir, 0o700)
    results_path = run_dir / "results.jsonl"
    if results_path.exists():
        raise ValueError(f"refusing to overwrite {results_path}")

    identity = model_identity(base_url, model)
    started_at = datetime.now(timezone.utc).isoformat()
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "started_at_utc": started_at,
                "ollama_base_url": base_url,
                "ollama_version": post_json(base_url, "/api/version"),
                "model": identity,
                "prompt_version": prompt_version,
                "case_file": str(case_file),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    prompt = system_prompt(prompt_path)
    runtime_stop = threading.Event()
    runtime_sampler = threading.Thread(
        target=sample_docker_stats,
        args=(
            run_dir / "docker-samples.csv",
            run_dir / "host-memory-samples.csv",
            runtime_stop,
        ),
        name="m05a-runtime-stats",
        daemon=True,
    )
    runtime_sampler.start()
    gpu_sample_file = (run_dir / "gpu-samples.csv").open("x", encoding="utf-8")
    sampler_error = None
    try:
        sampler = subprocess.Popen(
            [
                "nvidia-smi",
                "--query-gpu=timestamp,memory.used,memory.free,utilization.gpu",
                "--format=csv,noheader,nounits",
                "-l",
                "1",
            ],
            stdout=gpu_sample_file,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        sampler = None
        sampler_error = f"{type(exc).__name__}: {exc}"
    rows = []
    loaded_models = []
    placement_error = None
    unload_error = None
    try:
        with results_path.open("x", encoding="utf-8") as output_file:
            for case in cases:
                try:
                    result, _ = generate_one(base_url, model, prompt, case)
                except (
                    urllib.error.URLError,
                    TimeoutError,
                    RuntimeError,
                    ValueError,
                ) as exc:
                    result = {
                        "case_id": case["id"],
                        "response": None,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                rows.append(result)
                if (
                    not result.get("error")
                    and not loaded_models
                    and not placement_error
                ):
                    try:
                        loaded_models = post_json(base_url, "/api/ps").get("models", [])
                    except (
                        urllib.error.URLError,
                        TimeoutError,
                        RuntimeError,
                        ValueError,
                    ) as exc:
                        placement_error = f"{type(exc).__name__}: {exc}"
                output_file.write(json.dumps(result, ensure_ascii=False) + "\n")
                output_file.flush()
                print(
                    f"{len(rows)}/{len(cases)} {case['id']} "
                    f"{'ERROR' if result.get('error') else 'recorded'}",
                    flush=True,
                )
                if result.get("error"):
                    break
    finally:
        if sampler is not None:
            sampler.terminate()
            try:
                sampler.wait(timeout=5)
            except subprocess.TimeoutExpired:
                sampler.kill()
                sampler.wait(timeout=5)
        gpu_sample_file.close()
        runtime_stop.set()
        runtime_sampler.join(timeout=6)
        try:
            unload(base_url, model)
        except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as exc:
            unload_error = f"{type(exc).__name__}: {exc}"
    summary = summarize(
        run_dir, identity, rows, started_at, loaded_models, placement_error
    )
    summary["prompt_version"] = prompt_version
    summary["unload_error"] = unload_error
    summary["gpu_sampler_error"] = sampler_error
    try:
        summary["models_loaded_after_unload"] = post_json(base_url, "/api/ps").get(
            "models", []
        )
    except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError) as exc:
        summary["models_loaded_after_unload_error"] = f"{type(exc).__name__}: {exc}"
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if len(rows) != len(cases) or unload_error else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate", action="store_true", help="validate corpus and prompt only"
    )
    parser.add_argument("--model", help="exact installed Ollama model tag")
    parser.add_argument(
        "--case-id",
        action="append",
        help="run only this case; repeat the option to select multiple cases",
    )
    parser.add_argument("--case-file", type=Path, default=CORPUS)
    parser.add_argument("--prompt", type=Path, default=PROMPT)
    parser.add_argument("--prompt-version", default="v1")
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument(
        "--run-dir", type=Path, help="new output directory under private/m05a"
    )
    args = parser.parse_args(argv)
    try:
        cases = read_cases(args.case_file)
        errors = validate_cases(
            cases, require_corpus_coverage=args.case_file.resolve() == CORPUS.resolve()
        )
        system_prompt(args.prompt)
        if errors:
            for error in errors:
                print(error, file=sys.stderr)
            return 2
        if args.validate:
            print(
                f"valid: {len(cases)} cases; prompt {args.prompt_version}; no runtime contacted"
            )
            return 0
        if not args.model or not args.run_dir:
            parser.error("--model and --run-dir are required unless --validate is used")
        if args.case_id:
            selected = set(args.case_id)
            known = {case["id"] for case in cases}
            unknown = selected - known
            if unknown:
                parser.error(f"unknown --case-id value(s): {sorted(unknown)}")
            cases = [case for case in cases if case["id"] in selected]
        return run(
            args.model,
            args.base_url,
            args.run_dir,
            cases,
            args.prompt,
            args.prompt_version,
            args.case_file,
        )
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
