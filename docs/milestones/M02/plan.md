# M02 STT inference plan

Status: M02-A and M02-B are PASS following user validation and explicit closeout approval on 2026-10-17. **M02-C.2b: PASS for the bounded CUDA smoke-test scope only**, accepted on 2026-10-17. Overall M02 remains incomplete. No persistent target service deployment was performed. The accepted architecture is documented in [m02-stt-design.md](../../architecture/m02-stt-design.md) and its network boundary in [ADR 0009](../../adr/0009-worker-network-reachability.md).

## Scope

Implement one provider-neutral STT application using a single faster-whisper adapter on CPU and CUDA. Use one resident model, one active job, bounded upload/admission queues and a persistent supervised inference subprocess. Resolve stable model aliases in STT. Verify immutable model artifacts offline. Keep public API engine-independent; implement only the private STT worker path. Keep TTS unchanged. Preserve M01 health-only config behavior.

Initial `llm` deployment policy is explicit CUDA with no CPU fallback. A separate CPU-only profile proves portability. No public Gateway inference routing/authentication (M04), second adapter, streaming, diarization, batching, multiple resident models, dynamic scheduling, model eviction, automatic OOM retry, runtime model download, Ollama/Dify control or deployment without separate authorization.

## Phases and entry gates

Each phase is a reviewable deliverable. User approval is required before beginning each phase; successful verification does not advance automatically.

### M02-A — Application and execution foundation

Entry gate: M01 PASS (satisfied); M02-A implementation was explicitly authorized. Exit gate: all acceptance criteria and verification pass, records are updated, and user validates A before B is proposed. **Status: PASS.** User validation and closeout approval were received 2026-10-17. M02-B is the next separate approval gate.

Deliver typed domain/ports, alias catalog, versioned strict inference config and deployment config; legacy health-only compatibility; manifest schema/validation; worker/model lifecycles; admission and byte accounting; supervised child protocol; health/readiness; safe errors and metrics. Use fake backend and fake device/process adapters. Do not add faster-whisper, CUDA or start containers in this phase.

Acceptance: unknown/missing/duplicate/invalid config fails; old M01 health-only config still starts health control with readiness 503; artifact path/digest/file errors fail before child model load; exactly one model and active job; queue count and bytes enforce boundaries; cancellation releases queued work once and active resources only after completion/confirmed child exit; worker liveness stays independent from model readiness; saturation is 429 without readiness flapping; shutdown drains then cancels/reaps; no payload logging or persistent audio; Compose statically enforces internal `stt_private` and `tts_private` networks, Gateway attached to both, each worker attached only to its own network, no worker published ports, and Gateway as the only host-published service; TTS and public contract unchanged.

Verification commands: `make verify PYTHON=.venv/bin/python` (includes rendered Compose and static topology validation); focused new suite `PYTHON=.venv/bin/python -m unittest discover -s services/stt/tests -v`; `git diff --check`. CI runs the fake-backend suite without GPU. The focused command is a planned test location to create in A. Runtime network reachability remains unverified until separately authorized deployment.

User validation: completed 2026-10-17. User approved M02-A validation after the final audit recommendation ACCEPT. ADR 0009 is accepted for design; no host access or deployment is part of M02-A.

### M02-B — faster-whisper CPU/CUDA adapter and private STT operation

Entry gate: M02-A is implemented, verified and explicitly user-accepted; separate approval for M02-B was received. Exit gate: CPU artifact smoke evidence and verification are recorded and the user explicitly accepts B before C begins. **Status: PASS.** User accepted M02-B CPU validation on 2026-10-17.

Add one adapter and its locked dependency/image profile; bounded audio decode; immutable artifact loading; effective capability reporting; internal transcription route; timestamps; CPU-only profile; explicit CUDA profile; structured metrics/errors. Provision models offline. Do not add Gateway public routing or any other adapter.

Acceptance: adapter contract suite passes on CPU; a pinned licensed small artifact runs an offline CPU smoke test with correct result schema/language and segment bounds; supported/unsupported timestamp and language behaviors map to existing internal errors; manifest is verified before load; invalid precision/device combinations fail closed; CPU profile does not import NVIDIA packages; CUDA configuration rejects missing/incompatible device without CPU fallback; cancellation tests exercise adapter checkpoints and supervised process boundary; no audio/transcript persistence or payload logging; internal OpenAPI remains engine-neutral; local runtime is configured to use local artifacts only. The pinned tiny CPU smoke has passed; see the validation record and remaining NOT ESTABLISHED items in [verification](verification.md).

Verification commands: `make verify PYTHON=.venv/bin/python`; `make stt-cpu-integration PYTHON=.venv/bin/python` with `STT_APPLICATION_CONFIG`, `STT_DEPLOYMENT_CONFIG` and `STT_SMOKE_AUDIO` pointed to local provisioned files; `make compose-check PYTHON=.venv/bin/python`; `git diff --check`. No GPU is required for CPU CI. CUDA runtime checks remain NOT ESTABLISHED. The Compose check verifies rendered static topology only; it does not start containers.

