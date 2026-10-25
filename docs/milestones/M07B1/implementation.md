# M07B1 implementation record

## OBSERVED

Added `scripts.roundtrip` as one focused CLI module. It discovers UTF-8 reference fixtures in deterministic filename order, validates supported language-prefixed names and text before any request, then sends sequential authenticated public TTS and STT requests. TTS uses fixture-language hint, `quality` mode and no audio processing. STT uses matching source/output language and explicitly sends `X-STT-Provider: local` plus `X-Allow-Cloud-Audio: false`. It reuses M07A's token/origin validation, bounded HTTP transport, multipart construction, STT schema checks and WAV validation. It stops after authentication, connection, timeout, provider mismatch, output, rate-limit or server failures.

WER uses whitespace-delimited normalized tokens; CER uses normalized characters. Both use Levenshtein distance, NFC, casefolding, punctuation-to-space and whitespace collapse, identified in reports as `speechplatform-roundtrip-text-v1`. These scores measure combined TTS → STT round-trip error and cannot independently attribute errors to either model. Reports record the local Git revision and publicly returned provider metadata; model identities unavailable in public operation responses remain unset. Reports distinguish technical status, measured metrics and pending human review; reference/transcription text appears only in an explicitly requested private report created mode 0600.

Generated WAVs use exact matching case names, mode 0600, and are never reused or overwritten unless `--regenerate` is supplied. Initial writes use exclusive creation; regeneration writes a temporary sibling and atomically replaces only the selected expected fixture output after WAV validation. Failed or interrupted writes attempt to remove incomplete files and report if cleanup cannot be confirmed. No unrelated audio paths are removed. `.gitignore` already ignored WAV files globally; its audio section now explicitly describes fixture/generated audio. Added a live-only `make test-roundtrip` target, not a `verify` prerequisite. Existing `make verify` discovers the new offline tests through its current `scripts/test_*.py` discovery and the existing release workflow invokes `make verify`; no CI runner or workflow change was needed.

No dependencies, Gateway/worker behavior or API contract changes were added. Existing reference text fixtures were read only and left unchanged. No live inference, deployment, cloud call or model operation was performed.

The CLI emits flushed, content-free case and TTS/STT stage progress to stderr. Existing per-case results remain on stdout, and its final result line includes technical success/failure counts and elapsed time; JSON report fields are unchanged.

## INTERPRETATION

The reported WER/CER characterize generated synthetic speech recognition only. They do not establish human-speech accuracy, semantic equivalence or synthesis quality. Live qualification requires separate authorization; human review remains pending.
