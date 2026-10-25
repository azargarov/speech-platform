# D02 — Minimal Make + Docker Compose Deployment

## Objective

Provide an operator path based on Make, root Compose, the independent read-only
preflight, and small focused helpers. Keep the Python product installer available
as fallback during this milestone.

## Included

- Fixed Compose project identity (`speech-platform`) and local Docker context.
- Deployment environment sanitization so inherited shell settings cannot override
  the reviewed `.env` values.
- Full-stack `make install`, scoped `status`, `logs`, and `stop` commands.
- Exact running-image retention before build, source/role/platform label checks,
  bounded network-disabled CUDA visibility probes, Compose health wait, and
  readiness checks before install succeeds.
- Explicit rejection/migration guidance for obsolete Gateway expected-image pins.
- Offline tests using mocked Docker/Compose commands.

## Excluded

- Deleting `scripts/product_deployment.py` or its tests.
- Editing private configuration, building/deploying images, running CUDA probes,
  or restarting services as part of offline implementation.
- Ollama lifecycle/network mutation, model download, inference, destructive
  Docker cleanup, automatic rollback orchestration, or changes to worker behavior.

## Acceptance checks

- Environment, Compose project and service scope are fixed and tested.
- Validation/build/identity/CUDA failures stop before `compose up`.
- Existing image IDs are preserved before replacement.
- Install only operates on a clean committed revision.
- `make verify PYTHON=.venv/bin/python`, focused tests and `git diff --check`
  pass.
- Target-host installation and local smoke qualification are separately
  recorded; do not claim them from offline checks.

## Risks and gate

The obsolete Gateway image pins were removed from the private `.env` under
operator authorization on 2026-10-25 after a private mode-0600 backup. The
resulting configuration validates. Target preflight still fails both pinned
STT/TTS model metadata checks; model artifacts are outside this scope and must
not be altered to bypass the gate. Installation also requires a clean committed
source tree.

## Status

Implementation is committed as `cb627310dd939f7e8a3ce6c5a433007ce57e20b6`.
Offline checks pass. Target-host installation is blocked by STT/TTS model
metadata preflight failures; no service replacement or smoke inference occurred.
D02 qualification and user validation remain pending; D02 is not closed.
