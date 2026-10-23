# M06 operator validation

Status: **M06A architecture decisions accepted 2026-10-23. M06B implementation authorization is pending a separate user request.**

## M06A architecture decision

The operator reviewed the preliminary read-only repository assessment and approved the architecture decisions in the M06A request. The decisions are recorded in [ADR 0022](../../adr/0022-model-lifecycle-predictive-warmup.md) and [the M06 plan](plan.md):

- STT lazy loading, internal warmup, 60-second initial idle timeout, safe active/admitted-request protection, reload and child-reap cleanup boundary.
- STT process liveness and on-demand readiness semantics, including readiness while intentionally unloaded.
- Reuse TTS's existing lazy lifecycle, warmup, admission and VRAM guard.
- Native empty-request Ollama warmup with finite nonzero keep-alive; preserve shared Ollama and do not explicitly unload or send `keep_alive:0`.
- Bounded synchronous operation-oriented warmup API with `stt`, `tts`, and `text_transform`; no job framework, content generation, user content or cloud warmup.
- Preserve M05B selection and fallback behavior. Defer `on_local_warming` and `next_eligible`.
- Keep GPU coordination local and limited; no general scheduler or forced eviction.
- Use the stages M06A through M06E and keep offline verification separate from live qualification and deployment.

This is approval of the planning architecture. It is not a milestone closeout, implementation authorization, live-qualification authorization, deployment authorization or commit approval.

## Pending decision gates

| Gate | Status |
|---|---|
| M06A architecture accepted | **ACCEPTED 2026-10-23** |
| M06B application implementation | **PENDING separate authorization** |
| M06C Gateway/API implementation | **PENDING M06B contract and separate authorization** |
| M06D offline verification | **PENDING implementation** |
| M06E live qualification | **NOT AUTHORIZED** |
| Deployment | **NOT AUTHORIZED; separate scope and rollback approval required** |
| M06 milestone closeout | **NOT APPLICABLE** |
| Commit | **NOT AUTHORIZED** |

Before M06E, operator approval must cover target identity, shared Ollama eviction acceptance or isolation choice, run envelope, monitoring, recovery and rollback. Do not infer approval from M06A acceptance.
