# M02-D — STT v1 product path

Status: **PASS; COMPLETE (2026-10-21).** See [verification](verification.md),
[user validation](user-validation.md), and [result](result.md).

## Objective

Deliver an end-to-end, clean-checkout STT product path using Git, Docker
Compose, the existing faster-whisper CUDA worker and the verified persistent
model store. Keep historic deployment-state/snapshot work optional.

## Scope

- A stable Gateway multipart STT route with bounded request forwarding,
  worker readiness, consistent errors and exposure-appropriate authentication.
- Per-request source language (`auto|ru|en|sv`) and output language
  (`auto|ru|en|sv`); retain the existing internal `language` source alias.
- Automatic detection, detection probability when supplied by the backend,
  unsupported detected-language refusal, raw transcription preservation and
  explicit per-model translation capability. Preserve large-v3-turbo as the
  primary model and configure translation unavailable for it; reject
  unsupported cross-language requests with `unsupported_translation`.
- One Git-hosted production configuration, configurable host/model/GPU values,
  pinned build base/dependency inputs, validation, idempotent install, status
  and STT smoke commands without a `private/deployment/` dependency.
- User-facing installation/API/operations documentation and roadmap alignment.
- Focused unit and API tests; clean-checkout validation; an isolated Compose
  runtime test only when resource checks show it will not disturb existing
  Speech Platform services.

## Exclusions

- No change to the original standalone STT or existing M01E/experiment
  containers and bind mounts.
- No TTS inference, transcript refinement, cloud translation, external
  backup/NAS, generation adoption, snapshot capture, automatic rollback,
  image publication, tag creation or push.
- No new translation service and no model change.

## Design boundaries

- Gateway owns the public endpoint, request cap, authentication check, worker
  forwarding and readiness probe. It does not decode audio or choose a model.
- STT owns detection, supported-language policy, transcription and enforcing
  configured per-model translation capability. It does not call Gateway or TTS.
- Compose owns service identity, networks, restart policy, host exposure,
  resources, GPU selection and read-only model bind.
- The Make/CLI layer validates inputs and invokes exact project-scoped Compose
  commands. It does not create deployment history or operate unrelated
  containers.

## Acceptance criteria

1. A clean checkout contains the complete non-secret production configuration;
   install/plan/status/test-STT have no private deployment dependency.
2. Compose uses the existing model digest by configurable path, read-only,
   with worker UID/GID and supplementary artifact-reader group, one explicit
   GPU, restart policy, health/readiness and no worker host port.
3. The Gateway public API reaches STT through the private worker network and
   retains public behavior for health/errors/request limits.
4. Automatic and forced `ru`, `en`, and `sv` source selection are covered by
   deterministic tests. Unsupported detection, invalid codes, legacy alias
   conflicts and unsupported translation pairs fail explicitly.
5. Same-language and automatic output return raw transcription. Translation
   requests are gated by the selected model's configured capability, and
   `translated=true` is never returned for a model without that capability.
   Confidence is emitted only when genuinely supplied by automatic detection.
6. Configuration is strict; model and image inputs are immutable/pinned;
   `.env` and credentials remain private; loopback is the default exposure.
7. `make verify`, governance validation, `git diff --check`, clean-checkout
   checks, and focused tests pass. Any GPU/E2E check distinguishes observed
   runtime evidence from static validation and does not alter protected
   deployments.

## Risks and limits

- The deployed large-v3-turbo model supports multilingual transcription but
  does not reliably support speech-to-English translation. Its configuration
  disables translation; translation-capable models can opt in independently.
- The GPU is shared with three active STT containers. An isolated test must
  pass a conservative free-memory/process preflight and one-request bound;
  otherwise GPU execution remains NOT ESTABLISHED pending a safe window.
- A new image digest/tag cannot be published here. This work can validate
  reproducible local builds and prepare a release candidate; registry
  publication/tagging needs separate operator approval.

## Verification commands

- Focused STT and Gateway tests.
- `make verify PYTHON=.venv/bin/python`
- `make governance-check PYTHON=.venv/bin/python`
- `git diff --check`
- Clean clone at the implementation commit followed by offline config/Compose
  validation; no lifecycle operation in the clean clone.
- Isolated runtime installation and real multilingual audio only after model,
  GPU and port preflight; project identity must be unique and cleanup scoped.

Implementation checks and operator-reported runtime acceptance are recorded
in [verification.md](verification.md). The operator accepted M02-D as PASS on
2026-10-21; see [user-validation.md](user-validation.md) and [result.md](result.md).
