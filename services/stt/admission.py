"""Single-active-job FIFO admission with bounded byte ownership."""

from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field

from services.stt.domain import (
    FailureCode,
    OperationContext,
    SpeechFailure,
    TranscriptionRequest,
    TranscriptionResult,
)


@dataclass
class _Job:
    request: TranscriptionRequest
    context: OperationContext
    queue_deadline: float
    result: TranscriptionResult | None = None
    failure: SpeechFailure | None = None
    state: str = "new"
    finished: bool = False
    cleanup_pending: bool = False
    done: threading.Event = field(default_factory=threading.Event)


class UploadLease:
    def __init__(self, gate):
        self._gate = gate
        self._buffer = bytearray()
        self._reserved_bytes = 0
        self._finished = False
        self._transferred = False
        self._closed = False
        self._lock = threading.Lock()

    def write(self, chunk: bytes):
        with self._lock:
            if self._finished or self._closed or not isinstance(chunk, bytes):
                raise SpeechFailure(
                    FailureCode.INVALID_INPUT, "upload chunk is invalid"
                )
            next_size = len(self._buffer) + len(chunk)
            if next_size > self._gate._max_request_bytes:
                raise SpeechFailure(
                    FailureCode.INPUT_LIMIT, "audio exceeds configured request limit"
                )
            self._gate._reserve_upload_bytes(len(chunk))
            try:
                self._buffer.extend(chunk)
            except Exception:
                self._gate._release_upload_bytes(len(chunk))
                raise
            self._reserved_bytes += len(chunk)

    def finish(self):
        with self._lock:
            if self._finished or self._closed:
                raise SpeechFailure(
                    FailureCode.INVALID_INPUT, "upload is already finished"
                )
            if not self._buffer:
                raise SpeechFailure(
                    FailureCode.INVALID_INPUT, "audio must not be empty"
                )
            self._finished = True
            return self._buffer

    def transfer(self, size):
        with self._lock:
            if self._closed or not self._finished or size != self._reserved_bytes:
                raise SpeechFailure(
                    FailureCode.INVALID_INPUT, "upload ownership is incomplete"
                )
            self._gate._transfer_upload_to_retained(self, size)
            self._transferred = True
            self._closed = True
            self._buffer = bytearray()

    def owns(self, audio):
        with self._lock:
            return not self._closed and self._finished and audio is self._buffer

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._gate._close_lease(self, self._reserved_bytes)
            self._buffer.clear()
            self._closed = True


