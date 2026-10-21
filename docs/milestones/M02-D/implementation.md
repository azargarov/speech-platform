# M02-D implementation record

## STT cancellation handling

- **OBSERVED:** `InferenceSupervisor.transcribe` no longer terminates an active
  child after a cancellation grace interval. It signals the existing cooperative
  cancellation event, continues consuming the in-flight response, and returns
  the cancellation or deadline failure while discarding the response result.
- **OBSERVED:** requests remain serialized through the existing single child and
  IPC channel, so a late response is consumed before a subsequent request is
  sent. Queued cancellation remains owned by the admission controller.
- **OBSERVED:** a fatal response is latched and the child is reaped before the
  caller's cancellation result is selected. This prevents cancellation from
  hiding a fatal backend state.
- **OBSERVED:** explicit shutdown and fatal IPC/backend cleanup continue to use
  bounded process-exit waits. Child failure and exit diagnostics use fixed
  classifications and exit status only; audio, transcripts, paths, credentials
  and exception text are excluded.
- **OBSERVED:** active inference cancellation, a subsequent request after a
  discarded result, fatal-response/cancellation ordering, and existing process
  crash, IPC failure, queued cancellation and shutdown paths have regression
  coverage.
- **INTERPRETATION:** API error codes and deployment architecture remain
  unchanged. Explicit shutdown, fatal backend failures, and broken IPC/process
  states retain their process cleanup behavior.
- **NOT ESTABLISHED:** behavior with an actual CUDA/CTranslate2 inference call
  under client cancellation was not exercised in this local CPU test run.

The change preserves the existing `cooperative_cancel_grace_seconds` config
field for compatibility; it no longer controls child termination during an
active request.

## Scope classification

- Cancellation behavior: `services/stt/supervisor.py` and its serialized IPC
  regression cases in `services/stt/tests/test_runtime.py`.
- Diagnostic logging: lifecycle state transitions and fixed child failure/exit
  classifications in `services/stt/lifecycle.py` and `supervisor.py`.
- Runtime acceptance documentation: this record and
  [verification.md](verification.md).
- The concurrent `scripts/product_deployment.py` output-display helper and its
  test are unrelated CLI presentation edits and are not part of the cancellation
  change.
