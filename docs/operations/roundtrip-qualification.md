# TTS-to-STT round-trip qualification

See the [CLI reference](../cli/reference.md) for the broader command inventory;
this guide covers round-trip inputs, reports and interpretation.

The round-trip runner synthesizes each text fixture through the authenticated public Gateway TTS route, then transcribes that WAV through the public STT route with provider `local` and cloud-audio consent disabled:

```sh
mkdir -p samples/audio private/roundtrip
.venv/bin/python -m scripts.roundtrip --case en-polite --report private/roundtrip/en-polite.json
```

The live command requires a running Gateway, configured credentials in the repository's private `.env`, and an existing output directory. It runs one case at a time. Use `--language en|ru|sv` to filter or omit filters to run all `samples/text/*.txt` cases. `make test-roundtrip` runs all discovered fixtures (two sequential Gateway requests per fixture) and performs live inference; run it only in an approved GPU window. It is intentionally excluded from `make verify`.

During a run, concise case and TTS/STT stage progress is flushed to stderr; stdout retains per-case results and the final count/elapsed summary. Progress does not include fixture text, transcripts or credentials.

## Fixtures and generated audio

Add one UTF-8, nonempty reference per case as `samples/text/<language>-<case>.txt`, where language is `en`, `ru`, or `sv` and the remaining case name uses lowercase letters, digits, and hyphens. The language prefix selects the TTS language hint and same-language STT source/output. Fixture contents are not modified. Duplicate case names after Unicode normalization/case folding, unsupported prefixes, unreadable files and references without measurable text are rejected before requests.

Generated files use the matching name under `samples/audio/`, such as `samples/audio/en-polite.wav`. Audio files are ignored by Git. Existing WAVs are never reused or overwritten by default: the run stops before inference if any selected destination already exists. To explicitly regenerate selected cases, pass `--regenerate`; only each selected case's exact expected WAV path can be replaced. Replacement occurs atomically after successful TTS and WAV validation, so a failed or interrupted synthesis does not leave a partial WAV presented as complete. Unrelated files are untouched. The output directory must already exist. If valid generated audio exceeds the public STT request limit, the WAV is retained but STT is not sent; the report records that case as a technical failure.

## Reports and interpretation

`--report` writes a mode-0600, exclusive-create JSON report under `private/`. It includes the current local Git revision and whether the worktree is dirty, reference text and returned transcription for inspection, reference/audio SHA-256, WAV properties, per-stage HTTP/provider/timing/error metadata, WER/CER, technical status, and a `NOT_REVIEWED` human-review status. STT provider identity is recorded from the public response header. The current public transcription response does not identify the serving model, and the TTS contract does not guarantee provider/model identity; unavailable identities remain unset rather than being inferred from internal services. Console output omits text and transcripts. Keep the private report protected and remove it when no longer required. No report is written by default.

Normalization is deterministic and identified in each report as `speechplatform-roundtrip-text-v1`: Unicode NFC, case-folding, Unicode punctuation replaced by spaces, and whitespace collapsed. WER uses whitespace-delimited word tokens; CER uses the normalized character sequence including single spaces. Both use Levenshtein edit distance divided by the reference word or character count, respectively. Scores are not clamped and no quality threshold is applied. Punctuation treatment and whitespace tokenization are intentionally simple; language-specific tokenizers are not used.

These measurements describe the combined TTS → STT round trip: errors may arise from synthesis, recognition, or their interaction, and WER/CER cannot independently attribute them to either model. They describe recognition of SpeechPlatform-generated synthetic speech only. They do not establish human-speech accuracy, semantic equivalence, naturalness, or overall product quality. A successful technical run is reported separately from measured WER/CER and pending human review. STT serving-provider provenance is required and checked against `local`.

## Offline verification

The deterministic mocked tests run as part of ordinary `make verify PYTHON=.venv/bin/python` and therefore the existing release verification workflow. They need no Gateway, model, GPU or cloud access. They verify fixture parsing, metrics, request contracts, no-cloud routing, report privacy, and WAV lifecycle. Offline tests do not perform or establish live qualification.
