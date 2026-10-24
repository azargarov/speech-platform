"""HTTP waiting must not own the lifetime of unfinished STT execution."""

import asyncio
import unittest
from types import SimpleNamespace

from services.stt.domain import FailureCode, OperationContext, SpeechFailure
from services.stt.http_server import _wait_for_result


class DeadlineWaitTests(unittest.IsolatedAsyncioTestCase):
    async def test_caller_stops_waiting_without_cancelling_owned_execution(self):
        for expired in (False, True):
            with self.subTest(expired=expired):
                entered, release = asyncio.Event(), asyncio.Event()

                async def execute():
                    entered.set()
                    await release.wait()
                    return "late result"

                task = asyncio.create_task(execute())
                await entered.wait()
                context = OperationContext(0 if expired else None)
                if not expired:
                    context.cancel()
                request = SimpleNamespace(
                    transport=SimpleNamespace(is_closing=lambda: False)
                )
                try:
                    with self.assertRaises(SpeechFailure) as caught:
                        await _wait_for_result(task, context, request)
                    self.assertEqual(
                        caught.exception.code,
                        FailureCode.DEADLINE_EXCEEDED
                        if expired
                        else FailureCode.CANCELLED,
                    )
                    self.assertFalse(task.cancelled())
                    self.assertFalse(task.done())
                finally:
                    release.set()
                    await task

    async def test_late_execution_failure_does_not_replace_expired_deadline(self):
        async def execute():
            raise SpeechFailure(FailureCode.NOT_READY)

        task = asyncio.create_task(execute())
        await asyncio.wait({task})
        request = SimpleNamespace(transport=SimpleNamespace(is_closing=lambda: False))
        with self.assertRaises(SpeechFailure) as caught:
            await _wait_for_result(task, OperationContext(0), request)
        self.assertEqual(caught.exception.code, FailureCode.DEADLINE_EXCEEDED)
        await asyncio.gather(task, return_exceptions=True)
