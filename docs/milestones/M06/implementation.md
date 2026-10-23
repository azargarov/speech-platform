# M06 implementation record

Status: **M06B offline implementation and verification ACCEPTED 2026-10-23. M06 remains in progress; M06C is the next separately gated development stage.**

M06A finalized the architecture and contracts. This M06B change implements STT lazy loading, an internal warmup route, idle unloading/reload, and the approved worker readiness behavior. It does not implement the public Gateway API, TTS/Ollama changes, readiness-aware routing, deployment, or live GPU qualification.

## M06B changes

- STT process startup now validates configuration/artifacts and starts bounded admission without creating a model child. `STTApplication._ensure_model()` starts one bounded background initialization attempt guarded by the lifecycle condition; inference and warmup wait on the same attempt using their own operation deadlines.
- Each cold-load cycle creates a fresh `InferenceSupervisor`, preserving the supervised child boundary and reaper behavior. Device discovery/selection is repeated before each child start. A shared cleanup event remains connected to admission resource retention. An unconfirmed cleanup latches the worker and blocks reload.
- `AdmissionController.run_if_idle()` reserves unloading atomically against pending, active, queued, and active-upload work, then releases the admission lock before child shutdown. Upload lease acquisition uses the same admission lock. New work waits for the `unloading` state within its own deadline.
- Added validated `lifecycle.model_idle_unload_seconds` in `0..86400`, default 60; zero unloads at the first safe point. Existing application configs that omit the field retain the 60-second default. The product config and tracked CPU/CUDA examples state it explicitly.
- `/healthz` remains process liveness. `/readyz` now remains ready in `unloaded`, `loading`, `ready`, and `unloading` when the worker is serving; fatal, cleanup-unconfirmed, draining and stopped workers are not ready. Gateway source/configuration was not changed because its readiness check consumes worker `/readyz`.
- Added internal `POST /internal/v1/warmup`; it accepts no body, requires the existing request-timeout header, and returns `{"model_state":"ready"}` on success. Failure uses the existing sanitized error envelope. Client timeout/disconnect stops waiting but does not cancel the underlying model initialization. No public Gateway warmup route was added.
- Confirmed-cleanup initialization failures are returned to the active request and all pending/queued requests admitted before the failure transition. The admission lock protects the failure-generation boundary; only later admissions can initiate a retry. Uncertain cleanup retains the fault latch. No automatic retry loop is introduced.
- The public request path no longer dereferences a runner after admission completion. Fault checks use a condition-protected current-runner snapshot, while active inference uses its owned local runner reference.
- Device/runner preflight runs in one bounded daemon activity. If a native probe does not return by `model_load_timeout_seconds`, the worker enters `cleanup_unconfirmed`; a late factory result cannot start a model child and is shut down. Shutdown joins loader, preflight and idle lifecycle activity within configured bounds and remains cleanup-unconfirmed if any activity cannot be joined or child cleanup cannot be confirmed.
- Preflight runner ownership is now transferred through one condition-protected handoff: the loader claims a completed result, or timeout abandons it and the preflight owner cleans a late result. The two ownership outcomes cannot both succeed.
- Application shutdown uses one derived deadline (`shutdown_drain_timeout_seconds + model_load_timeout_seconds + 2 * process_exit_timeout_seconds`). Admission close reports whether its worker and active operation actually stopped. If inference still owns the runner, application shutdown does not call runner shutdown; it returns with readiness false and `cleanup_unconfirmed` latched.
- Supervisor shutdown bounds both lock acquisition and child cleanup by its supplied deadline. Failure to acquire the IPC ownership lock is treated as cleanup uncertainty; the child is not declared stopped and the worker cannot reload it.
- Warmup timeout-header errors now use the sanitized JSON error envelope. The route rejects declared and chunked bodies before model loading; any body read for an unknown-length request uses the operation deadline. The body remains required to be empty.

## Files changed

Application: `services/stt/application.py`, `services/stt/admission.py`, `services/stt/supervisor.py`, `services/stt/lifecycle.py`, `services/stt/service.py`, `services/stt/http_server.py`, `services/stt/config.py`.

Configuration: `configs/stt-product-application.yaml`, `configs/stt-application-cpu.example.yaml`, `configs/stt-application-cuda.example.yaml`.

Tests: `services/stt/tests/test_config_artifacts.py`, `services/stt/tests/test_runtime.py`, `services/stt/tests/test_http.py`.

## Lifecycle and compatibility

`unloaded → loading → ready → unloading → unloaded`; confirmed-cleanup load failure returns to `unloaded`; cleanup uncertainty enters `cleanup_unconfirmed`; fatal inference faults enter `faulted`. Readiness expresses bounded request acceptance, not model residency. Existing inference request/response contracts and normal inference without warmup remain supported.

STT cold initialization uses one loader thread and one bounded preflight activity; only the loader may start the supervised child after explicitly claiming ownership. Concurrent callers wait with their own operation deadlines. A caller timeout or disconnect does not cancel shared child initialization. Non-cooperative native preflight or inference cannot be forcibly interrupted safely: it is marked cleanup-unconfirmed, blocks reinitialization, and is reported as such if it outlives bounded shutdown. When active inference outlives shutdown, the runner remains owned and is not shut down concurrently; operator process recovery may be required. No separate manager or scheduler was added.

## M06B concurrency corrections

The independent lifecycle review findings were addressed in the existing application/admission/HTTP boundaries. Regression coverage includes zero-timeout unload after request completion, queued work held at the shared-load failure boundary, concurrent warmup failure singleflight, upload acquisition before unload reservation, inference admission during blocked unload, preflight completion/timeout ownership competition, bounded shutdown during non-cooperative inference, supervisor lock-acquisition timeout, blocked preflight cleanup uncertainty, and warmup timeout/body validation. The complete evidence and limitations are recorded in [verification.md](verification.md).

## Not included

M06C owns the public Gateway warmup contract, TTS reuse and Ollama warmup and is the next development stage, subject to separate implementation authorization. M06D owns full offline integration/regression verification. M06E live qualification and deployment require separate explicit operator authorization. M06B acceptance covers only its implementation and offline verification; it is not an overall M06 closeout.
