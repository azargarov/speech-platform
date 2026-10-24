import threading
import time
import unittest

from services.stt.admission import AdmissionController, UploadGate
from services.stt.domain import (
    FailureCode,
    OperationContext,
    SpeechFailure,
    TranscriptionRequest,
    TranscriptionResult,
)


def request(value=b"x"):
    return TranscriptionRequest(value, "audio/wav")


class AdmissionTests(unittest.TestCase):
    def controller(self, execute, *, queued=2, queued_bytes=10, retained=20, wait=1):
        controller = AdmissionController(
            execute,
            queued,
            queued_bytes,
            retained,
            10,
            wait,
            2,
            20,
        )
        controller.start()
        self.addCleanup(lambda: controller.close(0.5))
        return controller

    def test_fifo_and_exact_queue_item_byte_and_retained_boundaries(self):
        entered = threading.Event()
        release = threading.Event()
        order = []

        def execute(item, _context):
            order.append(item.audio)
            if item.audio == b"a":
                entered.set()
                release.wait(2)
            return TranscriptionResult(item.audio.decode(), "en")

        controller = self.controller(execute, queued=2, queued_bytes=4, retained=6)
        errors = []
        first = threading.Thread(
            target=lambda: self._submit(controller, request(b"a"), errors)
        )
        first.start()
        self.assertTrue(entered.wait(2))
        second = threading.Thread(
            target=lambda: self._submit(controller, request(b"bb"), errors)
        )
        second.start()
        self._wait(lambda: controller.snapshot()["queued"] == 1)
        third = threading.Thread(
            target=lambda: self._submit(controller, request(b"cc"), errors)
        )
        third.start()
        self._wait(lambda: controller.snapshot()["queued"] == 2)
        with self.assertRaises(SpeechFailure) as count_full:
            controller.submit(request(b"z"), OperationContext())
        self.assertEqual(count_full.exception.code, FailureCode.OVERLOADED)
        self.assertEqual(controller.snapshot()["queued_bytes"], 4)
        self.assertEqual(controller.snapshot()["retained_bytes"], 5)
        release.set()
        for thread in (first, second, third):
            thread.join(2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(order, [b"a", b"bb", b"cc"])
        self.assertFalse(errors)
        self.assertEqual(controller.snapshot()["retained_bytes"], 0)

    def test_queue_byte_budget_and_request_limit(self):
        entered = threading.Event()
        release = threading.Event()

        def execute(_request, _context):
            entered.set()
            release.wait(2)
            return TranscriptionResult("ok", "en")

        controller = self.controller(execute, queued=3, queued_bytes=2, retained=8)
        first = threading.Thread(
            target=lambda: self._submit(controller, request(b"1"), [])
        )
        first.start()
        self.assertTrue(entered.wait(2))
        second = threading.Thread(
            target=lambda: self._submit(controller, request(b"22"), [])
        )
        second.start()
        self._wait(lambda: controller.snapshot()["queued"] == 1)
        with self.assertRaises(SpeechFailure) as queued_limit:
            controller.submit(request(b"x"), OperationContext())
        self.assertEqual(queued_limit.exception.code, FailureCode.OVERLOADED)
        with self.assertRaises(SpeechFailure) as request_limit:
            controller.submit(request(b"01234567890"), OperationContext())
        self.assertEqual(request_limit.exception.code, FailureCode.INPUT_LIMIT)
        release.set()
        first.join(2)
        second.join(2)

    def test_retained_audio_budget_includes_active_job(self):
        entered = threading.Event()
        release = threading.Event()

        def execute(_request, _context):
            entered.set()
            release.wait(2)
            return TranscriptionResult("ok", "en")

        controller = self.controller(execute, queued=2, queued_bytes=8, retained=2)
        first = threading.Thread(
            target=lambda: self._submit(controller, request(b"a"), [])
        )
        first.start()
        self.assertTrue(entered.wait(2))
        second = threading.Thread(
            target=lambda: self._submit(controller, request(b"b"), [])
        )
        second.start()
        self._wait(lambda: controller.snapshot()["queued"] == 1)
        with self.assertRaises(SpeechFailure) as retained_limit:
            controller.submit(request(b"c"), OperationContext())
        self.assertEqual(retained_limit.exception.code, FailureCode.OVERLOADED)
        self.assertEqual(controller.snapshot()["retained_bytes"], 2)
        release.set()
        first.join(2)
        second.join(2)

    def test_queue_expiration_releases_bytes_while_active_work_continues(self):
        entered = threading.Event()
        release = threading.Event()

        def execute(_request, _context):
            entered.set()
            release.wait(2)
            return TranscriptionResult("ok", "en")

        controller = self.controller(execute, queued=2, wait=0.08)
        first = threading.Thread(
            target=lambda: self._submit(controller, request(b"a"), [])
        )
        first.start()
        self.assertTrue(entered.wait(2))
        captured = []

        def submit_expiring():
            try:
                controller.submit(request(b"b"), OperationContext())
            except SpeechFailure as exc:
                captured.append(exc.code)

        second = threading.Thread(target=submit_expiring)
        second.start()
        second.join(1)
        self.assertFalse(second.is_alive())
        self.assertEqual(captured, [FailureCode.OVERLOADED])
        self.assertEqual(controller.snapshot()["retained_bytes"], 1)
        release.set()
        first.join(2)

    def test_queued_client_cancellation_releases_exactly_once(self):
        entered = threading.Event()
        release = threading.Event()

        def execute(_request, context):
            entered.set()
            while not release.is_set():
                context.check()
                time.sleep(0.005)
            return TranscriptionResult("ok", "en")

        controller = self.controller(execute)
        first = threading.Thread(
            target=lambda: self._submit(controller, request(b"a"), [])
        )
        first.start()
        self.assertTrue(entered.wait(2))
        context = OperationContext()
        captured = []

        def queued():
            try:
                controller.submit(request(b"b"), context)
            except SpeechFailure as exc:
                captured.append(exc.code)

        second = threading.Thread(target=queued)
        second.start()
        self._wait(lambda: controller.snapshot()["queued"] == 1)
        context.cancel()
        second.join(1)
        self.assertFalse(second.is_alive())
        self.assertEqual(captured, [FailureCode.CANCELLED])
        self.assertEqual(controller.snapshot()["queued_bytes"], 0)
        self.assertEqual(controller.snapshot()["retained_bytes"], 1)
        release.set()
        first.join(2)
        self.assertEqual(controller.snapshot()["retained_bytes"], 0)

    def test_active_deadline_and_graceful_shutdown_release_resources(self):
        started = threading.Event()

        def execute(_request, context):
            started.set()
            while True:
                context.check()
                time.sleep(0.005)

        controller = self.controller(execute)
        context = OperationContext(time.monotonic() + 0.1)
        captured = []
        thread = threading.Thread(
            target=lambda: self._capture(controller, request(), context, captured)
        )
        thread.start()
        self.assertTrue(started.wait(1))
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(captured, [FailureCode.DEADLINE_EXCEEDED])
        # Caller completion no longer implies execution/cleanup completion.
        self._wait(lambda: not controller.snapshot()["active"])
        self.assertEqual(controller.snapshot()["retained_bytes"], 0)

        blocked = threading.Event()
        entered = threading.Event()

        def drainable(_request, context):
            entered.set()
            while not blocked.is_set():
                context.check()
                time.sleep(0.005)
            return TranscriptionResult("ok", "en")

        draining = AdmissionController(drainable, 1, 8, 8, 8, 1, 1, 8)
        draining.start()
        caller = threading.Thread(target=lambda: self._submit(draining, request(), []))
        caller.start()
        self.assertTrue(entered.wait(1))
        draining.close(0.05)
        caller.join(1)
        self.assertFalse(caller.is_alive())
        self.assertEqual(draining.snapshot()["retained_bytes"], 0)

    def test_completion_cancel_race_releases_once_and_uncertain_cleanup_retains_owner(
        self,
    ):
        entered = threading.Event()
        release_result = threading.Event()

        def finish_after_cancel(_request, _context):
            entered.set()
            self.assertTrue(release_result.wait(2))
            return TranscriptionResult("ok", "en")

        controller = self.controller(finish_after_cancel)
        context = OperationContext()
        captured = []
        caller = threading.Thread(
            target=lambda: self._capture(
                controller, request(b"race"), context, captured
            )
        )
        caller.start()
        self.assertTrue(entered.wait(1))
        context.cancel()
        release_result.set()
        caller.join(1)
        self.assertFalse(caller.is_alive())
        self.assertEqual(captured, [FailureCode.CANCELLED])
        self.assertEqual(controller.snapshot()["retained_bytes"], 0)
        self.assertGreaterEqual(controller.snapshot()["queued_bytes"], 0)
        self.assertGreaterEqual(controller.snapshot()["retained_bytes"], 0)

        cleanup_event = threading.Event()

        def uncertain(_request, _context):
            raise SpeechFailure(
                FailureCode.DEADLINE_EXCEEDED,
                "private diagnostic must stay internal",
                retain_resources=True,
            )

        deferred = AdmissionController(uncertain, 1, 8, 8, 8, 1, 1, 8, cleanup_event)
        deferred.start()
        with self.assertRaises(SpeechFailure):
            deferred.submit(request(b"owned"), OperationContext())
        deferred.latch_fault()
        snapshot = deferred.snapshot()
        self.assertTrue(snapshot["active"])
        self.assertEqual(snapshot["retained_bytes"], 5)
        self.assertEqual(snapshot["queued_bytes"], 0)
        self.assertGreaterEqual(snapshot["retained_bytes"], 0)
        with self.assertRaises(SpeechFailure):
            deferred.submit(request(b"blocked"), OperationContext())
        cleanup_event.set()
        self._wait(lambda: deferred.snapshot()["retained_bytes"] == 0)
        self.assertFalse(deferred.snapshot()["active"])
        self.assertGreaterEqual(deferred.snapshot()["retained_bytes"], 0)
        deferred.close(0.5)

    def test_upload_gate_has_exact_concurrency_bound_and_closes(self):
        gate = UploadGate(1, 8, 8, 8)
        with gate.acquire() as lease:
            lease.write(b"1234")
            self.assertEqual(gate.snapshot()["upload_bytes"], 4)
            with self.assertRaises(SpeechFailure) as full:
                with gate.acquire():
                    pass
            self.assertEqual(full.exception.code, FailureCode.OVERLOADED)
            with self.assertRaises(SpeechFailure):
                lease.write(b"12345")
        lease.close()
        gate.close()
        self.assertEqual(gate.snapshot()["upload_bytes"], 0)
        self.assertEqual(gate.snapshot()["active_uploads"], 0)
        with self.assertRaises(RuntimeError):
            gate.release_retained(1)
        self.assertEqual(gate.snapshot()["retained_bytes"], 0)
        with self.assertRaises(SpeechFailure) as closed:
            with gate.acquire():
                pass
        self.assertEqual(closed.exception.code, FailureCode.NOT_READY)

    @staticmethod
    def _submit(controller, item, errors):
        try:
            controller.submit(item, OperationContext(time.monotonic() + 4))
        except Exception as exc:
            errors.append(exc)

    @staticmethod
    def _capture(controller, item, context, captured):
        try:
            controller.submit(item, context)
        except SpeechFailure as exc:
            captured.append(exc.code)

    @staticmethod
    def _wait(predicate):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.005)
        raise AssertionError("condition did not become true")


if __name__ == "__main__":
    unittest.main()
