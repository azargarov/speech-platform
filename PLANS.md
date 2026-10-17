# Milestones

- M00: experimental benchmark; supplied observations and provenance are recorded. Original source files were not recovered. Under a user-approved M01 scope decision (2026-10-17), source recovery is deferred and does not block M01 closure; this is not a passed preservation test, and reproduction is not claimed.
- M00B: engineering governance and reusable Codex skills. **PASS; closed 2026-10-17 after user-approved validation.** Long-term adherence during implementation remains unverified. See [records](docs/milestones/M00B/plan.md).
- M01: foundation and architecture. **PASS; closed after user validation.** See [M01 result](docs/milestones/M01/result.md). Runtime deployment and GPU passthrough remain unverified; no deployment or M02 work was performed.
- M02: STT inference. **M02-A: PASS. M02-B: PASS. M02-C.2b bounded CUDA smoke: PASS for its approved scope. M02-C.3 CUDA HTTP integration: PASS for the accepted one-request scope. Overall M02 remains incomplete.** One production HTTP request completed using CUDA device 0 and float16, detected `ru`, and returned five validated segments. Peak VRAM, concurrency, sustained performance, production latency/throughput and persistent deployment remain NOT ESTABLISHED. See [M02 plan](docs/milestones/M02/plan.md), [result](docs/milestones/M02/result.md), and [STT design](docs/architecture/m02-stt-design.md).
- M03: TTS inference (not started).
- M04: authentication enforcement, validation and complete request routing (not started).

No automatic advancement or commits. User approval is required before committing. User validation and explicit closeout approval gate each milestone completion. M00B closeout does not automatically authorize M01 resumption.
