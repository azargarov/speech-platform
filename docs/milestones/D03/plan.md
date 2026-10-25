# D03 — Exact-Image Rollback Qualification

## Objective

Exercise a simple native Compose rollback to the exact retained pre-D02
Gateway, STT and TTS image objects using a validated private configuration
snapshot, then restore the intended deployed revision `2ec766855c5c355bd312c47bb79549cf99c80b1f` through `make install`.

## Included

- Read-only verification of Git, deployed image/source identities, retained
  image objects, labels, config schema, project ownership and shared services.
- A private mode-restricted snapshot of the active `.env` and Gateway config.
- Local rollback aliases mapped to the exact retained image IDs and verified
  before and after Compose use.
- Fixed-project Compose render and `up --no-build --pull never` for only
  Gateway, STT and TTS.
- Authenticated local STT/TTS smoke checks on rollback and after restoration.
- Return to revision `2ec766855c5c355bd312c47bb79549cf99c80b1f` using its clean
  committed Make + Compose installation path.
- A concise exact-image rollback procedure in the current operations guide.

## Excluded

- Automatic rollback orchestration, persistent deployment state, D04 work,
  model downloads or modifications, credential changes, cloud inference,
  Docker pruning, or shared Ollama/unrelated-service lifecycle changes.

## Acceptance checks

- Initial Git and production state are recorded and consistent with authorization.
- Each rollback alias resolves to the expected retained image ID and role/source
  labels.
- Rollback configuration validates and old image config parsers accept it.
- Rendered Compose contains only the fixed `speech-platform` services and
  existing external Ollama network; invocation requests no build or pull.
- Rollback health, API authentication, STT/TTS smoke and shared-service
  preservation are observed.
- The intended revision is restored through Make + Compose with healthy
  services, expected image/source identities and no unexpected restarts.
- Operations guidance and evidence are updated; verification passes.

## Status

**PASS; COMPLETE (operator accepted 2026-10-25).** Rollback and
restoration executed and accepted on 2026-10-25. Review evidence in
[verification](verification.md). D04 is next planned.
