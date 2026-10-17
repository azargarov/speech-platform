# M02 STT inference plan

Status: design closeout checks passed; final user approval pending; implementation NOT STARTED. M02-A is the next approval gate. This plan does not authorize M02 inference code, service startup or deployment. The accepted architecture is documented in [m02-stt-design.md](../../architecture/m02-stt-design.md) and its network boundary in [ADR 0009](../../adr/0009-worker-network-reachability.md).

## Scope

Implement one provider-neutral STT application using a single faster-whisper adapter on CPU and CUDA. Use one resident model, one active job, bounded upload/admission queues and a persistent supervised inference subprocess. Resolve stable model aliases in STT. Verify immutable model artifacts offline. Keep public API engine-independent; implement only the private STT worker path. Keep TTS unchanged. Preserve M01 health-only config behavior.

Initial `llm` deployment policy is explicit CUDA with no CPU fallback. A separate CPU-only profile proves portability. No public Gateway inference routing/authentication (M04), second adapter, streaming, diarization, batching, multiple resident models, dynamic scheduling, model eviction, automatic OOM retry, runtime model download, Ollama/Dify control or deployment without separate authorization.

## Phases and entry gates

Each phase is a reviewable deliverable. User approval is required before beginning each phase; successful verification does not advance automatically.

### M02-A — Application and execution foundation

Entry gate: M01 PASS (satisfied); separate explicit user approval for M02-A. Exit gate: all acceptance criteria and verification pass, records are updated, and user validates A before B is proposed.

Deliver typed domain/ports, alias catalog, versioned strict inference config and deployment config; legacy health-only compatibility; manifest schema/validation; worker/model lifecycles; admission and byte accounting; supervised child protocol; health/readiness; safe errors and metrics. Use fake backend and fake device/process adapters. Do not add faster-whisper, CUDA or start containers in this phase.

Acceptance: unknown/missing/duplicate/invalid config fails; old M01 health-only config still starts health control with readiness 503; artifact path/digest/file errors fail before child model load; exactly one model and active job; queue count and bytes enforce boundaries; cancellation releases queued work once and active resources only after completion/confirmed child exit; worker liveness stays independent from model readiness; saturation is 429 without readiness flapping; shutdown drains then cancels/reaps; no payload logging or persistent audio; Compose statically enforces internal `stt_private` and `tts_private` networks, Gateway attached to both, each worker attached only to its own network, no worker published ports, and Gateway as the only host-published service; TTS and public contract unchanged.

Verification commands: `make verify PYTHON=.venv/bin/python` (includes rendered Compose and static topology validation); focused new suite `PYTHON=.venv/bin/python -m unittest discover -s services/stt/tests -v`; `git diff --check`. CI runs the fake-backend suite without GPU. The focused command is a planned test location to create in A. Runtime network reachability remains unverified until separately authorized deployment.

User validation: review config/schema and failure policy; run the listed commands locally; confirm legacy health-only compatibility, static network topology, and explicit M02-A acceptance. ADR 0009 is accepted for design; no host access or deployment is part of M02-A.

### M02-B — faster-whisper CPU/CUDA adapter and private STT operation

Entry gate: M02-A is implemented, verified and explicitly user-accepted; separate approval for M02-B. Exit gate: CPU adapter acceptance and verification pass, user reviews evidence and explicitly accepts B before C is proposed.

Add one adapter and its locked dependency/image profile; bounded audio decode; immutable artifact loading; actual effective capability reporting; internal transcription route; timestamps; CPU-only profile; explicit CUDA profile; structured metrics/errors. Provision models offline. Do not add Gateway public routing or any other adapter.

Acceptance: adapter contract suite passes on CPU; a pinned licensed small artifact runs an offline CPU smoke test with correct result schema/language and segment bounds; supported/unsupported timestamp and language behaviors map to existing internal errors; manifest is verified before load; invalid precision/device combinations fail closed; CPU profile does not import NVIDIA packages; CUDA configuration rejects missing/incompatible device without CPU fallback; cancellation tests exercise real adapter checkpoints and the supervised process boundary; no audio/transcript persistence or payload logging; generated OpenAPI remains engine-neutral; offline runtime test confirms no model downloads.

Verification commands: `make verify PYTHON=.venv/bin/python`; `make stt-cpu-integration PYTHON=.venv/bin/python` (planned target, using a provisioned immutable test artifact); `make compose-check PYTHON=.venv/bin/python`; `git diff --check`. No GPU is required for CI. CUDA runtime checks remain NOT ESTABLISHED until M02-C. The Compose check verifies rendered static topology only; it does not start containers.

User validation: review the private worker protocol and generated configuration; run CPU integration with documented artifact provenance; verify audio cleanup and logs; explicitly accept M02-B. No target deployment.

### M02-C — Authorized `llm` GPU validation and closeout

Entry gate: M02-B is implemented, verified and explicitly user-accepted; separate explicit authorization for target-host access and deployment. Exit gate: all host evidence and rollback review pass and the user explicitly approves M02 closeout.

Prepare a dedicated deployment profile/runbook and rollback. Only after separate host/deployment authorization, validate the exact `large-v3-turbo` artifact and image/library pins on CUDA, measure resource use, and test cancellation/shutdown/recovery while leaving Ollama/Dify untouched.

Acceptance: approved CUDA device and compute type observed; model manifest digest verified; load, transcription and segment timestamps succeed; no CPU fallback; cold/warm load and request timing recorded; peak RSS and VRAM measured separately from estimates; overload, OOM/fault-latch and forced child exit behavior meet documented bounds; active and queued audio is released as specified; no shared service was modified; rollback commands address only the Speech Platform Compose project; evidence is reviewed and M02 closeout is explicitly approved.

Verification commands: `make verify PYTHON=.venv/bin/python`; `make stt-gpu-integration PYTHON=.venv/bin/python` (planned target, requires explicitly authorized host GPU and service startup); rendered Compose check; documented project-scoped smoke/rollback commands. No command in this phase may prune, restart or alter Ollama/Dify.

User validation: review measured results and limitations, inspect service status and logs for privacy, confirm shared services remain unchanged, run or review project-scoped rollback, then explicitly approve M02 closeout. Do not start M03 automatically.

## Verification baseline

OBSERVED at M01 closeout: `make verify PYTHON=.venv/bin/python` passed at commit `734e223a249988a93df668a857831db7c2a43852`; this is historical and does not verify M02. Phase commands above are proposed; targets that do not exist yet must be added during their authorized phase. GPU results and current dependency/model pins remain NOT ESTABLISHED.

## Decisions and risks

Accepted decisions are in ADRs 0006-0009. Remaining M02 implementation details include async STT multipart/disconnect transport dependency, exact model/upstream revision and manifest digest, dependency/image lock, decoded-audio limits, operationally acceptable manual recovery, and performance/quality measurements during authorized design/implementation review. Estimates are not measurements. No GPU or deployment guarantee is established by this design closeout.
