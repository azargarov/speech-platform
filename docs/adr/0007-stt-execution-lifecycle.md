# STT worker, model and inference execution lifecycle

Status: accepted for M02 design; active-request cancellation behavior amended by [ADR 0019](0019-stt-active-cancellation.md). Implementation authorization remains separate.

## Context

Native inference may outlive an HTTP task or fail while using GPU memory. Worker process health, model readiness and request capacity are distinct facts. M02 must bound resource use while keeping model warm and avoid automatic interference with Ollama/Dify.

## Decision

Keep worker-control and model lifecycle state machines separate. M02 limits each worker instance to one resident model and one active job, with configured bounded FIFO admission. A persistent supervised child owns decoder/model/native inference state. Disconnect/deadline removes queued work immediately and signals active cancellation. See ADR 0019 for active-request behavior. Forced termination, OOM or uncertain cleanup fault-latches the model and requires manual recovery. No same-request retry, precision downgrade, model eviction, or automatic restart loop.

The one-model/one-job limit is an M02 implementation constraint, not a permanent architecture invariant. Orderly shutdown disables admission, drops queued jobs, drains the active job to deadline, then follows cancel/terminate/reap. Liveness describes the control process; readiness describes a loaded usable model with admission enabled. Queue saturation returns 429 and does not make readiness flap.

## Consequences

The parent process can remain live for diagnostics after a model fault. A forced child exit may require operator restart and can reduce availability. A timeout bounds the caller result but does not promise immediate native/GPU cleanup. Queue counts and retained bytes are measurable local policy; no distributed or cross-service GPU reservation is implied.

## Alternatives

Inference in the HTTP process is smaller but cannot reliably terminate an uncooperative native call. One process per request adds repeated load cost and GPU allocation churn. Both are rejected for M02.
