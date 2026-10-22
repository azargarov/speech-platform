# M04 — Minimal SSML 1.1 Support

Status: **PASS; COMPLETE (2026-10-22)** for the bounded implementation and acceptance scope. Operator listening and closeout are recorded in [user-validation.md](user-validation.md) and [result.md](result.md).

## Goal and boundaries

Add an explicitly selected, small SSML input subset to the existing TTS speech
route for single-file English, Swedish and Russian vocabulary audio. Preserve
plain-text behavior and the existing model modes. SSML is parsed by the TTS
worker; the Gateway validates and forwards the format selection. Composition
returns one mono PCM16 WAV at 48 kHz after all speech segments succeed.

Reference: [W3C Speech Synthesis Markup Language (SSML) Version 1.1](https://www.w3.org/TR/speech-synthesis/).
This is a documented subset, not a claim of full SSML 1.1 compliance. The
supported elements are `<speak>`, nested `<lang xml:lang>` and `<break time>`.
Root documents require the SSML namespace, `version="1.1"` and `xml:lang`.
Language tags are limited to `en`, `ru`, `sv` and two-letter regional subtags
for those primary languages; regional tags map to the existing base language
instruction and do not guarantee accent selection or detected language.

Out of scope: voice selection, prosody, pitch, emotion, temperature, phonemes,
external audio, custom repetition syntax, model changes, new services,
databases, orchestration frameworks and client applications.

## Design and compatibility

- Public and internal JSON contracts gain additive `input_format`, enum
  `text|ssml`, default `text`. Existing clients and omitted-mode behavior stay
  unchanged. With SSML, request-level `language` must be omitted or `auto`;
  document `xml:lang` attributes control segment context. Existing TTS mode semantics remain: `fast`, `quality`,
  `high_quality`, and `auto`.
- Gateway owns request validation/forwarding and context propagation. TTS owns
  XML parsing, language inheritance, segment bounds, model calls and WAV
  composition. STT remains independent.
- The TTS worker parses a fully bounded document with the Python standard
  library, rejects DTD/entity declarations, enforces namespace/version/root
  language and allowlists every element/attribute. XML whitespace-only
  formatting nodes are ignored; non-whitespace text is preserved in order.
- Text fragments with their effective language and fixed-duration breaks form
  one ordered plan. Language subtags map to existing `en`, `ru`, or `sv` model
  hints. Each text fragment uses the existing serialized lifecycle; native
  inference is allowed to drain as today. All generated audio remains in
  memory until the entire document succeeds; errors return no partial audio.
- Individual breaks accept integer `ms` or decimal `s` to millisecond
  precision, converted to an exact frame count at 48 kHz. Adjacent breaks are
  retained independently and compose to their exact summed silence.
- Strict worker configuration bounds SSML bytes, aggregate speech characters,
  speech segment count, XML element count and nesting depth, per-break duration,
  total silence, estimated output size and actual composed output bytes. Public
  request size remains 64 KiB.
- No new dependency is planned. Existing outputs must be validated as mono,
  PCM16, 48 kHz before composition; mismatched generated audio fails closed.

## Acceptance criteria

1. Plain-text requests remain backward compatible, including defaults, errors,
   modes and WAV response behavior.
2. Explicit `input_format=ssml` accepts the documented namespaced 1.1 subset
   with ordered text, breaks and supported nested language tags.
3. The parser rejects malformed XML, missing/wrong namespace or version,
   unsupported elements/attributes, bad language/time tags, DTDs and entities
   with structured errors and no external resource access.
4. Input bytes, aggregate text, speech segments, pause duration, total silence,
   estimated output and actual output have configured upper bounds.
5. Language context inherits and nested `<lang>` overrides it for descendant
   text; English, Russian and Swedish all map to existing worker hints.
6. Composition preserves segment order and inserts exactly the requested
   silent frames. It produces one valid mono PCM16 48 kHz WAV.
7. A failure in any segment returns an error, never a successful partial WAV.
   Existing request cancellation behavior, serialized inference and shutdown
   draining remain intact.
8. Gateway forwards `input_format`; public/internal OpenAPI schemas and TTS
   operations documentation agree with runtime behavior and configured limits.
9. Focused tests cover all cases in the user request. `make verify
   PYTHON=.venv/bin/python` passes.
10. A bounded live Gateway English–Swedish vocabulary request yields one valid
    WAV. STT identity/state and unrelated services remain unchanged; exact
    rollback inputs and a private listening sample are prepared. Operator
    listening acceptance and explicit M04 closeout are recorded in the
    milestone result.

## Verification and live-test plan

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest services.tts.tests.test_tts -v`
- `go test ./internal/gateway`
- OpenAPI/config/Gateway focused checks and `make verify PYTHON=.venv/bin/python`.
- Before target changes, inspect `docker compose ... ps`, immutable image IDs,
  container IDs, start times and restart counts for Gateway, TTS and STT;
  confirm the scoped Compose project and current rollback images/config.
- Rebuild only required Gateway/TTS image(s), deploy only those services with
  Compose `--no-deps --no-build`, request a short SSML sample through the
  loopback Gateway, validate the returned WAV, and verify all service
  identities/health. Restore the previous Gateway/TTS images and TTS config
  after sample capture, including on success, because listening acceptance is
  still pending. Verify the restored baseline. Do not touch STT, Ollama, Dify,
  M00 or unrelated Compose projects.
- Keep sample, request metadata and rollback overlays under ignored `private/`.
  Record exact commands, observed identities, errors, checksums and limitations
  in `verification.md`; expose no transcript/audio payload in tracked evidence.

## Risks and limits

- Segment-per-call inference increases total latency; model synthesis is not
  streaming and each native call remains non-interruptible. A disconnect must
  not result in partial audio being returned as success.
- The estimate is a protective heuristic, not a duration guarantee. The actual
  WAV byte bound is authoritative.
- VoxCPM2's existing language controls are hints. Regional tags do not select
  a known accent, and language correctness remains unestablished until operator
  listening.
- Existing M03 production licensing, cold-start latency and sustained-load
  limitations remain applicable.

## User decision gate

Implementation and technical verification were followed by operator review
of the private sample and explicit closeout approval. The closeout authorization
permits a local commit of scoped M04 changes; it does not authorize push, tag,
deployment or another milestone.
