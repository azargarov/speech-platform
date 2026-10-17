# M02 implementation

Status: M02-A implemented, verified, user-validated and closed as PASS on 2026-10-17. Overall M02 remains incomplete; M02-B has not started and is the next approval gate.

## M02-A implementation record

OBSERVED:

- Added provider-neutral domain contracts for transcription, model/artifact identity, capabilities, devices, operation context, loaded models, backend and device-probe ports, and typed safe failures.
- Added strict versioned application and deployment configuration, stable alias/catalog resolution, immutable artifact manifest verification, explicit device selection policy, and fail-closed handling for unregistered backends and unsupported options.
- Added separate worker/model lifecycle, readiness behavior, FIFO admission, bounded upload/retained audio accounting, deadlines, cancellation, queue expiration, drain/shutdown, and explicit resource release.
- Added a persistent spawned child supervisor using the test-only fake backend. It bounds IPC, supports cooperative cancellation, escalates termination, confirms child exit before release, latches fatal faults, and does not automatically restart a failed child.
- Remediated audit findings: typed errors now expose fixed messages while retaining diagnostics separately; child frames are validated and IPC failures fault and terminate the child; terminate and kill each have bounded waits, with `cleanup_unconfirmed` exposed as an unready state; retained request ownership remains held until a reaper confirms child exit; a new child cannot replace an unconfirmed child.
- CUDA selection now rejects unknown or insufficient free memory when a backend declares a mandatory peak-memory estimate. This remains an advisory preflight, not a reservation.
- Preserved M01 health-only configuration behavior. The worker server uses optional lifecycle integration; TTS and public Gateway/OpenAPI behavior were not changed.
- Added deterministic local tests for contracts, configuration, artifacts, admission, lifecycle, supervisor behavior, and resource ownership.
- Added deterministic injected response-reader, poller and process-control tests for malformed, oversized and unreadable IPC frames; unconfirmed cleanup; no replacement; completion/cancellation ordering; child crash during cancellation; repeated cleanup; and deferred resource release.
- Final read-only acceptance audit recommended ACCEPT M02-A. User validation and closeout approval were received 2026-10-17; see [user validation](user-validation.md) and [result](result.md).

INTERPRETATION:

- The M02-A composition root deliberately has no production inference backend registered. Inference-mode startup therefore fails closed until a later authorized phase supplies an adapter. Fake-backend tests validate application behavior without downloading artifacts or requiring a GPU.
- Backend `load` is the boundary that must include implementation-specific loading and any warmup before the worker becomes ready. No real engine warmup was exercised.

NOT ESTABLISHED:

- Real model loading, transcription quality, CPU/GPU performance, memory use, CUDA compatibility, GPU passthrough, artifact provisioning on a deployment host, and runtime worker-network behavior.
- An internal HTTP transcription endpoint or full transport streaming/disconnect integration. M02-A provides the application and subprocess foundation only; it does not add public Gateway inference routing.
- Long-running reliability or process behavior under production workloads.
- Actual OS behavior where a process remains alive after SIGKILL. The injected process-control test verifies bounded state handling and retained ownership, but cannot establish kernel cleanup or GPU memory release.
- Resource monitor behavior if an unconfirmed child never exits: it retains ownership and remains unready; operator restart/recovery procedures are not yet exercised.
- Protection against concurrent artifact mutation after verification and before/during model load; deployment must provide read-only immutable artifact mounts and M02-B must validate this boundary.

No inference engine, model download, GPU test, remote host access, container deployment, or M02-B work was performed. See [verification](verification.md) and [user validation](user-validation.md).
