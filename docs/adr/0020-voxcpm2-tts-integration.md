# ADR 0020: VoxCPM2 in the existing TTS worker

- Status: Accepted for M03B implementation; production acceptance pending
- Date: 2026-10-21
- Supersedes: ADR 0018, decision 6 only, for current TTS behavior

## Context

M03A operator listening selected VoxCPM2 for initial integration across
English, Russian, Swedish and mixed-language input. The existing platform has
a Go Gateway, Python TTS worker, and one canonical Compose TTS service. The
worker is currently health-only. VoxCPM2's pinned synthesis API accepts
multilingual text but exposes no native language-code detector or language
parameter. The measured 10-step configuration is the quality baseline; the
8-step candidate is faster but has not passed quality acceptance.

## Decision

Implement VoxCPM2 behind the current TTS worker and Gateway. The public request
uses text, optional language hint (`auto`, `en`, `ru`, `sv`) and optional mode
(`quality`, `fast`, `auto`), returning a complete WAV PCM16 response. `auto`
language sends text without language metadata. Explicit language hints may
guide the model through its supported instruction input but are not detected
language results. `quality` uses 10 steps. `fast` returns a clear unavailable
error until its output is accepted. `auto` mode initially selects quality.

The TTS worker owns lazy load, warm-up, state, idle unload and one-at-a-time
GPU inference. Client disconnect does not terminate active native inference;
its result is discarded when the disconnected socket cannot receive it. The
Gateway owns public validation, authentication, limits, routing and response
forwarding. Model files are pre-provisioned at a read-only digest-bound model
store path; runtime download is disabled. Existing Compose and Make paths are
retained, with TTS resource settings separated from STT.

## Alternatives

- Keep TTS health-only: rejected because the current task authorizes a backend.
- Add another inference container or generic GPU scheduler: rejected because
  the existing TTS service is the boundary and no orchestration framework is
  justified.
- Route language to an external detector: rejected because VoxCPM2 already
  synthesizes multilingual inputs and the operator reported successful
  multilingual output; this should be revisited only if tests expose a need.
- Enable 8-step as default: rejected until listening acceptance establishes
  quality parity.

## Consequences and limits

TTS and STT remain separate services with private networking. TTS inference is
serialized within its worker, but this does not coordinate GPU use with STT.
Free VRAM is only a point-in-time signal; OOM/resource errors must be handled
without retry loops. Production use remains gated on license/notice review,
operator listening and live shared-GPU validation. The implementation does
not claim real-time performance or production readiness.
