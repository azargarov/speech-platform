"""Run an offline real-model CPU smoke test using operator-provisioned files."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from services.stt.config import load_application_config, load_deployment_config
from services.stt.http_server import create_http_app
from services.stt.service import DeferredApplication


def main():
    app_path = os.environ["STT_APPLICATION_CONFIG"]
    deployment_path = os.environ["STT_DEPLOYMENT_CONFIG"]
    audio_path = Path(os.environ["STT_SMOKE_AUDIO"])
    if not audio_path.is_file():
        raise SystemExit("STT_SMOKE_AUDIO must name a local readable audio file")
    config = load_application_config(app_path)
    deployment = load_deployment_config(deployment_path)
    if config.device_mode != "cpu":
        raise SystemExit("CPU smoke test requires device_policy.mode: cpu")
    if audio_path.stat().st_size > config.admission.max_request_bytes:
        raise SystemExit("smoke audio exceeds configured request byte limit")
    application = DeferredApplication(config, deployment)
    result = asyncio.run(_exercise_http(application, config, audio_path))
    load_seconds = result.pop("model_load_seconds")
    inference_seconds = result.pop("inference_seconds")
    child_alive_after_close = result.pop("child_alive_after_close")
    if child_alive_after_close:
        raise SystemExit("inference subprocess remained alive after cleanup")
    print(
        json.dumps(
            {
                "event": "stt_cpu_smoke_pass",
                "model_alias": config.default_model,
                "model_revision": config.models[0].identity.upstream_revision,
                "manifest_sha256": config.models[0].manifest_sha256,
                "model_load_seconds": round(load_seconds, 6),
                "inference_seconds": round(inference_seconds, 6),
                "child_alive_after_close": child_alive_after_close,
                **result,
            },
            sort_keys=True,
        )
    )


async def _exercise_http(application, config, audio_path):
    client = TestClient(TestServer(create_http_app(application)))
    audio = audio_path.read_bytes()
    result = None
    try:
        started = time.monotonic()
        await client.start_server()
        health = await client.get("/healthz")
        if health.status != 200 or (await health.json()).get("status") != "alive":
            raise SystemExit("worker health endpoint did not report alive")
        initial_ready = await client.get("/readyz")
        initial_ready_status = initial_ready.status
        deadline = started + config.lifecycle.model_load_timeout_seconds + 10
        while True:
            ready = await client.get("/readyz")
            if ready.status == 200:
                break
            if time.monotonic() >= deadline:
                raise SystemExit("configured local model did not become ready")
            await asyncio.sleep(0.05)
        load_seconds = time.monotonic() - started

        form = _form(audio, audio_path, config.default_model)
        inference_started = time.monotonic()
        response = await client.post(
            "/internal/v1/transcriptions",
            data=form,
            headers={
                "X-Request-Timeout-Ms": str(
                    int(config.admission.request_timeout_seconds * 1000)
                )
            },
        )
        if response.status != 200:
            raise SystemExit("private transcription endpoint returned an error")
        body = await response.json()
        inference_seconds = time.monotonic() - inference_started
        _validate_result(body, config.audio_limits.max_duration_seconds)
        expected_language = os.environ.get("STT_EXPECTED_LANGUAGE")
        if expected_language and body["language"].lower() != expected_language.lower():
            raise SystemExit(
                "transcription language differed from STT_EXPECTED_LANGUAGE"
            )

        invalid_form = _form(audio, audio_path, "unknown-smoke-alias")
        invalid = await client.post(
            "/internal/v1/transcriptions",
            data=invalid_form,
            headers={"X-Request-Timeout-Ms": "5000"},
        )
        if (
            invalid.status != 404
            or (await invalid.json()).get("code") != "unknown_model"
        ):
            raise SystemExit("unknown model HTTP error contract did not match")
        metrics = await client.get("/metrics")
        metrics_body = await metrics.text()
        if "synthetic transcript" in metrics_body or body["text"] in metrics_body:
            raise SystemExit("transcript content appeared in metrics")
        result = {
            "language": body["language"],
            "segments": len(body["segments"]),
            "health_status": health.status,
            "initial_ready_status": initial_ready_status,
            "ready_status": ready.status,
            "unknown_alias_status": invalid.status,
            "model_load_seconds": load_seconds,
            "inference_seconds": inference_seconds,
        }
    finally:
        await client.close()
        delegate = application._delegate
        if delegate is None:
            if result is not None:
                raise SystemExit("worker did not create an application delegate")
        elif result is not None:
            result["child_alive_after_close"] = delegate.runner.child_alive
    return result


def _form(audio, audio_path, alias):
    form = FormData()
    form.add_field(
        "audio",
        audio,
        filename=audio_path.name,
        content_type=_media_type(audio_path),
    )
    form.add_field("language", "auto")
    form.add_field("model", alias)
    form.add_field("timestamps", "true")
    form.add_field("stream", "false")
    return form


def _validate_result(body, maximum_duration):
    if set(body) != {"text", "language", "segments"}:
        raise SystemExit("transcription response schema was invalid")
    if not isinstance(body["text"], str) or not body["text"].strip():
        raise SystemExit("transcription response did not contain text")
    if not isinstance(body["language"], str) or not body["language"]:
        raise SystemExit("transcription response did not contain a language")
    if not isinstance(body["segments"], list) or not body["segments"]:
        raise SystemExit("transcription response did not contain timestamp segments")
    previous_end = 0
    for segment in body["segments"]:
        if set(segment) != {"start", "end", "text"}:
            raise SystemExit("segment response schema was invalid")
        start, end = segment["start"], segment["end"]
        if (
            not isinstance(start, (int, float))
            or not isinstance(end, (int, float))
            or start < previous_end
            or end < start
            or end > maximum_duration
            or not isinstance(segment["text"], str)
        ):
            raise SystemExit("segment timestamps were outside allowed bounds")
        previous_end = end


def _media_type(path):
    suffix = path.suffix.lower()
    return {
        ".wav": "audio/wav",
        ".flac": "audio/flac",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".m4a": "audio/mp4",
    }.get(suffix, "application/octet-stream")


if __name__ == "__main__":
    main()
