# M02 implementation

Status: M02-A, M02-B, M02-C.2b, M02-C.3, M02-C.4 and M02-C.5 are PASS for their accepted bounded scopes. C.5 covers deterministic offline failure behavior and the operator recovery procedure; it does not establish real CUDA cleanup, GPU OOM recovery or active GPU workload coexistence. Overall M02 remains INCOMPLETE. C.6 deployment planning is proposed; no deployment implementation or runtime validation has begun.

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

At M02-B closeout, M02-C had not started; its CPU acceptance limitations are historical. The subsequent C.2b smoke is recorded below. See [verification](verification.md), [user validation](user-validation.md), [result](result.md), and [design](../../architecture/m02-stt-design.md).

## M02-C.2a CUDA dependency-policy closeout

OBSERVED:

- Added CTranslate2 4.8.3 as an explicit CUDA input pin and regenerated the CUDA hash lock using its documented `uv pip compile` command. The resolved package versions and hashes are unchanged; the lock now records CTranslate2 as both an explicit requirement and a faster-whisper dependency.
- Added a lock-policy check for CTranslate2 4.8.3, cuBLAS 12.9.2.10 and cuDNN 9.27.0.42, and a guard against adding `nvidia-cuda-runtime-cu12`. Added tests for the approved tuple and rejection of incompatible CTranslate2/cuDNN pins and the CUDA Runtime package.
- Kept the CPU input and lock unchanged. No repository-maintained CUDA probe existed; the incorrect `libcudart.so.12` assertion was in the temporary diagnostic probe, so no new probe was added.
- Updated the architecture and ADR-0008 to record the accepted version policy and upstream documentation conflict.

INTERPRETATION:

- CTranslate2 4.8.3's versioned changelog is authoritative for cuDNN compatibility; its generic wheel note about cuDNN 8 is stale. The separate `libcudart.so.12` load check is not an appropriate package-compatibility requirement because the CTranslate2 wheel notes describe CUDA Runtime as statically linked.

NOT ESTABLISHED:

- At the C.2a dependency-policy closeout, CUDA STT inference, GPU memory behavior under model load, target-host deployment and coexistence during active Ollama/Dify workloads remained unverified. The later C.2b smoke provides one limited inference observation; it does not establish these broader properties.

## M02-C.2b bounded CUDA smoke — PASS

OBSERVED on 2026-10-17 in the authorized single diagnostic attempt:

- The approved immutable image (`sha256:b25af1309e1e51e8ce72c227028727cb26014fef512b716fbd11cf8f9fb16540`, linux/amd64) used faster-whisper 1.2.1, CTranslate2 4.8.3, PyAV 19.0.1, cuBLAS 12.9.2.10, cuDNN 9.27.0.42 and NVRTC 12.9.86. CUDA lock SHA-256: `68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14`.
- The manifest-verified `Systran/faster-whisper-tiny` artifact at revision `d90ca5fe260221311c53c58e660288d3deb8d356` loaded with explicit CUDA device 0 and float16. The production bounded decoder handled the approved audio. The single transcribe call and lazy segment iteration completed; output validation found Russian (`ru`), five segments and valid timestamp bounds. Transcript text was not persisted.
- Observed stage durations: model load 1.206437 s; transcribe call including production audio decode 0.693926 s; segment iteration 0.248505 s; output validation 0.000465 s. These are one-run diagnostic timings, not a performance claim.
- The launcher and harness reported success; the container exited 0 and was removed. The sanitized evidence is retained outside Git under the operator's private staging tree at `M02/M02-C/M02-C.2b/attempts/cuda-final-decoderfix-20261017-01/` (`launcher-report.json` and `harness/harness-report.json`). Ollama HTTP health remained 200 and Dify component health checks remained healthy before and after. GPU preflight reported a Quadro RTX 5000 with 14,909 MiB free; post-run observation returned to the same reported state. These observations do not measure true peak allocation.
- Execution used no network or published ports, non-root identity, read-only root/input/artifact mounts, one writable attempt-results mount, GPU 0 only and a 180-second bound. No persistent service was deployed.

INTERPRETATION:

