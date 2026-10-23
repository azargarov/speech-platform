# M06 operator validation

Status: **M06A architecture accepted; M06B offline implementation/verification accepted; M06C offline implementation/verification accepted; M06D offline integration/regression accepted; M06E live qualification accepted; M06 COMPLETE — all accepted 2026-10-23 with documented limitations.**

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
| M06B application implementation and offline verification | **ACCEPTED 2026-10-23; acceptance is limited to offline implementation and verification and includes the documented non-cooperative-native-call limitation** |
| M06C Gateway/API offline implementation and verification | **ACCEPTED 2026-10-23, including documented shared-GPU, native model-loading cancellation and unqualified installed-Ollama limitations** |
| M06D offline integration and regression qualification | **ACCEPTED 2026-10-23** |
| M06E live GPU qualification | **ACCEPTED 2026-10-23 with documented limitations** |
| Scoped deployment of Gateway/STT | **ACCEPTED; corrected Gateway deployed from commit `f2f2d337271d5ed677daf13a8c5fcd875d68000a`; STT/TTS unchanged in the follow-up deployment** |
| M06 milestone closeout | **ACCEPTED 2026-10-23; M06 COMPLETE** |
| M06B closeout commit | **COMPLETED by the 2026-10-23 closeout** |
| M06C closeout commit | **AUTHORIZED by the 2026-10-23 closeout request** |

The operator accepted M06A through M06D at their recorded stages and accepted M06E live qualification and M06 overall on 2026-10-23. M06B's non-cooperative native-call limitation remains. Final live evidence and deployed image identity are recorded in [verification.md](verification.md).

The operator's final acceptance on 2026-10-23 covers M06E live qualification and M06 overall, including the known limitations: explicit SSML was not live-qualified; GPU coexistence is established only for tested combinations; Ollama is shared and not exclusively controlled by SpeechPlatform; non-cooperative native calls require conservative cleanup; and installed model residency is not guaranteed beyond observed conditions. Text-transformation routing and cloud authorization remain unchanged, and no cold/warming-local fallback policy was added.