class UploadGate:
    """Bounded in-memory upload leases transferred into retained request ownership."""

    def __init__(
        self,
        maximum: int,
        max_upload_bytes: int,
        max_request_bytes: int,
        max_retained_bytes: int,
    ):
        self._maximum = maximum
        self._max_upload_bytes = max_upload_bytes
        self._max_request_bytes = max_request_bytes
        self._max_retained_bytes = max_retained_bytes
        self._active = 0
        self._upload_bytes = 0
        self._retained_bytes = 0
        self._accepting = True
        self._condition = threading.Condition()
        self._leases = set()

    @contextmanager
    def acquire(self):
        lease = UploadLease(self)
        with self._condition:
            if not self._accepting:
                raise SpeechFailure(FailureCode.NOT_READY, "worker is draining")
            if self._active >= self._maximum:
                raise SpeechFailure(FailureCode.OVERLOADED, "upload capacity is full")
            self._active += 1
            self._leases.add(lease)
        try:
            yield lease
        finally:
            lease.close()
            with self._condition:
                self._condition.notify_all()

    @property
    def retained_bytes(self):
        with self._condition:
            return self._retained_bytes

    def snapshot(self):
        with self._condition:
            return {
                "active_uploads": self._active,
                "upload_bytes": self._upload_bytes,
                "retained_bytes": self._retained_bytes,
            }

    def reserve_retained(self, size):
        with self._condition:
            if self._retained_bytes + size > self._max_retained_bytes:
                raise SpeechFailure(
                    FailureCode.OVERLOADED, "retained audio capacity is full"
                )
            self._retained_bytes += size

    def release_retained(self, size):
        with self._condition:
            if size < 0 or size > self._retained_bytes:
                raise RuntimeError("retained audio ownership is inconsistent")
            self._retained_bytes -= size
            self._condition.notify_all()

    def _reserve_upload_bytes(self, size):
        with self._condition:
            if self._upload_bytes + size > self._max_upload_bytes:
                raise SpeechFailure(
                    FailureCode.OVERLOADED, "upload byte capacity is full"
                )
            self._upload_bytes += size

    def _release_upload_bytes(self, size):
        with self._condition:
            if size < 0 or size > self._upload_bytes:
                raise RuntimeError("upload byte ownership is inconsistent")
            self._upload_bytes -= size

    def _close_lease(self, lease, size):
        with self._condition:
            if lease not in self._leases or size < 0 or size > self._upload_bytes:
                raise RuntimeError("upload lease ownership is inconsistent")
            if self._active <= 0:
                raise RuntimeError("upload slot ownership is inconsistent")
            self._upload_bytes -= size
            self._active -= 1
            self._leases.discard(lease)
            self._condition.notify_all()

    def _transfer_upload_to_retained(self, lease, size):
        with self._condition:
            if size > self._upload_bytes:
                raise RuntimeError("upload byte ownership is inconsistent")
            if self._active <= 0:
                raise RuntimeError("upload slot ownership is inconsistent")
            if self._retained_bytes + size > self._max_retained_bytes:
                raise SpeechFailure(
                    FailureCode.OVERLOADED, "retained audio capacity is full"
                )
            self._upload_bytes -= size
            self._retained_bytes += size
            self._active -= 1
            self._leases.discard(lease)
            self._condition.notify_all()

    def close(self):
        with self._condition:
            self._accepting = False
            leases = tuple(self._leases)
        for lease in leases:
            lease.close()