- This demonstrates that the pinned tiny-model faster-whisper/CTranslate2 CUDA path completed one transcription on the inspected host using the approved image and production decoder. The diagnostic decoder adjustment avoids the PyAV 19.0.1 incompatibility in faster-whisper 1.2.1's path-based decode; production adapter code was not changed for this workaround.
- User formally accepted this bounded smoke-test scope as PASS on 2026-10-17. This is not deployment or full M02 acceptance.

NOT ESTABLISHED:

- True peak VRAM or GPU utilization, concurrency, sustained performance, production HTTP worker integration on CUDA, cancellation during CUDA inference, large-v3-turbo behavior, capacity, persistent deployment, and coexistence during active Ollama/Dify workload.
- Transcription quality beyond detected language and structural segment/timestamp validation.

## M02-C.3 HTTP CUDA integration harness — pre-acceptance implementation record

OBSERVED:

- Added `scripts/stt_cuda_http_smoke.py`. It uses the production aiohttp application through `TestServer`/`TestClient`, and the existing deferred application, admission controller, supervisor and faster-whisper runtime. It sends one multipart inference request to the private route, checks health/readiness, validates language and segment/timestamp metadata, and confirms the child is stopped and worker is unready after close.
- The harness reuses strict application/deployment configuration, worker configuration, installed CUDA lock verification, model manifest verification, shared approved-audio checksum verification, and the existing atomic privacy-filtered diagnostic report runner. Its persisted result omits transcript and segment text.
- Extended the maintained CUDA host launcher for the HTTP profile. It verifies the local immutable image/platform, explicit configured GPU index, CUDA float16 profile, configured free-VRAM gate, audio digest, dependency-lock digest, no runtime image pull, read-only root and input mounts, no external network or published ports, non-root execution, and explicit CPU/RAM/PID limits. Experiment timeouts are required arguments without launch defaults.
- Added `make stt-cuda-http-integration`, an operator-configured one-attempt command. Application, deployment, worker, artifact, and audio settings have separate sources. The Docker GPU selector is derived from and checked against deployment configuration; the worker validates the same configuration in-container.
- Added deterministic HTTP tests for invalid audio errors, overload at upload capacity, deadline cancellation, health/readiness behavior, and fixed safe error responses. Added profile override and Docker argument rejection tests, plus configured free-VRAM gate boundary tests.
- The first two authorized C.3 target attempts did not pass. Attempt `cuda-http-20261017-01` preserved the non-200 branch but lacked status/error metadata. Attempt `cuda-http-20261017-02` recorded HTTP 415 / `unsupported_media_type`: the extensionless `/input/smoke-audio` path caused the harness to send `application/octet-stream`. The handler rejected it before admission dispatch, decoding or inference. This was a harness defect; no production STT defect was established.
- Corrected the harness to require explicit `STT_CUDA_AUDIO_MEDIA_TYPE`, validate it against supported formats, and produce a matching multipart filename for extensionless mounts. Added a separate bounded `shutdown-report.json` with confirmed, unconfirmed, and failed/timed-out outcomes. The shutdown evidence checks the application supervisor state; Docker container removal is not treated as child cleanup evidence.
- `docs/operations/stt-cuda-http-integration.md` records configuration precedence, the proposed 4 CPU / 8 GiB / 128 PID / 180 second experiment envelope, its evidentiary limits, invocation, preflight and cleanup. No application inference semantics, TTS, Compose services or running services were changed.

INTERPRETATION:

- A successful future run will exercise the production route, app/admission path, child supervisor, bounded decoder and selected CUDA backend using an in-container loopback server. It will not validate host-published HTTP service behavior, the production Compose image, capacity or persistent deployment.
- The CPU/RAM/PID values reuse the C.2b bounded test envelope. C.2b did not measure RSS or true peak VRAM; 8 GiB is a container ceiling, not a measured memory requirement or guarantee. The 12,288 MiB VRAM gate is read from strict deployment configuration and remains advisory, not a reservation.

NOT ESTABLISHED:

- Local C.3 implementation and correction verification used no Docker container, model load, CUDA initialization or inference. The two separately authorized HTTP attempts reached the target container but neither performed transcription. Actual CUDA HTTP inference, real-audio response success, child shutdown confirmation for those attempts, resource use and Ollama/Dify coexistence under successful inference remain unverified. C.3 is not PASS; overall M02 remains incomplete.

