# M02-D verification evidence

Status: **implementation checks PASS; runtime acceptance NOT ESTABLISHED**.
This is evidence for implementation review, not milestone closeout or operator
acceptance.

## OBSERVED

- `make verify PYTHON=.venv/bin/python` — passed after the final code changes.
  This ran Go vet/race tests/build, Ruff checks, strict Gateway/STT/TTS config
  validation, legacy and canonical Compose rendering, release validation,
  repository tests, governance structural checks and STT lock checks.
- `.venv/bin/python -m unittest scripts.test_product_deployment services.stt.tests.test_faster_whisper`
  — 12 tests passed, including a regression check that backend unload clears
  the loaded model reference.
- `.venv/bin/python -m unittest discover -s services/stt/tests` — 64 tests
  passed.
- `go test -race ./...` — passed.
- `make governance-check PYTHON=.venv/bin/python` — passed.
- `docker compose --env-file .env.example -f compose.yaml config --quiet` —
  passed.
- `git diff --check` — passed before commit.
- Operator-reported model verification for release `v0.1.2`, model
  `large-v3-turbo`, manifest
  `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6` —
  passed against `/srv/speech-platform/models`. Operator-reported UID 65532
  and supplementary GID 988 read check exited 0. No artifact was copied or
  moved.
- Current host observation: the selected GPU had 8412 MiB free and three
  active compute processes associated with existing workloads. Existing
  Compose projects and containers remained running; no lifecycle command was
  issued by this work.
- `.env` was mode 0600 and ignored by Git.

## NOT ESTABLISHED

- A fresh `make plan` stopped at the read-only model integrity check because
  this process has no cached sudo authorization for the root-owned model
  store. The operator's earlier verification remains PASS; this is a privilege
  limitation in the current shell, not evidence of artifact failure.
- Product `make install`, Compose startup/redeployment and Gateway-to-worker
  runtime calls were not run. Three existing GPU compute processes make an
  install/inference rehearsal unsafe for the protected deployments.
- Real Russian, English and Swedish audio inference, automatic detection,
  forced source-language output and translation pairs were not run against
  this product deployment. No Swedish fixture was available in the repository.
- Restart recovery and clean-checkout runtime installation were not exercised.
- STT v1 operator acceptance and release-tag readiness are not established.

## Translation behavior implemented, not runtime-verified

- `auto` or matching source/target returns the original-language transcript.
- Russian to English and Swedish to English call faster-whisper's built-in
  translation task and retain the original transcription in the response.
- English to Russian/Swedish, Russian to Swedish and Swedish to Russian return
  `unsupported_translation`.
- Detected languages outside `ru`, `en` and `sv` return
  `unsupported_detected_language`.

These combinations have deterministic unit coverage; their real-audio quality
and runtime behavior remain NOT ESTABLISHED.

## Safe next operator actions

1. In a planned GPU maintenance window, ensure the selected GPU has no
   protected inference workload running.
2. Run `sudo -v`, then `make plan` for a fresh privileged read-only artifact
   check.
3. Review the project name, API bind/port and current Compose project listing.
4. Run `make install` only after an isolated product deployment is authorized.
5. Submit private Russian, English and Swedish audio fixtures with
   `make test-stt AUDIO=... SOURCE_LANGUAGE=auto OUTPUT_LANGUAGE=auto`, then
   repeat with forced source and advertised output selections.
6. Record results and obtain operator validation before closing M02-D or
   declaring STT v1 accepted.
