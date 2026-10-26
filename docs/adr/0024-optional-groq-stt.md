# ADR 0024: Optional, explicitly authorized Groq STT

- Status: accepted for v0.2.0 after offline verification and bounded live qualification on 2026-10-24
- Scope: public Gateway STT provider selection
- Extends: [ADR 0006 — STT model alias ownership](0006-stt-alias-ownership.md), [ADR 0019 — STT active cancellation](0019-stt-active-cancellation.md)

## Context

The Gateway has bounded, provider-aware FIFO STT admission, but production
requests currently use only local Faster-Whisper. Optional cloud transcription
must not inherit text transformation's independent cloud authorization. The
Gateway already buffers an admitted audio upload and has a 25 MiB request cap;
provider concurrency therefore remains deliberately bounded.

Groq's documented transcription endpoint accepts multipart audio and supports
`whisper-large-v3` and `whisper-large-v3-turbo`, JSON/verbose JSON responses,
and language hints. This integration uses transcription only. It does not use
Groq's separate English translation endpoint, arbitrary prompts, remote audio
URLs, or caller-selected provider model IDs.

## Decision

- Groq STT is disabled by default. When enabled, `GROQ_STT_API_KEY` (or the
  configured environment-variable name) is read from the Gateway environment.
  A missing or malformed key marks Groq STT unavailable and emits a
  provider-specific warning; it does not prevent Gateway startup or local STT.
  Deployment preflight reports optional cloud credential problems as warnings.
  The key is separate from `GROQ_API_KEY` used for text transformation.
- Cloud audio requires both the operator enabling the provider and the request
  setting `X-Allow-Cloud-Audio: true`. Text `allow_cloud` does not authorize
  audio. Omitted provider selection remains local-only without this consent.
- `X-STT-Provider: local|groq` pins a request. Without a pin, a consenting
  request is local-first and can be assigned to Groq only when local admission
  is occupied. Once assigned, failures do not trigger a retry or cross-provider
  fallback. One lease dispatches to exactly one provider.
- Local capacity remains one. Groq's configured provider capacity may be one
  or two, but total active STT operations are capped at two to limit Gateway
  audio retention under its 256 MiB container limit. The three waiting STT
  slots remain shared and request bodies are not read until assignment.
- At the configured 25 MiB request limit, a conservative transient-buffer
  estimate for two simultaneous Groq uploads is about 114 MiB (one bounded
  multipart request buffer plus one parsed audio copy per operation, allowing
  for `io.ReadAll` growth); adding a maximum 64 MiB TTS response and two bounded
  STT response/encoding pairs gives roughly 186 MiB before Go runtime, HTTP
  buffers, and allocator overhead. This leaves nominal headroom under 256 MiB,
  but it is an estimate, not a measured RSS ceiling or guarantee.
- The Gateway forwards a bounded multipart file, configured model, optional
  supported language hint, and `verbose_json`; it maps the result to the
  existing transcription JSON shape and adds `X-Speech-Provider`. No audio is
  logged or persisted. Rate limits map to bounded 429 responses; retries are
  not automatic. Other provider errors are sanitized.
- Groq is used only for transcription in the current public contract. Explicit
  cross-language translation, streaming, and non-empty platform `model`
  selection are rejected for Groq before transmission. Current public language
  support remains `auto`, English, Russian, and Swedish; unsupported detections
  return 422.

## Privacy and limitations

Sending a request to Groq transmits its audio outside the local environment.
Groq documents inference data as not retained by default, while allowing
temporary input/output retention for reliability or abuse investigation for up
to 30 days unless the account's data controls alter that handling. Operators
must review their organization's current settings and privacy obligations
before enabling cloud audio. References: [Groq speech-to-text API](https://console.groq.com/docs/speech-to-text), [Groq data controls](https://console.groq.com/docs/your-data).

The two-operation Gateway ceiling bounds request counts, not VRAM or total
process RSS. It does not reserve GPU capacity or account for other Ollama or
host workloads. Real Groq behavior, costs, account retention settings and
combined production resource capacity are not established by offline tests.

## Verification

The original startup requirement for an enabled provider credential was
relaxed: cloud providers are optional capabilities, while Gateway configuration
and mandatory local worker prerequisites remain strict. Explicit selection of
an unavailable Groq provider returns `provider_unavailable`; the Gateway never
dispatches that request elsewhere. `/readyz` continues to represent required
local STT/TTS worker readiness.

Stage A offline verification uses mocked HTTP providers and synthetic multipart
audio. A separately authorized live qualification on 2026-10-24 sent only three
operator-approved recordings to the configured local and Groq transcription
models. All eleven bounded requests (including the local/Groq concurrency pair)
returned successfully with compatible response mapping and provider
provenance. The comparison found high transcript agreement but had no verified
reference transcripts, so it establishes no accuracy winner or WER/CER. Groq
Turbo was faster than Large v3 on all three files; Turbo remains the configured
default based on latency, not claimed accuracy. Account-specific retention and
Zero Data Retention status remain unverified. Raw transcripts and audio are
excluded from this ADR; detailed qualification records remain in the ignored
private directory.