At the time of this implementation entry, the correction was locally verified but had not yet been staged or run. The subsequent accepted target attempt is recorded below.

## M02-C.3 accepted target run — PASS for bounded scope

OBSERVED on 2026-10-17 during the third user-authorized attempt:

- Updated target staging with only the changed `Makefile` and HTTP smoke harness. All 26 staged runtime/source/config files matched the current workstation source by SHA-256; target Git checkout was not modified.
- The extensionless audio mount was submitted with explicit `Content-Type: audio/mp4` and generated multipart filename `smoke-audio.m4a`. The production HTTP integration stage passed; its non-200 branch fails the stage, establishing HTTP 200.
- The strict config and artifact checks passed. The harness reported explicit CUDA device 0, float16 and `cpu_fallback: false`; the pinned model manifest and audio checksum matched approved metadata.
- Output validation passed: detected language `ru`, five nonempty segments and valid timestamp bounds. No transcript text or audio content was included in the reports.
- Timings: model load 2.548835 s, transcription 0.958716 s, HTTP integration 3.827919 s.
- The independent shutdown report recorded `completed_and_confirmed`, with `child_exit_confirmed: true`, `worker_not_ready: true` and completed TestClient close. Docker exited 0 and the attempt container was absent after cleanup.
- GPU 0 had 14,909 MiB free before and after, with no compute process and 0% sampled utilization. Ollama HTTP health passed before and after. Dify API/database/Redis/sandbox health checks passed; web/proxy containers remained running and the proxy returned HTTP 307.
- Sanitized evidence remains outside Git at `/home/master/speech-platform-staging/M02/M02-C/M02-C.3/attempts/cuda-http-20261017-03/`, including `launcher-report.json`, `harness/harness-report.json`, `harness/shutdown-report.json`, and bounded stdout/stderr classifications.

INTERPRETATION: this demonstrates one accepted end-to-end multipart HTTP transcription through the production application and CUDA adapter in an isolated ephemeral container. It does not establish general service performance or production deployment behavior.

NOT ESTABLISHED: instrumented peak VRAM, concurrency, sustained load, production latency/throughput, persistent deployment, or Ollama/Dify coexistence under active inference load. C.3 PASS is limited to the accepted one-request test. Overall M02 remains incomplete.

## M02-C.4B offline measurement harness — implemented

OBSERVED in the local repository workspace:

- Extended the existing production-HTTP smoke harness with a validated sequential request count and explicit maximum. The defaults remain one request. Each HTTP response is fully read and schema/timestamp validated before the next request is sent to the same TestServer worker.
- Reports now distinguish process-cold start-to-readiness time, first request and later warm request timings, fixture audio duration and request-level real-time factor. Inference-only duration is reported as unavailable because the worker contract does not expose it; the harness adds no production API dependency.
- Added an optional single-thread resource sampler with constant-space aggregation for NVML device and visible worker-process GPU memory, harness/descendant RSS from `/proc`, and the cgroup v1/v2 memory high-water counter where present. GPU/RSS values are labeled sampled peaks; cgroup memory is kept distinct from process RSS. Missing interfaces use fixed diagnostic codes.
- Sanitized success and partial-failure reports retain only allowlisted counts, timings, statuses, language/segment metadata and resource summaries. Audio and transcript contents, private paths and raw exception details are not included. Existing independent shutdown evidence and lifecycle cleanup remain in place.
- The C.3 Make target defaults to one request and accepts configured request-count, maximum-count, overall-deadline and optional sample-interval settings. No CUDA, Docker, model load, inference, target access or shared-service operation was performed for this implementation.

INTERPRETATION: the extension enabled bounded, repeatable sequential measurement through the existing application path without changing production inference behavior. It was used for the later C.4 target experiments recorded below.

NOT ESTABLISHED at the time of this C.4B implementation record: the large-v3-turbo model had not been loaded or run; no cold/warm inference timings, RTF, VRAM/RSS values, resource thresholds, CUDA HTTP behavior for this model, quality results or capacity conclusions were established. The later bounded C.4 target experiments are recorded below.

## M02-C.4 target-model experiments — PASS for bounded scope

OBSERVED on 2026-10-18; user accepted the bounded scope:

