import asyncio
import json
import threading
import time
import unittest
from types import SimpleNamespace

from aiohttp import FormData
from aiohttp.payload import AsyncIterablePayload
from aiohttp.test_utils import TestClient, TestServer

from services.stt.admission import UploadGate
from services.stt.domain import (
    FailureCode,
    OperationContext,
    SpeechFailure,
    TranscriptionResult,
)
from services.stt.http_server import (
    _validate_empty_warmup_body,
    create_http_app,
)


class FakeLifecycle:
    def __init__(self):
        self.is_ready = True
        self.is_cleanup_unconfirmed = False

    def ready(self):
        return self.is_ready

    def cleanup_unconfirmed(self):
        return self.is_cleanup_unconfirmed


class FakeApplication:
    def __init__(
        self,
        *,
        block_until_cancel=False,
        block_warmup=False,
        max_uploads=2,
        failure=None,
    ):
        self.config = SimpleNamespace(
            admission=SimpleNamespace(
                max_request_bytes=1024,
                max_upload_bytes=1024,
                max_retained_audio_bytes=1024,
                request_timeout_seconds=5,
            )
        )
        self.lifecycle = FakeLifecycle()
        self.uploads = UploadGate(max_uploads, 1024, 1024, 1024)
        self.block_until_cancel = block_until_cancel
        self.block_warmup = block_warmup
        self.failure = failure
        self.started = threading.Event()
        self.warmup_done = threading.Event()
        self.release_warmup = threading.Event()
        self.cancelled = threading.Event()

    def start(self):
        return None

    def close(self):
        self.uploads.close()

    def acquire_upload(self):
        return self.uploads.acquire()

    def transcribe_uploaded(
        self,
        lease,
        media_type,
        model=None,
        language="auto",
        timestamps=False,
        context=None,
        output_language="auto",
    ):
        lease.finish()
        if self.failure is not None:
            raise self.failure
        if self.block_until_cancel:
            self.started.set()
            while not context.cancelled():
                time.sleep(0.005)
            self.cancelled.set()
            raise SpeechFailure(FailureCode.DEADLINE_EXCEEDED)
        return TranscriptionResult(
            "synthetic transcript",
            "en",
            () if timestamps else None,
        )

    def warmup(self, context=None):
        if self.failure is not None:
            raise self.failure
        self.started.set()
        if self.block_warmup:
            self.release_warmup.wait(2)
        self.warmup_done.set()
        return {"model_state": "ready"}


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.application = FakeApplication()
        self.client = TestClient(TestServer(create_http_app(self.application)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    @staticmethod
    def form(*, timestamps="true"):
        form = FormData()
        form.add_field(
            "audio", b"synthetic audio", filename="sample.wav", content_type="audio/wav"
        )
        form.add_field("language", "auto")
        form.add_field("model", "smoke-small")
        form.add_field("timestamps", timestamps)
        form.add_field("stream", "false")
        return form

    async def test_private_transcription_contract_and_metrics(self):
        response = await self.client.post(
            "/internal/v1/transcriptions",
            data=self.form(),
            headers={"X-Request-Timeout-Ms": "4000"},
        )
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(body["text"], "synthetic transcript")
        self.assertEqual(body["language"], "en")
        self.assertIn("segments", body)
        metrics = await self.client.get("/metrics")
        metrics_body = await metrics.text()
        self.assertIn('speech_stt_requests_total{outcome="success"} 1', metrics_body)
        self.assertNotIn("synthetic transcript", metrics_body)

    async def test_internal_warmup_empty_body_repeat_and_validation(self):
        headers = {"X-Request-Timeout-Ms": "4000"}
        first = await self.client.post("/internal/v1/warmup", headers=headers)
        second = await self.client.post("/internal/v1/warmup", headers=headers)
        self.assertEqual(first.status, 200)
        self.assertEqual(await first.json(), {"model_state": "ready"})
        self.assertEqual(second.status, 200)
        invalid = await self.client.post(
            "/internal/v1/warmup", data=b"user content", headers=headers
        )
        self.assertEqual(invalid.status, 400)

    async def test_warmup_missing_and_malformed_timeout_are_sanitized_json(self):
        for headers in (
            {},
            {"X-Request-Timeout-Ms": "not-a-number"},
            {"X-Request-Timeout-Ms": "9" * 40},
            {"X-Request-Timeout-Ms": "0"},
        ):
            response = await self.client.post("/internal/v1/warmup", headers=headers)
            self.assertEqual(response.status, 400)
            body = await response.json()
            self.assertEqual(body["code"], "invalid_input")
            self.assertNotIn("invalid timeout", body["message"])
        self.assertFalse(self.application.started.is_set())

    async def test_warmup_oversized_and_chunked_body_rejected_before_loading(self):
        headers = {"X-Request-Timeout-Ms": "1000"}
        oversized = await self.client.post(
            "/internal/v1/warmup", data=b"x" * 2048, headers=headers
        )
        self.assertEqual(oversized.status, 413)
        self.assertEqual((await oversized.json())["code"], "input_limit")

        async def chunks():
            yield b""

        chunked = await self.client.post(
            "/internal/v1/warmup",
            data=AsyncIterablePayload(chunks()),
            headers=headers,
        )
        self.assertEqual(chunked.status, 400)
        self.assertEqual((await chunked.json())["code"], "invalid_input")
        self.assertFalse(self.application.started.is_set())

    async def test_warmup_stalled_unknown_length_body_is_bounded(self):
        class StalledStream:
            async def read(self, _size):
                await asyncio.Event().wait()

        request = SimpleNamespace(
            content_length=None,
            headers={},
            can_read_body=True,
            content=StalledStream(),
        )
        with self.assertRaises(SpeechFailure) as caught:
            await _validate_empty_warmup_body(
                request,
                OperationContext(time.monotonic() + 0.05),
                1024,
            )
        self.assertEqual(caught.exception.code, FailureCode.DEADLINE_EXCEEDED)
        self.assertFalse(self.application.started.is_set())

    async def test_warmup_http_timeout_does_not_cancel_model_load(self):
        await self.client.close()
        self.application = FakeApplication(block_warmup=True)
        self.client = TestClient(TestServer(create_http_app(self.application)))
        await self.client.start_server()
        response = await self.client.post(
            "/internal/v1/warmup", headers={"X-Request-Timeout-Ms": "1"}
        )
        self.assertEqual(response.status, 504)
        self.assertEqual((await response.json())["code"], "deadline_exceeded")
        self.assertTrue(self.application.started.is_set())
        self.application.release_warmup.set()
        self.assertTrue(
            await asyncio.wait_for(
                asyncio.to_thread(self.application.warmup_done.wait), 1
            )
        )

    async def test_source_language_alias_conflict_is_rejected(self):
        form = self.form(timestamps="false")
        form.add_field("source_language", "ru")
        response = await self.client.post(
            "/internal/v1/transcriptions",
            data=form,
            headers={"X-Request-Timeout-Ms": "4000"},
        )
        self.assertEqual(response.status, 400)
        self.assertEqual((await response.json())["code"], "invalid_input")

    async def test_bad_timeout_and_unsupported_stream_are_safe_json(self):
        bad_timeout = await self.client.post(
            "/internal/v1/transcriptions",
            data=self.form(),
            headers={"X-Request-Timeout-Ms": "zero"},
        )
        self.assertEqual(bad_timeout.status, 400)
        self.assertEqual((await bad_timeout.json())["code"], "invalid_input")
        form = self.form()
        form.add_field("extra", "forbidden")
        # A duplicate/unknown field is rejected before inference starts.
        invalid = await self.client.post(
            "/internal/v1/transcriptions",
            data=form,
            headers={"X-Request-Timeout-Ms": "1000"},
        )
        self.assertEqual(invalid.status, 400)

    async def test_request_disconnect_cancels_inference_context(self):
        await self.client.close()
        self.application = FakeApplication(block_until_cancel=True)
        self.client = TestClient(TestServer(create_http_app(self.application)))
        await self.client.start_server()
        task = asyncio.create_task(
            self.client.post(
                "/internal/v1/transcriptions",
                data=self.form(timestamps="false"),
                headers={"X-Request-Timeout-Ms": "4000"},
            )
        )
        started = await asyncio.wait_for(
            asyncio.to_thread(self.application.started.wait, 2), 3
        )
        self.assertTrue(started)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        cancelled = await asyncio.wait_for(
            asyncio.to_thread(self.application.cancelled.wait, 2), 3
        )
        self.assertTrue(cancelled)

    async def test_invalid_audio_failure_uses_safe_public_error(self):
        await self.client.close()
        self.application = FakeApplication(
            failure=SpeechFailure(
                FailureCode.DECODE_FAILED,
                "private /srv/audio/russian.m4a token=secret-value transcript text",
            )
        )
        self.client = TestClient(TestServer(create_http_app(self.application)))
        await self.client.start_server()
        response = await self.client.post(
            "/internal/v1/transcriptions",
            data=self.form(),
            headers={"X-Request-Timeout-Ms": "4000"},
        )
        body = await response.json()
        self.assertEqual(response.status, 422)
        self.assertEqual(body["code"], "decode_failed")
        self.assertEqual(body["message"], "audio could not be decoded")
        self.assertNotIn("/srv/audio", json.dumps(body))
        self.assertNotIn("secret-value", json.dumps(body))
        self.assertNotIn("transcript text", json.dumps(body))

    async def test_resource_exhaustion_uses_bounded_safe_http_error(self):
        await self.client.close()
        self.application = FakeApplication(
            failure=SpeechFailure(
                FailureCode.RESOURCE_EXHAUSTED,
                "allocator at /private/audio/russian.m4a token=secret-value",
            )
        )
        self.client = TestClient(TestServer(create_http_app(self.application)))
        await self.client.start_server()
        response = await self.client.post(
            "/internal/v1/transcriptions",
            data=self.form(),
            headers={"X-Request-Timeout-Ms": "4000"},
        )
        body = await response.json()
        self.assertEqual(response.status, 503)
        self.assertEqual(body["code"], "resource_exhausted")
        self.assertEqual(body["message"], "service resource limit was exceeded")
        self.assertNotIn("allocator", json.dumps(body))
        self.assertNotIn("secret-value", json.dumps(body))

    async def test_upload_admission_limit_is_enforced_over_http(self):
        await self.client.close()
        self.application = FakeApplication(block_until_cancel=True, max_uploads=1)
        self.client = TestClient(TestServer(create_http_app(self.application)))
        await self.client.start_server()
        first = asyncio.create_task(
            self.client.post(
                "/internal/v1/transcriptions",
                data=self.form(timestamps="false"),
                headers={"X-Request-Timeout-Ms": "500"},
            )
        )
        started = await asyncio.wait_for(
            asyncio.to_thread(self.application.started.wait, 2), 3
        )
        self.assertTrue(started)
        limited = await self.client.post(
            "/internal/v1/transcriptions",
            data=self.form(),
            headers={"X-Request-Timeout-Ms": "4000"},
        )
        self.assertEqual(limited.status, 429)
        self.assertEqual((await limited.json())["code"], "overloaded")
        completed = await first
        self.assertEqual(completed.status, 504)
        cancelled = await asyncio.wait_for(
            asyncio.to_thread(self.application.cancelled.wait, 2), 3
        )
        self.assertTrue(cancelled)

    async def test_request_deadline_cancels_work_and_returns_gateway_timeout(self):
        await self.client.close()
        self.application = FakeApplication(block_until_cancel=True)
        self.client = TestClient(TestServer(create_http_app(self.application)))
        await self.client.start_server()
        request = asyncio.create_task(
            self.client.post(
                "/internal/v1/transcriptions",
                data=self.form(timestamps="false"),
                headers={"X-Request-Timeout-Ms": "100"},
            )
        )
        started = await asyncio.wait_for(
            asyncio.to_thread(self.application.started.wait, 2), 3
        )
        self.assertTrue(started)
        response = await request
        self.assertEqual(response.status, 504)
        self.assertEqual((await response.json())["code"], "deadline_exceeded")
        cancelled = await asyncio.wait_for(
            asyncio.to_thread(self.application.cancelled.wait, 2), 3
        )
        self.assertTrue(cancelled)

    async def test_health_and_readiness_are_distinct(self):
        self.application.lifecycle.is_ready = False
        health = await self.client.get("/healthz")
        ready = await self.client.get("/readyz")
        self.assertEqual(health.status, 200)
        self.assertEqual(ready.status, 503)
        self.assertEqual((await ready.json())["code"], "not_ready")
        self.application.lifecycle.is_cleanup_unconfirmed = True
        cleanup = await self.client.get("/readyz")
        self.assertEqual(cleanup.status, 503)
        self.assertEqual((await cleanup.json())["code"], "cleanup_unconfirmed")
        self.application.lifecycle.is_cleanup_unconfirmed = False
        self.application.lifecycle.is_ready = True
        self.assertEqual((await self.client.get("/readyz")).status, 200)


if __name__ == "__main__":
    unittest.main()
