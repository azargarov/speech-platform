"""Worker and model lifecycle state, deliberately tracked separately."""

from enum import StrEnum
import json
import threading


class WorkerState(StrEnum):
    STARTING = "starting"
    SERVING = "serving"
    DRAINING = "draining"
    STOPPED = "stopped"
    FAILED = "failed"


class ModelState(StrEnum):
    UNRESOLVED = "unresolved"
    VALIDATING = "validating"
    DISCOVERING = "discovering"
    LOADING = "loading"
    READY = "ready"
    UNLOADING = "unloading"
    UNLOADED = "unloaded"
    FAULTED = "faulted"
    CLEANUP_UNCONFIRMED = "cleanup_unconfirmed"


class Lifecycle:
    def __init__(self):
        self._lock = threading.Lock()
        self._worker = WorkerState.STARTING
        self._model = ModelState.UNRESOLVED

    def set_worker(self, state: WorkerState):
        with self._lock:
            self._worker = state

    def set_model(self, state: ModelState):
        with self._lock:
            previous = self._model
            self._model = state
        if previous != state:
            print(
                json.dumps(
                    {
                        "event": "model_state_changed",
                        "from": previous.value,
                        "to": state.value,
                    },
                    separators=(",", ":"),
                ),
                flush=True,
            )

    def snapshot(self) -> tuple[WorkerState, ModelState]:
        with self._lock:
            return self._worker, self._model

    def live(self) -> bool:
        return self.snapshot()[0] in {WorkerState.SERVING, WorkerState.DRAINING}

    def ready(self) -> bool:
        worker, model = self.snapshot()
        return worker == WorkerState.SERVING and model == ModelState.READY

    def cleanup_unconfirmed(self) -> bool:
        return self.snapshot()[1] == ModelState.CLEANUP_UNCONFIRMED
