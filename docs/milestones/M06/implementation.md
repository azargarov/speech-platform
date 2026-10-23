# M06 implementation record

Status: **Application implementation NOT STARTED. M06A architecture and contract documentation finalized 2026-10-23.**

The operator approved the M06 architecture decisions for planning in the M06A request. This authorization covered documentation updates only. It does not authorize M06B application code, tests, deployment configuration changes, live qualification, deployment or commits.

## M06A documentation changes

- Reconciled [PLANS.md](../../../PLANS.md) with M05B's accepted closeout and M06's planning status.
- Replaced the proposed lifecycle/routing ADR with accepted planning decisions for STT lazy lifecycle and readiness, TTS lifecycle reuse, Ollama warmup, the public warmup contract, M05B routing preservation, and bounded GPU coordination.
- Reconciled this plan and the four milestone evidence records with the approved M06A–M06E stage sequence and gates.
- Preserved the M05B evidence and the pre-deployment backup; no backup files were changed.

No application source, API OpenAPI file, configuration, tests, deployment file, private runtime state, or production service was changed.

## Planned application scope by stage

- **M06B:** STT worker lazy load, internal warmup, safe idle unload/reload, readiness and lifecycle state. Reuse the supervised child process and existing admission/fault/cleanup controls.
- **M06C:** public Gateway warmup route, TTS warmup reuse, and configured-local Ollama empty-request warmup. Update the public OpenAPI contract before handler implementation.
- **M06D:** offline integration and regression verification.
- **M06E:** separately authorized live qualification; deployment requires a distinct explicit scope and rollback approval.

These are plans, not implemented changes. M05B qualification evidence remains outside M06 implementation scope.
