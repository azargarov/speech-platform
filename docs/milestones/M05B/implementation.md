# M05B implementation record

Status: **M05B IN PROGRESS; Stage 1 implementation and Stage 2A/2B qualification are operator-accepted. Stage 2A completed all 18 sequential 4K/8K requests; seven outputs per context failed lexical invariants and remain failed. The operator retains local Qwen only for user-reviewed transformations, with no quality guarantee. Stage 2C network provisioning and deployment tooling are implemented and offline-verified. No production Gateway deployment or service restart occurred.**

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
being changed. The operator authorized M05B Stage 1 offline implementation. Later requests
authorized the bounded Stage 2A and Stage 2B live qualifications, whose results
were accepted with the limitations recorded in their qualification documents.
Stage 2C deployment preparation is authorized; deployment and M05B closeout
remain separately gated. Repository governance requires separate operator
authorization before committing.
Record implementation files and deviations below.

## Stage 1 acceptance — 2026-10-22

The operator accepted Stage 1 with PASS after the implementation and offline
verification recorded below. No implementation scope change was requested.
Stage 1 acceptance did not qualify live providers, deployment, GPU coexistence,
tokenizer/template bounds, model unload/cancellation, or production readiness.
Later bounded qualification results are recorded in the Stage 2A/2B records. M05B remains IN PROGRESS.

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

## Stage 2A preflight — 2026-10-22

The operator authorized only local Qwen 4K/8K infrastructure qualification.
Recorded the read-only GPU/Ollama/service baseline and a bounded nine-case
synthetic English/Swedish/Russian procedure in
[stage-2a-qualification.md](stage-2a-qualification.md). Prepared the private
mode-0600 case file under ignored `private/m05a/`; existing M05A case files,
prompts and run outputs were not modified. The runner's offline validation
passed. No tracked implementation code changed.

The operator subsequently requested a non-destructive revision that does not
require exclusive server ownership. The procedure specifies finite
`keep_alive: "60s"`, no unload requests, sequential 4K/8K runs, pre-run and
continuous residency/GPU sampling, contamination handling, and explicit
separation of inference, residency, natural expiry and recovery observations.
The operator later authorized the bounded comparison. One 4K request returned
successfully, but a post-response import error in the private harness prevented
saving its response and token metadata. Execution stopped under the procedure's
no-retry rule; no 8K comparison request was sent. The Qwen model expired
naturally and sampled GPU memory returned to baseline. No shared Ollama settings
or services were changed. Later bounded Stage 2B live qualification was separately authorized and is recorded below.

## Stage 2B offline qualification preparation — 2026-10-22

Added only test coverage to the existing Stage 1 Go test files: full option
forwarding across all 36 supported transformation/format/language combinations,
the configured reasoning payload fields for both retained Groq models, and an
authenticated generated request through the public Gateway handler using a
fake provider. No production Go source, API contract, production configuration,
Compose file or running service was changed. The private isolated profile and
bounded live proposal are recorded in
[stage-2b-qualification.md](stage-2b-qualification.md). Live inference,
deployment and M05B closeout remain pending separate operator decisions.

## Stage 2A resumed execution — 2026-10-22

After the operator accepted the root-cause analysis and offline regression
results, formatted the existing private runner, fixed its repository-root
import path, and preserved the earlier run artifacts by directing resumed
evidence to a fresh private directory. The tracked response helper persists
the bounded raw body before parsing and invariant checks. Its quality-failure
classification does not abort the corpus; harness, completion and infrastructure
failures still stop execution. Ruff lint/format, actual-path import verification,
four response-helper regression tests and the nine-case offline corpus check
passed before inference.

The bounded 4K then 8K run completed all 18 requests with no monitor errors or
abort conditions. Responses, measurements and a private output review are in
[stage-2a-qualification.md](stage-2a-qualification.md). No unload, restart,
deployment or shared Ollama configuration change occurred. Stage 2A operator
acceptance with limitations and Stage 2B are now operator-accepted; deployment and closeout remain separately gated.