- Phase A verified and staged the exact `dropbox-dash/faster-whisper-large-v3-turbo` artifact at revision `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`, with canonical manifest digest `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6` and model.bin SHA-256 `e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da`. The production artifact verifier passed. See Phase A evidence in [verification](verification.md).
- Phase B completed one request through the production HTTP application and explicit CUDA device 0 / float16 with CPU fallback disabled. Phase C repeated the same path for exactly three sequential requests through one worker and one model instance; each response was fully consumed and validated before the next request.
- Runtime identity: immutable image `sha256:b25af1309e1e51e8ce72c227028727cb26014fef512b716fbd11cf8f9fb16540` (`linux/amd64`); CUDA lock SHA-256 `68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14`; faster-whisper 1.2.1, CTranslate2 4.8.3, PyAV 19.0.1, cuBLAS 12.9.2.10, cuDNN 9.27.0.42 and NVRTC 12.9.86.
- Phase C reported 8.664 s process-cold startup-to-readiness. Three HTTP 200 responses detected `ru`; each had six segments with valid timestamp bounds. Full HTTP durations were 1.180 s, 0.702 s and 0.784 s; RTF was 0.055663, 0.033087 and 0.036972. Audio duration was 21.205333 s. Inference-only timing is not exposed by the worker contract.
- Resource sampler collected 12 one-second samples. Sampled maximum device-wide used memory was 2,795,962,368 bytes; cgroup memory high-water was 1,775,648,768 bytes. These are sampled device memory and cgroup high-water observations, not exact peak VRAM or process RSS. NVML child attribution was `process_not_visible`; descendant RSS samples were zero, so child-specific memory use is not established.
- Shutdown report confirmed worker close, inference-child exit/reaping, and readiness false. Container exited 0 and exact identity inspection confirmed removal. Temporary model-root/artifact modes were restored from `2710`/`2750` to original `2700`/`2700`. Ollama HTTP health and Dify proxy/core checks were satisfactory before and after. No service was modified.

Historical failures retained: the first Phase B target attempt stopped at artifact verification because the non-root container could not enumerate the model artifact directory. A separate non-GPU permission check confirmed the diagnosis; the bounded retry succeeded with temporary group traversal/read modes. During Phase C preparation, two host-side preflight scripts stopped before any container launch: one imported staged code before selecting its repository path, and one omitted the environment from its dry-run subprocess. Both wrapper issues were corrected before the single successful Phase C container run. These were harness/preflight failures, not CUDA inference failures.

INTERPRETATION: evidence supports successful bounded large-model CUDA HTTP execution and sequential first/warm request observations for the approved model, audio and image. It is not a capacity or production performance guarantee.

NOT ESTABLISHED: concurrency capacity, sustained-load behavior, exact peak VRAM, child-specific GPU memory/RSS, CUDA cancellation/driver cleanup after forced termination, active GPU workload coexistence with Ollama/Dify, or persistent deployment. Overall M02 remains incomplete.

## M02-C.5A offline fault-injection coverage — PASS for accepted scope

OBSERVED in the workstation repository:

- Review mapped C.5 scenarios to existing tests before adding coverage. Existing tests already exercise admission saturation and readiness stability (`test_queue_saturation_does_not_flap_readiness`, HTTP `test_upload_admission_limit_is_enforced_over_http`), disconnect and deadline cancellation, model-load timeout and load failure, unexpected child exit, fatal-child readiness latch, bounded forced termination and `cleanup_unconfirmed`, exact resource ownership/release, sanitized HTTP failures, launcher timeout evidence, and sanitized shutdown outcomes. These were retained rather than duplicated.
- Fixed one confirmed typed-error gap in `services/stt/backends/faster_whisper.py`: `MemoryError` from bounded decoded-audio buffer allocation now maps to `resource_exhausted`. No CUDA fallback, retry or production configuration change was added.
- Added `test_cuda_initialization_failure_is_typed_without_cpu_fallback` to assert an explicit CUDA constructor error becomes `model_load_failed` and the adapter never attempts CPU construction.
- Added `test_decoded_audio_allocation_failure_is_resource_exhausted`, `test_resource_exhaustion_uses_bounded_safe_http_error`, and `test_recoverable_resource_failure_releases_admission_for_next_request`. The last test observes zero active/queued/retained ownership after the injected failure, readiness remains true, and a following request succeeds through the same supervised child.
- Tightened `test_child_crash_and_load_failure_are_latched` to assert the unresponsive model-load timeout returns the existing `model_load_failed` code and the child is reaped.