User validation: completed 2026-10-17. User accepted pinned-model CPU HTTP smoke evidence, artifact provenance/digests, logs/privacy, cleanup and limitations. No target deployment.

### M02-C — Authorized `llm` GPU validation and closeout

Entry gate: M02-B is implemented, verified and explicitly user-accepted. **C.2b bounded CUDA smoke-test scope: PASS.** This did not authorize or perform persistent deployment or validate CUDA through the HTTP worker. Remaining C work, including C.3, requires its own approval gate. Exit gate: all broader host evidence and rollback review pass and the user explicitly approves M02 closeout.

Prepare a dedicated deployment profile/runbook and rollback. Only after separate host/deployment authorization, validate the exact `large-v3-turbo` artifact and image/library pins on CUDA, measure resource use, and test cancellation/shutdown/recovery while leaving Ollama/Dify untouched.

Acceptance: approved CUDA device and compute type observed; model manifest digest verified; load, transcription and segment timestamps succeed; no CPU fallback; cold/warm load and request timing recorded; peak RSS and VRAM measured separately from estimates; overload, OOM/fault-latch and forced child exit behavior meet documented bounds; active and queued audio is released as specified; no shared service was modified; rollback commands address only the Speech Platform Compose project; evidence is reviewed and M02 closeout is explicitly approved.

Verification commands: `make verify PYTHON=.venv/bin/python`; `make stt-gpu-integration PYTHON=.venv/bin/python` (planned target, requires explicitly authorized host GPU and service startup); rendered Compose check; documented project-scoped smoke/rollback commands. No command in this phase may prune, restart or alter Ollama/Dify.

User validation: review measured results and limitations, inspect service status and logs for privacy, confirm shared services remain unchanged, run or review project-scoped rollback, then explicitly approve M02 closeout. Do not start M03 automatically.

#### M02-C.3 — Real CUDA transcription through the STT HTTP worker

Status: **PASS for the approved bounded CUDA HTTP integration scope**, accepted by the user on 2026-10-17. The third controlled attempt succeeded through the production aiohttp application. The first two attempts and MIME harness defect remain part of the history; see [implementation](implementation.md) and [verification](verification.md). Overall M02 remains incomplete.

Objective: validate one real transcription through the existing private aiohttp STT route and production CUDA adapter in an ephemeral test container. This is an HTTP worker integration check, not persistent deployment or complete C acceptance.

Existing support (OBSERVED by source inspection): schema-v3 application configuration supports explicit `device_policy.mode: cuda` and a CUDA compute type; the runtime selects the configured device and the faster-whisper adapter passes that device and compute type explicitly, failing closed without CPU fallback. `services.stt.http_server.create_http_app` provides bounded multipart upload, request deadline propagation, disconnect cancellation, structured errors, readiness and metrics. `STTApplication`/`AdmissionController` bound uploads, retained audio, queue and execution to one active job. The production decoder and child supervisor are already used by this route. Existing HTTP tests use a fake application; the C.2b diagnostic invokes the adapter directly. The CPU smoke uses the HTTP app and real model in an in-process aiohttp `TestServer`, but requires CPU mode. The CUDA Compose overlay requests all GPUs, while the base Compose defaults include a 256 MiB worker memory limit; neither is suitable unchanged as proof of a GPU-0-only, appropriately bounded isolated C.3 run.

Proposed isolated execution:

1. Reuse the C.2b approved immutable CUDA validation image and current repository `services/` source mounted read-only, after verifying image platform/digest and the exact lock inventory. This tests the current worker code against the approved runtime dependencies without building or deploying the production Compose service. It does not validate the production image build/baked source.
2. Use the existing diagnostic launcher/report handling. Launch one temporary non-root container with `--gpus device=0`, `--network none`, no published ports, read-only root and artifact/code/config mounts, and only the attempt report directory writable. Provide explicit bounded host RAM/CPU/PID limits. Run an HTTP smoke driver inside the container; it starts the production STT app on an ephemeral loopback `TestServer`, waits for `/healthz` and `/readyz`, sends one multipart request to `/internal/v1/transcriptions`, validates the JSON/segments without printing or persisting transcript text, closes the app, and confirms the supervised child has exited. No Gateway, Ollama or Dify networking is involved.
3. Use private schema-v3 CUDA config: `device_policy.mode: cuda`, configured GPU index 0 and `compute_type_cuda: float16`; confirm no CPU fallback. Use only the approved manifest-verified tiny model and permitted audio. Keep the worker bound to the test's loopback socket. Runtime free-VRAM preflight remains advisory and cannot reserve memory.
4. Remove only the attempt container after recording launcher/harness results and shared-service health. Preserve sanitized reports outside Git. Do not start the persistent Compose stack.

Implementation and validation artifacts:

