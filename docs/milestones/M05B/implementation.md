# M05B implementation record

Status: **M05B IN PROGRESS; Stage 1 offline implementation PASS and operator-accepted (2026-10-22). No deployment or live inference.**

2026-10-22: inspected architecture, configuration/HTTP code, public OpenAPI,
canonical and historical Compose patterns, evaluation runners and M05A records.
Created the [plan](plan.md), proposed [ADR 0021](../../adr/0021-configurable-text-transformation.md),
verification, operator-validation and pending result records. Updated the
roadmap and the future M05 umbrella to point to this proposal.

Preserved existing dirty `PLANS.md` changes and untracked M05A documents/scripts.
M05A evidence and approval records were not edited. No production source,
contract, configuration, secret or running service was changed. No evaluation,
inference, deployment, commit or milestone closeout was performed.

M05A closeout was independently verified in Git: commit
`a5d22ab2ce7e52b2dc15380b5391832d0523ab8e`, titled `docs: close M05A evaluation`,
records PASS/COMPLETE and the accepted three-model retention. Its files are not
being changed. The operator authorized M05B Stage 1 offline implementation.
Stage 2, deployment, live inference and closeout remain unauthorized. The
current operator request authorizes a commit of intended Stage 1 implementation
and documentation files.
Record implementation files and deviations below.

## Stage 1 acceptance — 2026-10-22

The operator accepted Stage 1 with PASS after the implementation and offline
verification recorded below. No implementation scope change was requested.
Stage 2 remains pending and unauthorized; this acceptance does not qualify
live providers, deployment, GPU coexistence, tokenizer/template bounds, model
unload/cancellation, or production readiness. M05B remains IN PROGRESS.

## Stage 1 offline implementation — 2026-10-22

Implemented the optional strict `text_transform` YAML model and a non-secret
sample configuration in `configs/gateway-text.example.yaml`; the existing
`configs/gateway.yaml`, Compose files, `.env.example`, M05A records and running
services were not changed. Added `internal/texttransform/` with request/options
validation, exact raw passthrough, byte-based context preflight, stable model
selection, local/cloud filtering, per-request provider suppression, one-call
sequential fallback, bounded Ollama and OpenAI-compatible HTTP adapters, and
service-lifetime cancellation/admission. Wired the additive Gateway route,
per-path request cap, shutdown lifetime, safe metadata logs and counters. Added
the public OpenAPI schemas and route.

Offline tests cover nested strict configuration and credentials, API auth and
route registration, raw passthrough, ordered fallback, explicit selection,
cloud policy, missing credentials, duplicate/invalid JSON, context boundary and
multilingual preservation, provider wire payloads, incomplete responses, 429
scope and request/service cancellation. These tests do not qualify actual model
semantics, upstream protocol compatibility, network access, tokenizer/template
bounds, GPU coexistence, or remote inference termination. Context preflight
uses serialized UTF-8 byte size as a conservative count plus configured framing
overhead; per-model tokenizer/template assumptions remain Stage 2 gates.

No Compose/env overlay or operational runbook was added: deployment routing,
secrets and rollback remain Stage 2 and were not needed for offline checks. No
deployment, restart, live inference, M05B closeout or commit was performed.

## Astra plan revision — 2026-10-22

Revised the existing plan and proposed ADR, preserving the one-module/two-adapter
architecture and three initial models. No M05B Astra review text was found in
project records; the nine supplied findings A–I are the review source. The
[response matrix](plan.md#12-astra-response-and-remaining-decisions) maps the
corrections. Plan sections 3.1, 3.2, 5 and 8.1 are authoritative for startup,
context, failure/lifecycle and GPU policy; acceptance documents reference them.
Updated roadmap and acceptance to two stages, added explicit TTS/SSML and bearer
regression checks, and removed redundant configuration/response fields.

The starting worktree already contained modified PLANS.md and M05/plan.md,
untracked ADR 0021 and M05A/M05B records, and six M05A scripts/tests. Preserved
that work; only the eight M05B-related planning/roadmap documents were edited.
No source, production config, private data, running service or M05A record was
changed; no implementation, deployment, closeout or commit occurred.

## Stage 1 context-budget review — 2026-10-22

Compacted the production system prompt from 1,477 to 1,069 UTF-8 bytes while
retaining its transformation rules. Added an offline fixture pinning the
example local serialized-text budget at 867 bytes, plus escaped-JSON exact
boundary/one-over coverage. The focused test command and evidence, including
the tokenizer/API and output-reservation assessment, are in the
[context-budget review](context-budget-review.md). The example and production
configuration, local context, output reservation, adapters, STT/TTS, deployment
and GPU settings were not changed. No inference, deployment, Stage 2, closeout
or commit occurred.
# Stage 1 context expansion investigation (2026-10-22)

- Updated only the local Qwen entry in `configs/gateway-text.example.yaml` to
  8,192 context tokens. Kept the prompt, conservative common preflight,
  configured 512-token prompt overhead and 1,024-token output reservation.
- Updated the offline example-budget regression to pin 4,963 serialized ASCII
  input bytes at 8K. Added a synthetic longer dictated-text test proving 4K
  rejects and 8K accepts before provider dispatch; existing Unicode and JSON
  escaping boundary tests remain in place.
- Added `--num-ctx {4096,8192}` to the M05A sequential runner, retaining 4K as
  its default and recording the selected context in run metadata and summaries.
  Prior benchmark outputs and M05A evidence were not edited.
- Prepared the controlled comparison protocol in
  `qwen-context-comparison.md`. No runtime, shared Ollama configuration,
  production Gateway, STT/TTS service or live inference was contacted.
- Design/boundary: this is example configuration and offline budget behavior;
  M05A remains the isolated sequential measurement harness. Actual context
  acceptance, GPU resource impact and Stage 2 suitability remain unmeasured.