INTERPRETATION: deterministic tests establish the current typed failure, HTTP mapping, no-fallback decision and recoverable admission release for these injected paths. Existing process-control tests establish application ownership and cleanup state transitions under their fake seam.

NOT ESTABLISHED: real CUDA driver initialization/inference errors, native allocator failure semantics, actual cgroup OOM behavior, CUDA context/memory release after forced termination, kernel-uninterruptible child behavior, active GPU workload coexistence, and persistent deployment. No target host, Docker, GPU, CUDA runtime, model artifact or inference was used. C.5A PASS is limited to offline deterministic coverage; C.5 overall was accepted only after the separate C.5B procedure review, and M02 remains incomplete.

## M02-C.5B recovery/operator procedure — PASS for accepted offline scope

OBSERVED: added a bounded recovery section to [the existing CUDA HTTP operations guide](../../operations/stt-cuda-http-integration.md). It describes the actual fault/recovery semantics, exact-worker identification, readiness versus liveness, stale-PID precautions, preservation of sanitized reports, `cleanup_unconfirmed` escalation, exact-container bounded stop/kill/removal, GPU-process visibility limitations, post-recovery readiness checks, and conditions requiring operator escalation. The guidance explicitly defers persistent service restart commands until C.6 defines the deployment identity and rollback procedure. Review also found that startup model-load failure could report generic `not_ready` even when child cleanup was unconfirmed; `STTApplication.start()` now preserves the more precise `CLEANUP_UNCONFIRMED` lifecycle state after bounded shutdown.

Existing tests were reviewed and retained; no duplicate recovery framework or production API was added. Added `test_model_load_timeout_with_unconfirmed_exit_reports_cleanup_unconfirmed` with the injected process-control seam to verify startup failure remains unready, rejects a later request, reports uncertain cleanup, and does not recover readiness merely when the reaper later confirms exit. The HTTP readiness fake now asserts 503 with `cleanup_unconfirmed` distinctly from generic `not_ready`. Existing runtime tests cover fault latching, no replacement, forced reap and uncertain cleanup; diagnostic tests cover confirmed/unconfirmed/failed shutdown reporting.

INTERPRETATION: code and fake-process tests support the documented application-level state transitions. The operator procedure is conservative and does not claim host process or CUDA context cleanup beyond observed evidence.

NOT ESTABLISHED: actual target-host recovery, Docker daemon/container behavior under persistent deployment, process visibility for a real inference child, GPU context release after forced termination, GPU OOM recovery, and recovery while Ollama/Dify run active GPU workloads. The user accepted C.5A and C.5B as PASS on 2026-10-18 for deterministic offline scope; no target experiment was performed.

## M02-C.6 deployment readiness — planning only

OBSERVED: base Compose already separates internal Gateway/STT/TTS networks, publishes only Gateway by default on loopback, runs workers non-root with read-only root filesystems, and has private `/healthz` and `/readyz` contracts. CPU/CUDA overlays mount artifacts read-only. The CUDA overlay currently exposes all GPUs, STT defaults to 256 MiB/1 CPU, Compose has no healthcheck/restart policy, and the CUDA Dockerfile uses a mutable Python tag. The previous artifact test required temporary permission changes, so permanent read access for the service identity is not established.

INTERPRETATION: proposed C.6A should add a strict deployment profile driving both configured CUDA device and Compose GPU exposure, permanent least-privilege model permissions, reviewed configurable CPU/RAM/PID limits, digest-pinned base image, Compose liveness wiring, explicit project identity, and exact rollback documentation/static checks. C.6B would separately validate bounded target startup/readiness/shutdown and shared-service health. C.6C would separately validate one private-path request and rollback. Each execution phase requires separate approval; none is implemented here.

NOT ESTABLISHED: persistent target service behavior, device-0-only Compose passthrough, deployed image provenance, permanent artifact access, service resource envelope, restart/recovery behavior, shutdown/GPU resource release, or rollback. Ollama and Dify were not accessed or modified.