1. `scripts/stt_cuda_http_smoke.py` uses the production HTTP application in `aiohttp.TestServer`/`TestClient`, strict app/deployment/worker configuration, manifest and audio verification, exact dependency inventory, and the existing sanitized atomic report runner. The fixture MIME type is an explicit validated experiment setting; multipart filename and MIME must agree even when the bind mount is extensionless. Shutdown has a separate bounded report and must confirm worker and child state.
2. Deterministic tests cover HTTP decode errors, upload admission, request deadlines, health/readiness, profile mismatch/override rejection, response privacy, and Docker isolation/resource argument validation.
3. `make stt-cuda-http-integration` requires operator-provided experiment inputs and calls the maintained launcher. The launcher verifies the local image/platform, app/deployment profile, configured free-VRAM gate, audio checksum, immutable image selector, non-root/no-network/no-port/root-readonly mounts, and explicit CPU/RAM/PID limits.
4. `docs/operations/stt-cuda-http-integration.md` documents source precedence, proposed resource bounds, exact invocation, preflight, retained evidence and cleanup. No Compose service or persistent deployment behavior was changed.

Acceptance criteria for C.3 PASS (not yet established):

- Before launch: approved immutable image and linux/amd64 identity, lock/dependency inventory, config/model/audio integrity, GPU 0 and explicit float16 policy, free-VRAM gate, no unexpected GPU process, and Ollama/Dify health are recorded. Any failed prerequisite stops the attempt.
- One non-root, network-isolated, no-published-port container starts the current STT HTTP application using read-only inputs and bounded resources. `/healthz` is alive and `/readyz` transitions to ready after model load.
- Exactly one successful multipart transcription traverses the HTTP handler, application admission, production decoder, supervised inference child and faster-whisper CUDA backend. The client fully reads the response; language and segment schema/timestamps pass validation. The report and logs contain no audio or transcript content.
- The diagnostic request uses an explicit supported audio media type from approved fixture configuration/metadata, and its multipart filename matches the declared format. Failure reports preserve only HTTP status, allowlisted public error code, fixed request stage and sanitized category.
- Explicit CUDA device 0 and float16 are demonstrated by validated config/runtime path, with no CPU fallback; no additional inference, warm-up, retry or model download occurs.
- The app and inference child shut down within documented bounds; container removal is confirmed; GPU state returns near baseline; Ollama/Dify health is unchanged to the available checks. Sanitized launcher and harness evidence is retained.
- A separate shutdown report records `completed_and_confirmed`, `attempted_but_unconfirmed`, or `failed_or_timed_out`; successful cleanup requires supervisor child-exit confirmation and worker readiness false. Container removal alone is insufficient.
- The offline suite passes, including the new deterministic HTTP negative/boundary cases. User reviews evidence and limitations before C.3 is marked PASS.

Deferred from C.3: CUDA concurrency/capacity, peak VRAM instrumentation, sustained/large-v3-turbo performance, real client disconnect during GPU inference, production image build reproducibility, persistent Compose deployment, Gateway routing, and active-load coexistence with Ollama/Dify. These remain broader C/M02 work.

Pre-execution decisions were approved for the accepted run: one target-host container attempt using the C.2b image and current source mounts, the 12,288 MiB free-VRAM gate, 4 CPU / 8 GiB RAM / 128 PID limits, and the already approved model/audio artifacts. These values were specific to that experiment and are not production defaults. No further execution is authorized by C.3 acceptance.

Acceptance evidence (OBSERVED on 2026-10-17; user accepted): one multipart request through production `TestServer`/`TestClient` returned HTTP 200. Response validation passed with language `ru`, five nonempty segments and valid timestamp bounds. CUDA device 0 and float16 were selected; the diagnostic reported no CPU fallback. Model load was 2.549 s, transcription 0.959 s, and HTTP integration 3.828 s. The independent shutdown report confirmed the worker was no longer ready and the supervisor child had exited; the container exited 0 and was removed. Ollama health passed before and after; Dify core health checks remained healthy and its web/proxy stayed running. Evidence is preserved outside Git at `/home/master/speech-platform-staging/M02/M02-C/M02-C.3/attempts/cuda-http-20261017-03/`.

Limitations (NOT ESTABLISHED): instrumented peak VRAM, concurrency, sustained load, production latency or throughput, persistent deployment, and active-load coexistence. The user accepted C.3 only for this one-request integration scope. M02 overall remains incomplete.

## Verification baseline

OBSERVED at M01 closeout: `make verify PYTHON=.venv/bin/python` passed at commit `734e223a249988a93df668a857831db7c2a43852`; this is historical and does not verify M02. OBSERVED for C.2b: the approved tiny artifact completed one bounded CUDA float16 transcription; see [verification](verification.md). Phase commands above are proposed; targets that do not exist yet must be added during their authorized phase. Broader GPU resource behavior and deployment remain NOT ESTABLISHED.

## Decisions and risks

Accepted decisions are in ADRs 0006-0009. Remaining M02 implementation details include async STT multipart/disconnect transport dependency, exact model/upstream revision and manifest digest, dependency/image lock, decoded-audio limits, operationally acceptable manual recovery, and performance/quality measurements during authorized design/implementation review. Estimates are not measurements. No GPU or deployment guarantee is established by this design closeout.
