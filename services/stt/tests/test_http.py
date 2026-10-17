import asyncio
import threading
import time
import unittest
from types import SimpleNamespace

from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from services.stt.admission import UploadGate
from services.stt.domain import (
    FailureCode,
    SpeechFailure,
    TranscriptionResult,
)
from services.stt.http_server import create_http_app


class FakeLifecycle:
    def __init__(self):
        self.is_ready = True

    def ready(self):
        return self.is_ready

    def cleanup_unconfirmed(self):
        return False


class FakeApplication:
    def __init__(self, *, block_until_cancel=False):
        self.config = SimpleNamespace(
            admission=SimpleNamespace(
                max_request_bytes=1024,
                max_upload_bytes=1024,
                max_retained_audio_bytes=1024,
                request_timeout_seconds=5,
            )
        )
        self.lifecycle = FakeLifecycle()
        self.uploads = UploadGate(2, 1024, 1024, 1024)
        self.block_until_cancel = block_until_cancel
        self.started = threading.Event()
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
    ):
        lease.finish()
        if self.block_until_cancel:
            self.started.set()
            while not context.cancelled():
                time.sleep(0.005)
            self.cancelled.set()
            raise SpeechFailure(FailureCode.CANCELLED)
        return TranscriptionResult(
            "synthetic transcript",
            "en",
            () if timestamps else None,
        )


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


if __name__ == "__main__":
    unittest.main()
