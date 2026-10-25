# M07B1 user validation

**Status: PASS; OPERATOR ACCEPTED 2026-10-25.** The following results were supplied by the operator on 2026-10-25 and checked against the private structured run report where available. The report and generated audio remain private.

When separately authorized, start with one case in a suitable GPU window:

```sh
mkdir -p samples/audio private/roundtrip
.venv/bin/python -m scripts.roundtrip \
  --case en-polite \
  --report private/roundtrip/m07b1-en-polite-001.json
```

The command makes one public TTS request followed by one public STT request, explicitly pins STT to local and disables cloud-audio consent. It refuses an existing WAV or report path. For a later rerun of that exact fixture, operator must explicitly add `--regenerate`; this replaces only `samples/audio/en-polite.wav` after a successful, validated synthesis. Do not treat successful HTTP/status checks or WER/CER as semantic-quality acceptance. Review the private reference/transcription evidence and audio as appropriate.

## Recorded live validation

The operator reports all nine cases completed with technical PASS, five exact normalized TTS → STT matches, WER/CER for all cases, 170.658 seconds total execution, and no live cloud inference. Case-level results and the 0.025-second difference between operator-reported duration and report timestamp span are recorded in [verification](verification.md).

Human listening review was supplied separately from technical and metric results: English and Swedish accepted without observed issues; Russian was understandable and textually complete, with unnatural rising intonation at the end of some utterances and female voice for text containing masculine first-person grammatical forms. These observations do not establish a cause. No claim of general human-speech accuracy or independent TTS/STT attribution is made.

All nine reference text fixtures are included in the M07B1 commit. Generated WAVs remain ignored. No additional inference was performed for this closeout. The operator explicitly accepted M07B1 with the limitations above. M07B2 remains a separate proposed milestone and is not authorized by this acceptance.
