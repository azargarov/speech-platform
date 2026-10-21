# M02-D verification evidence

Status: **PASS; COMPLETE (2026-10-21).** Implementation checks and operator-
reported runtime acceptance are recorded below. Operator runtime evidence is
attributed and is not represented as a local execution by this closeout.

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
- A detached clean worktree at commit `94d40a4` passed
  `make verify PYTHON=/home/master/speech-platform/.venv/bin/python`, including
  all 426 script tests and 64 STT tests. The worktree had no `.env`; canonical
  Compose static rendering also passed. No containers were started.
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

## Historical implementation checkpoint limitations (superseded where noted below)

- A fresh `make plan` stopped at the read-only model integrity check because
  this process has no cached sudo authorization for the root-owned model
  store. The operator's earlier verification remains PASS; this is a privilege
  limitation in the current shell, not evidence of artifact failure.
- Product `make install`, Compose startup/redeployment and Gateway-to-worker
  runtime calls were not run. Three existing GPU compute processes make an
  install/inference rehearsal unsafe for the protected deployments.
- At the implementation checkpoint, real Russian, English and Swedish audio
  inference had not been run against this product deployment. The operator
  later reported successful real Russian/English transcription; Swedish
  runtime behavior remains NOT ESTABLISHED.
- Restart recovery and clean-checkout runtime installation were not exercised.
- At the implementation checkpoint, STT v1 operator acceptance was pending;
  operator acceptance is recorded below. Release-tag readiness is not
  established by this milestone closeout.

## Pre-correction translation behavior (superseded; not runtime-verified)

- `auto` or matching source/target returns the original-language transcript.
- Russian to English and Swedish to English call faster-whisper's built-in
  translation task and retain the original transcription in the response.
- English to Russian/Swedish, Russian to Swedish and Swedish to Russian return
  `unsupported_translation`.
- Detected languages outside `ru`, `en` and `sv` return
  `unsupported_detected_language`.

These combinations have deterministic unit coverage. The later operator
runtime rejection evidence is recorded below; translation quality is not
established because unsupported pairs are rejected rather than translated.

## Historical safe next operator actions

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

These actions were the pending procedure at the implementation checkpoint and
are superseded by the operator acceptance recorded below.

## Operator runtime acceptance (2026-10-21)

Evidence provenance: the following target-runtime observations were supplied
by the operator for this closeout. They were not executed or independently
reproduced by the local documentation verification commands.

- **OBSERVED (operator-reported):** canonical deployment revision was
  `3aa5f68c1d9a058ed2714b7b257c5b258a23c00a`.
- **OBSERVED (operator-reported):** active CUDA inference was confirmed before
  client cancellation. Cancellation returned nonfatal outcome `cancelled`.
- **OBSERVED (operator-reported):** inference child PID `2639811` survived the
  client disconnect, and GPU activity completed afterward.
- **OBSERVED (operator-reported):** a distinct follow-up Russian transcription
  succeeded after cancellation.
- **OBSERVED (operator-reported):** Gateway and STT remained healthy and ready.
  No unexpected child exit or fatal backend event was observed.
- **OBSERVED (operator-reported):** real Russian and English transcriptions
  succeeded. Unsupported language pairs were explicitly rejected with
  `unsupported_translation`.
- **INTERPRETATION:** the observations accept the bounded M02-D CUDA
  cancellation behavior and multilingual product path for the canonical
  deployment revision. They do not establish Swedish runtime behavior,
  translation quality, sustained load, capacity, or release-tag readiness.
- **NOT ESTABLISHED:** independent local reproduction of the target runtime
  event; behavior outside the supplied deployment and request conditions.

Local closeout verification commands and their actual outcomes are recorded
after documentation edits in the final closeout entry below.

## Documentation closeout verification (2026-10-21)

- **OBSERVED:** `make governance-check PYTHON=.venv/bin/python` exited 0;
  structural governance validation passed and both governance tests passed.
- **OBSERVED:** `git diff --check` exited 0.
- **OBSERVED:** a local Python Markdown-link check over `PLANS.md` and all five
  M02-D records found no missing relative targets (6 files checked).
- **INTERPRETATION:** these checks establish repository governance structure,
  changed-text whitespace integrity and local documentation link targets. They
  do not independently establish the operator-reported runtime observations.

# Cancellation regression verification (2026-10-21)

- **OBSERVED:** `.venv/bin/python -m unittest services.stt.tests.test_runtime`
  passed: 25 tests, exit 0.
- **OBSERVED:** `make verify PYTHON=.venv/bin/python` passed, exit 0. It
  included Go vet/race tests/build, lint and format checks, configuration and
  Compose validation, 434 script tests, 63 STT tests, governance checks, and
  STT lock validation.
