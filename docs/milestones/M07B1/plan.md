# M07B1 — Automated TTS-to-STT Round-Trip Qualification

## Scope

Implement a small sequential CLI that reads existing `samples/text/` fixtures, generates same-name WAV files using public Gateway TTS, transcribes them through public local-only STT, calculates deterministic WER/CER, and optionally writes private structured evidence. Reuse M07A request transport, authentication, multipart construction, response validation and WAV validation.

## Included

- `python -m scripts.roundtrip` with language/case selection, output directory, private report, regeneration and timeout options.
- Atomic generated WAV publication with exclusive creation by default; explicit regeneration limited to selected expected fixture paths.
- Offline deterministic tests integrated through existing `make verify` test discovery.
- A live-only `make test-roundtrip` target, excluded from `make verify`.
- Operational and milestone documentation.

## Excluded

No live inference in implementation verification, cloud requests, Gateway/worker changes, model downloads, deployment, semantic-quality thresholds, human-speech accuracy claims, or other M07B work.

## Acceptance and verification

- Validate the complete selected fixture/output set before network activity.
- Authenticate through the existing Gateway configuration; explicitly pin local STT and disable cloud audio.
- Preserve technical failures, timing, provenance, input/audio identities and measured WER/CER without calling metric success semantic PASS.
- Run focused offline tests, Ruff, `make verify PYTHON=.venv/bin/python`, and `git diff --check`.

Status: PASS; COMPLETE. The operator accepted M07B1 on 2026-10-25 after offline verification, nine-case live technical qualification and human listening review. See [result](result.md) and [user validation](user-validation.md).
