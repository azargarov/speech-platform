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
resulting configuration validates. The parent model-store directory grants
reader-group traversal but not listing; preflight's access check now matches
that layout. `sg stt-model-reader` preflight passes. This execution process
lacks GID 988 in its active supplementary groups, so ordinary preflight cannot
walk the model artifacts. Do not bypass that active-access failure or alter
model artifacts. Installation also requires a clean committed source tree.

## Status

Implementation is committed. Offline checks pass. The group-scoped preflight
passes, but ordinary preflight in this execution process cannot read model
artifacts because its active groups are stale. No service replacement or smoke
inference occurred. Direct retained-image rollback selection also remains
unqualified; D02 qualification and user validation remain pending.