- **OBSERVED:** `git diff --check` passed after implementation edits. It will
  be rerun after final documentation/scope staging.
- **NOT ESTABLISHED:** CUDA runtime cancellation, real client disconnect during
  native CTranslate2 inference, and target-host deployment were not exercised.

## Minimal runtime acceptance procedure (operator action pending)

Prerequisites: the isolated M02-D product deployment is already running and
ready; use private local Russian and Swedish audio files under `private/`, with
one short clip for successful calls and one long Russian clip known to run
longer than the cancellation delay. Do not use this procedure against
protected deployments. Set `AUDIO_RU`, `AUDIO_SV` and `AUDIO_RU_LONG` to those
paths in the shell. The command prints transcript text to the terminal; do not
redirect it to a tracked file.

1. Confirm readiness without changing lifecycle state:

   ```sh
   make status PYTHON=.venv/bin/python
   ```

2. Validate Russian transcription and check the returned metadata identifies
   Russian with `translated` false:

   ```sh
   make test-stt PYTHON=.venv/bin/python AUDIO="$AUDIO_RU" SOURCE_LANGUAGE=ru OUTPUT_LANGUAGE=ru
   ```

3. Confirm Russian-to-English is rejected because the deployed model has
   translation disabled:

   ```sh
   make test-stt PYTHON=.venv/bin/python AUDIO="$AUDIO_RU" SOURCE_LANGUAGE=ru OUTPUT_LANGUAGE=en
   ```

   Expect HTTP 400 with code `unsupported_translation`.

4. Confirm Swedish-to-English receives the same explicit refusal:

   ```sh
   make test-stt PYTHON=.venv/bin/python AUDIO="$AUDIO_SV" SOURCE_LANGUAGE=sv OUTPUT_LANGUAGE=en
   ```

   Expect HTTP 400 with code `unsupported_translation`.

5. Start a long request through Gateway, then abort the client while the request
   is active. For a local loopback API with no bearer token:

   ```sh
   curl --max-time 2 --silent --show-error \
     -F "audio=@$AUDIO_RU_LONG;type=audio/wav" \
     -F 'source_language=ru' -F 'output_language=ru' \
     http://127.0.0.1:8080/v1/stt/transcriptions >/dev/null
   ```

   Expect curl exit 28. For authenticated or non-loopback setups, use the
   configured API URL and bearer token. Confirm the request was active before
   the two-second abort using existing request/inflight telemetry or observed
   request duration; otherwise repeat with an appropriately longer audio clip
   and delay. The client result is discarded, while the supervisor consumes
   the original child response before another request can use its IPC channel.

6. After the cancelled request has completed worker cleanup, submit a fresh
   short request and confirm HTTP success plus a Russian result:

   ```sh
   make test-stt PYTHON=.venv/bin/python AUDIO="$AUDIO_RU" SOURCE_LANGUAGE=ru OUTPUT_LANGUAGE=ru
   ```

Record the deployment identity, sanitized request outcomes, timing and
readiness before/after. Do not record audio or transcript text in Git. This
procedure is an acceptance plan, not an observed runtime result; deployment,
CUDA cancellation behavior and operator acceptance remain NOT ESTABLISHED.

## M02-D translation capability correction (2026-10-21)

- **OBSERVED:** `make verify PYTHON=.venv/bin/python` passed after the
  capability correction. It included Go vet/race tests/build, Ruff checks,
  Gateway/STT/TTS config validation, Compose rendering, release validation,
  433 script tests, 64 STT tests, governance validation and STT lock checks.
- **OBSERVED:** `.venv/bin/python -m unittest
  services.stt.tests.test_runtime.ApplicationTests
  services.stt.tests.test_config_artifacts -v` passed (21 tests); the final
  full STT test suite also passed with the additional guard assertion.
- **OBSERVED:** `make governance-check PYTHON=.venv/bin/python` and
  `git diff --check` passed after the final edits.
- **OBSERVED:** product config retains `large-v3-turbo` as `default_model` and
  declares `translation_supported: false`. Deterministic application tests
  verify Russian-to-English and Swedish-to-English return
  `unsupported_translation`, same-language and automatic transcription return
  raw text with `translated: false`, and an impossible backend claim of
  `translated: true` is rejected.
- **INTERPRETATION:** capability is a validated per-model configuration value.
  Existing configurations that omit it retain the previous translation
  behavior for compatibility; the product and CUDA large-v3-turbo configs set
  it explicitly to false. Other model configurations can explicitly opt in.
- **NOT ESTABLISHED:** real-audio translation quality, CUDA inference,
  deployment/redeployment and operator acceptance were not exercised. No
  model was changed and no service was deployed.
