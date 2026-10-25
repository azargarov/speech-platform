# D04 — Retire Legacy Deployment Infrastructure

## Objective

Remove obsolete Python deployment orchestration and the unused shared Ollama
network mutator while preserving Make + Docker Compose operations, preflight
safeguards, rollback behavior and independent authenticated API smoke checks.

## Scope

- Delete `scripts/product_deployment.py` and its dedicated test suite.
- Delete `scripts/ollama_network.py` and its mutation tests after confirming no
  active callers remain.
- Retain read-only Ollama name/network/model validation in preflight.
- Keep only focused smoke-test client behavior as independent API tooling.
- Remove active references to the retired commands and update ADR-0023.
- Run offline verification and one authorized live regression on `llm`.

## Acceptance

- No active code, test, Make target, CI or current operations guide depends on
  the retired modules or commands.
- Make + Docker Compose is the only deployment mechanism.
- Initialization, read-only preflight, image/build/CUDA safeguards, status,
  logs, stop, model metadata checks and rollback documentation remain intact.
- Authenticated local STT and TTS smoke commands work independently.
- Full `make verify`, Ruff, Make/Compose/documentation checks and live regression
  pass; shared Ollama and unrelated services remain unchanged.

## Status

Offline qualification passed. The operator has authorized the implementation
commit and live regression. The clean committed source safeguard requires the
implementation commit before installation. D04 remains open pending production
regression and operator acceptance.
