"""Long-lived STT service facade that keeps health available during model setup."""

from __future__ import annotations

import threading

from services.stt.application import create_application
from services.stt.domain import FailureCode, SpeechFailure
from services.stt.lifecycle import Lifecycle, ModelState, WorkerState
from services.stt.runtime import create_runtime


class DeferredApplication:
    def __init__(self, config, deployment, backend_registry=None):
        self.config = config
        self._deployment = deployment
        self._backend_registry = backend_registry
        self._lock = threading.Lock()
        self._delegate = None
        self._lifecycle = Lifecycle()
        self._lifecycle.set_worker(WorkerState.SERVING)
        self._lifecycle.set_model(ModelState.VALIDATING)

    @property
    def lifecycle(self):
        with self._lock:
            return (
                self._delegate.lifecycle
                if self._delegate is not None
                else self._lifecycle
            )

    def start(self):
        try:
            if self._backend_registry is None:
                factory, probe = create_runtime(self.config, self._deployment)
                registry = {self.config.backend_id: factory}
            else:
                registry, probe = self._backend_registry
            backend = registry[self.config.backend_id]()
            application = create_application(
                self.config, self._deployment, registry, probe
            )
            application.start(backend.capabilities())
            with self._lock:
                self._delegate = application
                self._lifecycle = application.lifecycle
        except SpeechFailure:
            self._lifecycle.set_model(ModelState.FAULTED)
        except Exception:
            self._lifecycle.set_model(ModelState.FAULTED)

    def acquire_upload(self):
        application = self._current()
        if application is None:
            raise SpeechFailure(FailureCode.NOT_READY)
        return application.acquire_upload()

    def transcribe_uploaded(self, *args, **kwargs):
        application = self._current()
        if application is None:
            raise SpeechFailure(FailureCode.NOT_READY)
        return application.transcribe_uploaded(*args, **kwargs)

    def warmup(self, *args, **kwargs):
        application = self._current()
        if application is None:
            raise SpeechFailure(FailureCode.NOT_READY)
        return application.warmup(*args, **kwargs)

    def close(self):
        application = self._current()
        if application is not None:
            application.close()
        else:
            self._lifecycle.set_worker(WorkerState.STOPPED)
            self._lifecycle.set_model(ModelState.FAULTED)

    def _current(self):
        with self._lock:
            return self._delegate
