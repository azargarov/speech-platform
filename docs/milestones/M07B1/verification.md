# M07B1 verification

## Offline implementation verification — OBSERVED

Executed in `/home/master/speech-platform` on 2026-10-25. No Gateway, worker, Ollama, cloud or model requests were made by M07B1 verification.

- `.venv/bin/python -m unittest scripts.test_roundtrip -v` — PASS; 24 tests after CLI progress reporting. Includes deterministic fixture discovery/language parsing, Unicode normalization and metrics, authenticated mocked TTS/STT, stable JSON report structure, content-free flushed stage progress and ordering, elapsed times, failure/interruption output, multi-case numbering, and live-only Make target separation.
- `.venv/bin/python -m unittest scripts.test_roundtrip scripts.test_qualify scripts.test_api_smoke -v` — PASS; 46 tests in the run before the final two round-trip error-path tests were added. The final round-trip suite including those cases passed separately (18 tests).
- `.venv/bin/ruff check scripts/roundtrip.py scripts/test_roundtrip.py` — PASS.
- `.venv/bin/ruff format --check scripts/roundtrip.py scripts/test_roundtrip.py` — PASS as part of final `make verify` (93 Python files already formatted).
- `.venv/bin/python -m scripts.roundtrip --help` — PASS; CLI options rendered without requests.
- `make -n test-roundtrip PYTHON=.venv/bin/python` — PASS; renders `python -m scripts.roundtrip`.
- `make -n verify` and focused Make-target test — PASS; `test-roundtrip` is not a verification prerequisite.
- `discover_fixtures()` — PASS; found the nine existing `en`, `ru`, and `sv` fixtures in deterministic order. Only names, character counts and hashes were inspected; fixture contents were not copied into output. Existing untracked sample text files were not modified.
- `git check-ignore -q samples/audio/en-polite.wav` — PASS; generated WAV path is ignored by the existing global audio rule.
- Final `make verify PYTHON=.venv/bin/python` — PASS, exit 0. Ruff, Go vet/race tests/build, configuration and rendered Compose checks, release check, full script/STT/TTS test discovery, governance validation/tests, and STT/TTS lock checks passed. STT: 92 tests; TTS: 63 tests; governance: 2 tests.
- Final `git diff --check` and changed-document local-link checks — PASS.
- After progress reporting changes: `make verify PYTHON=.venv/bin/python` — PASS, exit 0; `.venv/bin/python -m unittest scripts.test_roundtrip -v` — PASS, 24 tests; `git diff --check` — PASS.
- After recording the live qualification and updating closeout records: `make verify PYTHON=.venv/bin/python` — PASS, exit 0. This run passed Ruff and formatting, Go vet/race tests/build, Gateway/STT/TTS configuration and Compose checks, release validation, repository script tests, STT (92 tests), TTS (63 tests), governance (2 tests), and dependency lock checks. `git diff --check` was run for the closeout changes and passed.
- Final acceptance/commit-candidate run on 2026-10-25: `make verify PYTHON=.venv/bin/python` — PASS, exit 0; Go vet/race tests/build, Ruff/format, configuration and Compose checks, release validation, repository script tests, STT (92 tests), TTS (63 tests), governance (2 tests), and lock checks all passed. No live inference was invoked.

## Live user qualification — OBSERVED / USER-REPORTED

Operator supplied the live qualification summary and human listening findings on 2026-10-25. The private evidence file `private/m07b1-full-roundtrip.json` was inspected read-only; only case IDs, statuses, metrics, stage timings and provenance were extracted into this record. No transcript, reference text or audio content is reproduced here.

Evidence records source revision `0b213aad23655df72bc944fed96c3fbc91096b3f` with a dirty worktree. All nine cases report HTTP 200 for TTS and STT, technical PASS, STT provider `local`, and WER/CER measured. Cloud audio consent was false. The operator reports no live cloud inference.

| Case | WER | CER | Exact normalized match |
| --- | ---: | ---: | --- |
| en-informal | 0.040000 | 0.022727 | No |
| en-polite | 0.000000 | 0.000000 | Yes |
| en-rude | 0.000000 | 0.000000 | Yes |
| ru-informal | 0.090909 | 0.032520 | No |
| ru-polite | 0.050000 | 0.007042 | No |
| ru-rude | 0.000000 | 0.000000 | Yes |
| sv-informal | 0.043478 | 0.022388 | No |
| sv-polite | 0.000000 | 0.000000 | Yes |
| sv-rude | 0.000000 | 0.000000 | Yes |

The operator reports total execution of 170.658 seconds. The private JSON start/end timestamps span 170.633 seconds; this 0.025-second difference is retained transparently rather than silently reconciled. Case-level TTS/STT elapsed measurements are in the private report.

The operator separately reports listening to all nine generated recordings: English and Swedish were accepted without observed issues. Russian was understandable and textually complete, with unnatural rising intonation at the end of some utterances and a female synthesized voice for text containing masculine first-person grammatical forms. These are listening observations; no cause is established. WER/CER measure the combined TTS → STT path and do not attribute error to either model. They do not establish general human-speech accuracy.

## NOT ESTABLISHED

- Independent TTS and STT quality attribution, human-speech accuracy, broad language coverage, and quality beyond these nine fixtures.
- Cause of the Russian prosody or voice/gender-form mismatch.
- GPU residency/resource behavior, model coexistence, and behavior under concurrent or external GPU workloads.

The existing release workflow runs `make verify`; its script test discovery includes `scripts/test_roundtrip.py`. No workflow or runner configuration change was needed. The live-only `make test-roundtrip` target is excluded from `verify`.
