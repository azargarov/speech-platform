# M07B2 verification

## OBSERVED

Executed in `/home/master/speech-platform` on 2026-10-25. No live Gateway
requests, cloud calls, deployments or service changes were made.

- `.venv/bin/python -m ruff format scripts/transform_samples.py scripts/test_transform_samples.py` — PASS.
- `.venv/bin/python -m ruff check scripts/transform_samples.py scripts/test_transform_samples.py` — PASS.
- `.venv/bin/python -m unittest scripts.test_transform_samples -v` — PASS, 10 tests.
- `make verify PYTHON=.venv/bin/python` — PASS. This ran Go vet/race tests/build, Ruff checks, config and Compose validation, release checks, all Python script tests (92), TTS tests (63), governance validation, and lock checks.
- `git diff --check` — PASS.
- Targeted local-link validation for M07B2 and batch-operation documentation — PASS.

After the operator-reported HTTP 400 `invalid_options`, the focused request test
was updated to assert the flat public request fields and omission of the
unspecified optional `model`. The 10 focused tests, full `make verify`, and
`git diff --check` were rerun and passed. No live request was used to validate
the correction.

## Production prompt correction

After the authorized prompt revision:

- `go test ./internal/texttransform -run 'TestProductionPromptDefinesModeAndPreservationRules|TestModeAndTranslationOptionsRemainSeparateFromUserText|TestExampleLocalSerializedInputBudget' -count=1 -v` — PASS.
- `go test ./internal/texttransform -count=1` — PASS.
- `make verify PYTHON=.venv/bin/python` — PASS, including Go vet/race tests and build, Python script and TTS tests, configuration/Compose/release checks, governance validation, and dependency-lock checks.
- `git diff --check` — PASS.

The prompt tests establish static instruction presence and correct options/text
framing only. They do not establish model compliance, semantic preservation,
style differentiation or translation quality. Live comparison remains NOT
ESTABLISHED and was not performed.

The tests use mocked Gateway responses and establish request composition,
local-only flags, one STT call followed by nine sequential transformation
calls, validation, failure reporting and output handling. They do not establish
live Gateway behavior or linguistic quality. Live inference is NOT ESTABLISHED
and was not authorized in this implementation task.

## Qualification CLI model-selection correction

On 2026-10-25, after changing `scripts/qualify.py` to omit an unspecified model
field, the following offline checks were executed:

- `.venv/bin/python -m unittest scripts.test_qualify scripts.test_transform_samples`
  — PASS, 36 tests.
- `make verify PYTHON=.venv/bin/python` — PASS. Go vet/race tests/build,
  Ruff, configuration and Compose validation, release checks, 92 repository
  Python tests, 63 TTS tests, governance and dependency-lock checks completed.
- `git diff --check` — PASS.

The focused tests verify omitted default model, unchanged explicit alias
serialization, consent flag behavior, preservation of Gateway authorization
and unknown-alias error codes, and unchanged batch omission behavior. Mocked
aliases are deliberately synthetic; tests do not assume configured aliases
exist. The reported effective aliases are from a separate read-only
configuration inspection. No live request, inference, cloud call, deployment
or service change was performed. These checks establish client request
semantics only; current live Gateway responses for these model selections are
NOT ESTABLISHED here.

## Configurable production prompt

On 2026-10-25, the configurable prompt implementation was verified offline:

- `go test ./internal/config ./internal/texttransform ./cmd/gateway ./internal/gateway` — PASS.
- `.venv/bin/python -m unittest scripts.test_acceptance scripts.test_compose scripts.test_qualify scripts.test_transform_samples` — PASS, 58 tests.
- `.venv/bin/python -m unittest scripts.test_m05b_stage2b_gateway_acceptance scripts.test_m05b_stage2b_lifecycle` — PASS, 5 tests.
- `make verify PYTHON=.venv/bin/python` — PASS. Go vet, race tests and build; Ruff checks; configuration, Compose, release and OpenAPI checks; 92 script tests; 63 TTS tests; governance and dependency-lock checks all completed successfully.
- `git diff --check` — PASS.

The implementation loads the configured prompt at startup, keeps an immutable
text/SHA-256 snapshot, and swaps it only after a SIGHUP reload passes validation.
Each request retains one snapshot across provider attempts. The public Gateway
response adds `X-Speech-Prompt-SHA256`; qualification clients record it when
present. Tests cover startup validation, successful and rejected reloads,
fingerprint changes, request consistency during reload, signal handling and
response metadata. No live inference, deployment, restart or cloud request was
performed. Production activation of this code and live prompt reload behavior
remain NOT ESTABLISHED.
