# M02 implementation

Status: M02-A and M02-B implemented, verified and user-validated as PASS on 2026-10-17. Overall M02 remains incomplete; M02-C is the next approval gate and has not started.

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

## M02-B implementation record

OBSERVED:

- Added a faster-whisper adapter behind the existing backend ports. Application/domain modules do not import faster-whisper, CTranslate2, CUDA or NVIDIA packages. The adapter imports its inference dependencies lazily; CPU probing does not import NVIDIA packages.
- Added explicit CPU/CUDA device probing, compute-type capability checks and required free-memory preflight for CUDA. Explicit CUDA does not fall back to CPU. The memory preflight uses observed free memory as an advisory check and does not reserve VRAM.
- Added bounded PyAV audio decoding to mono float32, automatic language detection, optional segment timestamps and typed safe error mapping. Native model runtime failures fault the supervised child rather than triggering retries.
- Added a private multipart worker endpoint at `/internal/v1/transcriptions`, with bounded request/upload handling, request deadline propagation, disconnect cancellation, health/readiness and bounded-cardinality Prometheus metrics. Public Gateway inference behavior and TTS implementation were not changed.
- Added strict inference configuration schema v3 and deployment config v2 while preserving legacy M01 health-only operation when inference configs are absent.
- Added CPU and CUDA dependency inputs and hash-locked dependency sets, CPU/CUDA Dockerfiles and Compose overlays, sample configuration, lock validation and a local CPU smoke command. Runtime artifact loading is local-only; model acquisition is an offline operator step.
- Runtime dependency versions in the locked sets include faster-whisper 1.2.1, CTranslate2 4.8.3 and PyAV 19.0.1. CPU lock excludes NVIDIA runtime packages. CUDA lock includes NVIDIA user-space libraries; host driver compatibility is not established here.
- Added synthetic decoder, backend contract, configuration/artifact, HTTP, disconnect and device-probe tests. Full STT suite has 52 passing tests.
- Following explicit user authorization, provisioned the upstream Systran CTranslate2 tiny model from immutable revision `d90ca5fe260221311c53c58e660288d3deb8d356`. The pinned Hugging Face model card identifies MIT licensing and documents CTranslate2/faster-whisper compatibility. Only the inference files `config.json`, `model.bin`, `tokenizer.json`, and `vocabulary.txt` were retained in the ignored private area. Their SHA-256 values and the canonical manifest digest are recorded in [verification](verification.md); no model or audio content is in Git.
- Corrected blocking validation issues found during CPU acceptance: (1) the adapter required `preprocessor_config.json`, absent from the pinned model; `test_cpu_load_uses_local_artifact_explicit_precision_and_threads` now uses a fixture matching the upstream file set; (2) the CPU deployment example put the manifest inside the artifact root, making exact file-set verification impossible; `test_cpu_deployment_example_places_manifest_outside_artifact_root` guards its placement; and (3) the CPU integration Make target omitted the repository root from `PYTHONPATH`, preventing `services` imports. The complete `make stt-cpu-integration` command was rerun successfully after that correction.
- Enhanced the CPU smoke harness to exercise the actual private HTTP endpoint and child supervisor, validate response and segment bounds and an unknown-alias error, record readiness/load and inference timings, and assert child exit after cleanup. Its output does not include audio or transcript text.

INTERPRETATION:

- The adapter exercises the existing M02-A cancellation/lifecycle and child ownership rules. Native backend failures are treated as fatal because CUDA/runtime cleanup can be uncertain.
- CUDA profile configuration and static Compose rendering demonstrate intended explicit device configuration, not working GPU passthrough.

OBSERVED during CPU user-validation preparation:

- Real local CPU transcription through the private HTTP route succeeded with automatic language detection (`ru`) and five valid timestamp segments. Readiness was 503 during loading and 200 after readiness; an unknown model alias returned 404. The supervised inference child was confirmed stopped after HTTP test-client cleanup.
- The same smoke passed with Hugging Face and Transformers offline environment flags, using only the provisioned local model directory. Across the two offline runs, observed readiness/load intervals were 0.466 and 0.514 seconds; transcription request times were 0.526 and 0.515 seconds. GNU `time` observed maximum RSS of 300,708 KiB for the complete offline smoke command (including its test harness and child); this is not a worker-isolated memory measurement.
- The recording's SHA-256 was unchanged across test runs. The integration output contained model alias/revision, language, segment count and timings only; it did not print transcript text. No audio was uploaded.

NOT ESTABLISHED:

- CPU timing and memory values are observations from this host, one short recording and the tiny test model; they are not performance guarantees or representative production capacity measurements. Cold-cache startup and sustained load were not measured.
- Local CTranslate2 reports zero CUDA devices. No CUDA inference, GPU integration test, Docker GPU passthrough or target-host compatibility test was run.
- No containers were started, no remote host was accessed, and Ollama/Dify were not touched. Real model HTTP disconnect cancellation under an interrupted client was not exercised; prior cancellation coverage remains fake-application based.

M02-B is PASS after CPU user acceptance; the NOT ESTABLISHED runtime checks above remain limitations of that acceptance. M02-C has not started. See [verification](verification.md), [user validation](user-validation.md), [result](result.md), and [design](../../architecture/m02-stt-design.md).