class AdmissionController:
    def __init__(
        self,
        execute,
        max_queued: int,
        max_queued_audio_bytes: int,
        max_retained_audio_bytes: int,
        max_request_bytes: int,
        queue_wait_timeout_seconds: float,
        max_uploads: int,
        max_upload_bytes: int,
        cleanup_event=None,
    ):
        self._execute = execute
        self._cleanup_event = cleanup_event or threading.Event()
        if cleanup_event is None:
            self._cleanup_event.set()
        self._max_queued = max_queued
        self._max_queue_bytes = max_queued_audio_bytes
        self._max_request_bytes = max_request_bytes
        self._queue_wait = queue_wait_timeout_seconds
        self.uploads = UploadGate(
            max_uploads,
            max_upload_bytes,
            max_request_bytes,
            max_retained_audio_bytes,
        )
        self._condition = threading.Condition()
        self._queue = deque()
        self._pending = None
        self._active = None
        self._queued_bytes = 0
        self._accepting = False
        self._closing = False
        self._thread = None

    @contextmanager
    def acquire_upload(self):
        """Acquire an upload lease atomically with idle lifecycle reservations."""
        with self._condition:
            lease_context = self.uploads.acquire()
            lease = lease_context.__enter__()
        try:
            yield lease
        finally:
            lease_context.__exit__(None, None, None)

    def start(self):
        with self._condition:
            if self._thread is not None:
                raise RuntimeError("admission controller already started")
            self._accepting = True
            self._thread = threading.Thread(
                target=self._run, name="stt-admission", daemon=True
            )
            self._thread.start()

    def submit(
        self,
        request: TranscriptionRequest,
        context: OperationContext,
        upload_lease: UploadLease | None = None,
    ):
        size = len(request.audio)
        if size == 0:
            raise SpeechFailure(FailureCode.INVALID_INPUT, "audio must not be empty")
        if size > self._max_request_bytes:
            raise SpeechFailure(
                FailureCode.INPUT_LIMIT, "audio exceeds configured request limit"
            )
        now = time.monotonic()
        queue_deadline = now + self._queue_wait
        if context.deadline is not None:
            queue_deadline = min(queue_deadline, context.deadline)
        job = _Job(request, context, queue_deadline)
        if upload_lease is not None and (
            upload_lease._gate is not self.uploads
            or not upload_lease.owns(request.audio)
        ):
            raise SpeechFailure(
                FailureCode.INVALID_INPUT, "upload ownership is invalid"
            )
        with self._condition:
            if not self._accepting:
                raise SpeechFailure(
                    FailureCode.NOT_READY, "worker is not accepting requests"
                )
            if self._active is None and self._pending is None and not self._queue:
                slot = "pending"
            else:
                if len(self._queue) >= self._max_queued:
                    raise SpeechFailure(FailureCode.OVERLOADED, "request queue is full")
                if self._queued_bytes + size > self._max_queue_bytes:
                    raise SpeechFailure(
                        FailureCode.OVERLOADED, "queued audio capacity is full"
                    )
                slot = "queued"
            if upload_lease is not None:
                upload_lease.transfer(size)
            else:
                self.uploads.reserve_retained(size)
            if slot == "pending":
                self._pending = job
                job.state = "pending"
            else:
                self._queue.append(job)
                self._queued_bytes += size
                job.state = "queued"
            self._condition.notify_all()

        while not job.done.wait(0.02):
            if context.cancelled():
                self.cancel(job)
            elif job.state == "queued" and time.monotonic() >= job.queue_deadline:
                self.expire(job)
        if job.failure:
            raise job.failure
        return job.result

    def cancel(self, job: _Job):
        with self._condition:
            if job.finished:
                return
            if job.state == "queued":
                try:
                    self._queue.remove(job)
                except ValueError:
                    pass
                else:
                    self._queued_bytes -= len(job.request.audio)
                    self._finish_locked(job, failure=_cancel_failure(job.context))
            elif job.state == "pending":
                job.context.cancel()
                self._condition.notify_all()
            elif job.state == "active":
                job.context.cancel()
                self._condition.notify_all()

    def expire(self, job: _Job):
        with self._condition:
            if job.finished or job.state != "queued":
                return
            try:
                self._queue.remove(job)
            except ValueError:
                return
            self._queued_bytes -= len(job.request.audio)
            self._finish_locked(
                job,
                failure=SpeechFailure(
                    FailureCode.OVERLOADED, "request expired in queue"
                ),
            )

    def snapshot(self):
        with self._condition:
            return {
                "active": self._active is not None or self._pending is not None,
                "queued": len(self._queue),
                "queued_bytes": self._queued_bytes,
                "retained_bytes": self.uploads.retained_bytes,
                "accepting": self._accepting,
            }

    def run_if_idle(self, reserve, callback):
        """Reserve an idle action under admission lock, then run it lock-free."""
        with self._condition:
            if (
                not self._accepting
                or self._closing
                or self._active is not None
                or self._pending is not None
                or self._queue
                or self.uploads.snapshot()["active_uploads"]
            ):
                return False
            if not reserve():
                return False
        callback()
        return True

    def latch_fault(self):
        with self._condition:
            self._accepting = False
            while self._queue:
                job = self._queue.popleft()
                self._queued_bytes -= len(job.request.audio)
                self._finish_locked(
                    job,
                    failure=SpeechFailure(
                        FailureCode.NOT_READY, "model is unavailable"
                    ),
                )
            self._condition.notify_all()
        self.uploads.close()

    def fail_admitted(self, failure, finish_generation):
        """Fail pending and queued work from one failed initialization generation."""
        with self._condition:
            if self._pending is not None:
                job = self._pending
                self._pending = None
                self._finish_locked(job, failure=failure)
            while self._queue:
                job = self._queue.popleft()
                self._queued_bytes -= len(job.request.audio)
                self._finish_locked(job, failure=failure)
            # Publish UNLOADED while admission is still closed to this transition.
            finish_generation()
            self._condition.notify_all()

    def close(self, drain_timeout_seconds: float):
        deadline = time.monotonic() + max(0.0, drain_timeout_seconds)
        with self._condition:
            if self._thread is None:
                return True
            self._accepting = False
            self._closing = True
            while self._queue:
                job = self._queue.popleft()
                self._queued_bytes -= len(job.request.audio)
                self._finish_locked(
                    job,
                    failure=SpeechFailure(FailureCode.NOT_READY, "worker is draining"),
                )
            if self._pending is not None:
                self._pending.context.cancel()
            self._condition.notify_all()
            thread = self._thread
        self.uploads.close()
        thread.join(timeout=max(0.0, (deadline - time.monotonic()) / 2))
        if thread.is_alive():
            with self._condition:
                active = self._active or self._pending
                if active is not None:
                    active.context.cancel()
                self._condition.notify_all()
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._condition:
            admission_idle = self._active is None and self._pending is None
        thread.join(timeout=0)
        return admission_idle and not thread.is_alive()

    def _run(self):
        while True:
            with self._condition:
                self._release_confirmed_cleanup_locked()
                self._expire_queue_locked()
                while self._pending is None and not self._queue and not self._closing:
                    self._condition.wait(0.02)
                    self._release_confirmed_cleanup_locked()
                    self._expire_queue_locked()
                if self._closing and self._pending is None and not self._queue:
                    if self._active is None:
                        return
                    if (
                        self._active.cleanup_pending
                        and not self._cleanup_event.is_set()
                    ):
                        self._condition.wait(0.02)
                        continue
                if self._pending is not None:
                    job = self._pending
                    self._pending = None
                elif self._queue and not self._closing:
                    job = self._queue.popleft()
                    self._queued_bytes -= len(job.request.audio)
                else:
                    self._condition.wait(0.02)
                    continue
                self._active = job
                job.state = "active"
            try:
                job.context.check()
                result = self._execute(job.request, job.context)
                job.context.check()
                self._complete(job, result=result)
            except SpeechFailure as exc:
                self._complete(job, failure=exc, retain_resources=exc.retain_resources)
            except Exception:
                self._complete(
                    job,
                    failure=SpeechFailure(
                        FailureCode.BACKEND_FAILED, "transcription failed"
                    ),
                )
            finally:
                with self._condition:
                    if self._active is job:
                        if job.cleanup_pending:
                            self._release_confirmed_cleanup_locked()
                        else:
                            self._active = None
                    self._condition.notify_all()

    def _expire_queue_locked(self):
        now = time.monotonic()
        retained = deque()
        while self._queue:
            job = self._queue.popleft()
            if job.context.cancelled():
                self._queued_bytes -= len(job.request.audio)
                self._finish_locked(job, failure=_cancel_failure(job.context))
            elif now >= job.queue_deadline:
                self._queued_bytes -= len(job.request.audio)
                self._finish_locked(
                    job,
                    failure=SpeechFailure(
                        FailureCode.OVERLOADED, "request expired in queue"
                    ),
                )
            else:
                retained.append(job)
        self._queue = retained

    def _complete(self, job, result=None, failure=None, retain_resources=False):
        with self._condition:
            self._finish_locked(job, result, failure, retain_resources)

    def _finish_locked(self, job, result=None, failure=None, retain_resources=False):
        if job.finished:
            return
        job.result = result
        job.failure = failure
        job.finished = True
        job.state = "finished"
        job.cleanup_pending = retain_resources and not self._cleanup_event.is_set()
        if not job.cleanup_pending:
            self.uploads.release_retained(len(job.request.audio))
        job.done.set()
        self._condition.notify_all()

    def _release_confirmed_cleanup_locked(self):
        job = self._active
        if job is not None and job.cleanup_pending and self._cleanup_event.is_set():
            self.uploads.release_retained(len(job.request.audio))
            job.cleanup_pending = False
            self._active = None
            self._condition.notify_all()


def _cancel_failure(context):
    if context.deadline is not None and time.monotonic() >= context.deadline:
        return SpeechFailure(FailureCode.DEADLINE_EXCEEDED, "request deadline exceeded")
    return SpeechFailure(FailureCode.CANCELLED, "request was cancelled")
