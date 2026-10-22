# M04 implementation record

Status: **Implementation and technical validation are complete; M04 is closed PASS following operator acceptance.**

## Design summary

See [plan.md](plan.md) for scope, responsibilities, compatibility, limits and
acceptance criteria. Parsing and composition remain in the TTS worker, request
format validation/forwarding remain in the Gateway, and provider/model
internals are unchanged.

## Changes and deviations

- Added the additive `input_format` (`text` default, `ssml`) field to public
  and internal contracts, Gateway validation/forwarding and the TTS worker.
  Plain text retains its existing 10,000-character path and mode defaults.
- Added a standard-library XML parser for namespaced SSML 1.1 `<speak>`, nested
  `<lang xml:lang>` and `<break time>` only. It rejects DTD/entity declarations,
  unsupported tags/attributes, bad language/time values and configured bound
  violations before loading the model.
- Added configured byte, character, segment, element, nesting, pause, silence,
  estimated-output and actual-output limits. Language inheritance maps
  regional tags to the existing base-language hint.
- Added PCM16 WAV frame validation and all-or-nothing composition. Segment audio
  must be mono 48 kHz PCM16; requested milliseconds become exactly 48 frames
  per millisecond of zero-valued silence. All pieces stay in memory until
  successful composition.
- No new dependency, service, model behavior or model internals were added.
  The only plan refinement was to bound XML depth and total markup elements in
  addition to speech segments, preventing deeply nested parser input.
- Built the M04 Gateway and TTS images locally and exercised one bounded
  English–Swedish request through the canonical loopback Gateway. Recorded the
  private sample and request metadata under ignored `private/m04/`.
- Restored the M03B Gateway/TTS images after the request. Final identities and
  health match the pre-test baseline; STT and unrelated services were
  preserved. See [verification.md](verification.md) for observed evidence and
  the rollback config permission correction.
- Operator listening acceptance and explicit M04 closeout are recorded in
  [user-validation.md](user-validation.md) and [result.md](result.md).
