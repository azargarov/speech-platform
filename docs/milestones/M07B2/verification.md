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

## M07 comprehensive qualification CLI follow-up

### OBSERVED — offline

Executed in `/home/master/speech-platform` on 2026-10-25:

- `.venv/bin/ruff format scripts/qualify.py scripts/api_smoke.py scripts/test_qualify.py` — PASS.
- `.venv/bin/ruff check scripts/qualify.py scripts/api_smoke.py scripts/test_qualify.py` — PASS.
- `.venv/bin/python -m unittest scripts.test_qualify scripts.test_api_smoke scripts.test_roundtrip scripts.test_transform_samples -v` — PASS, 73 tests.
- `make verify PYTHON=.venv/bin/python` — PASS. Go vet/race tests/build, Ruff, Gateway/STT/TTS config checks, Compose and release validation, 92 script tests, 63 TTS tests, governance validation and dependency-lock checks completed.
- `git diff --check` — PASS.

The new tests verify expected API-error matching and mismatch, STT model
multipart serialization and Groq model rejection, SSML selection, and CLI enum
alignment with the public OpenAPI contract. These tests use mocked responses
and do not establish provider availability or linguistic quality.

### OBSERVED — current runtime and local smoke

Read-only `make status PYTHON=.venv/bin/python` before and after local requests
reported Gateway, STT and TTS healthy on source
`0628bf763069440189c59944d36a8db8cc3b8bfc` with image IDs:

- Gateway: `sha256:d6556df44b90afeef2662aebd531c0a4e909faf5f8c80e4b77ece9eb54454251`
- STT: `sha256:78a8b0b0e0b0c0f434f5445b2ed63ecde40c1ce0bbf3aa7483af7ff06c45b7dd`
- TTS: `sha256:5f633dc86f71eaca954358313df08d3ef5cd55c05c0516a76785e519727cf6d1`

One request per operation, sequentially, completed through the existing
authenticated Gateway:

- Local STT on `samples/audio/en-polite.wav`: HTTP 200, provider `local`,
  client elapsed 4.488 s.
- Local TTS synthetic text request: HTTP 200, client elapsed 94.890 s. The
  returned mono PCM16 WAV was 48 kHz, 3.840 s, 368684 bytes. Gateway does not
  expose public TTS model/provider identity.
- Local-Qwen Written English transformation of the designated synthetic
  `en-rude` transcript: HTTP 200, provider `host-ollama`, model `local-qwen`,
  `generated=true`, `fallback_occurred=false`, prompt SHA-256
  `75c2b419ea92029b2b391e55a9e2eaae894c37630d03d12f2b1a353ed547530c`,
  client elapsed 10.130 s.

Private content-free reports and the TTS WAV are in
`private/m07-qualification-20261025/`, created with mode 0700; files have mode
0600. The transformation output was not retained. No cloud request was sent.

### OBSERVED — cloud activation blocked

Read-only inspection found the active private Gateway config has text cloud
disabled (`allow_cloud=false`) and Groq STT disabled. The configured Gateway
secret environment file `private/cloud.env` is absent. A separate private raw
credential file `private/groq_api` exists with mode 0600; its value was not
read into output or validated against Groq. No credential file or Gateway
configuration was changed.

`make preflight PYTHON=.venv/bin/python` exited 2 with 31 PASS, 2 WARN, 2 FAIL
and 2 SKIP. Both critical failures were pinned STT and TTS model-store
manifest/file metadata checks. It also reported the source tree not committed,
as expected for this uncommitted implementation. Accordingly no install,
restart or cloud-policy activation was attempted. Groq STT and both Groq text
models remain NOT ESTABLISHED through the current Gateway. There is no
Gateway-only deployment target; the existing `make install` path updates all
three services together and requires passing preflight and a clean committed
source tree.

### INTERPRETATION / NOT ESTABLISHED

The local smoke proves these three live API paths worked for the stated
requests only. It does not establish translation/style quality, Groq
credentials' validity, Groq routing, cloud account controls, or semantic
preservation. The full M07 provider matrix remains pending cloud configuration,
passing deployment prerequisites and the separately approved final
activation. M07B2 remains in progress; no user acceptance or milestone
closeout is recorded here.

### M07 diagnostic/API discrepancy follow-up — OBSERVED 2026-10-25

TTS failure investigation:

- The private CLI report records HTTP 503, API code `resource_exhausted`,
  elapsed 0.286 s, a client-generated ID, no server request ID, no response
  headers, and `failure_stage=gateway_response`. Its displayed message is the
  CLI's generic status text; it did not retain the API response message.
- The Gateway TTS handler forwards non-200 TTS worker responses. The worker
  emits `resource_exhausted` only when its model-load or synthesis code catches
  an out-of-memory error. Model loading includes a free-VRAM threshold check.
  Gateway admission exhaustion returns `429 overloaded`; unavailable CUDA
  returns `cuda_unavailable`. This source evidence attributes the observed
  code to TTS worker GPU-memory exhaustion, not Gateway queue admission.
- Exact failing substage (pre-load free-memory check, model allocation, or
  synthesis allocation) is NOT ESTABLISHED. The request reached the local TTS
  worker; no external provider is used by this TTS API. Whether VoxCPM model
  inference began is NOT ESTABLISHED.
- `make logs PYTHON=.venv/bin/python SERVICE=tts` returned 38 lines. They
  contained worker startup and CUDA/model-load messages but no OOM,
  `resource_exhausted`, or inference-error record. No request ID is propagated
  to correlate these logs. A later read-only GPU sample showed 15,360 MiB total,
  174 MiB used, 14,736 MiB free and 0% utilization; because it was collected
  after the failure, it does not establish GPU state at failure time.
- The CLI exposed the status/code and Gateway response stage, but its report
  could not attribute the worker substage or correlate logs. No extra CLI
  classification was added: the public API supplies no stage or correlation
  field, and guessing it in a client would overstate evidence. Improving this
  further requires an explicit safe Gateway diagnostic contract.

API consistency correction:

- The Gateway handler has no `GET /v1/stt/models` route, and
  `TestHandlerHealthReadinessAndUnavailableRoutes` explicitly expects 404.
  The unused OpenAPI operation and `Model` response schema were removed, along
  with the CLI's misleading `models` command. The CLI still accepts model
  aliases on API operations that support selection. A deterministic test
  asserts OpenAPI has no catalog path and the CLI exposes no such command.
- OpenAPI's bearer requirement is consistent with the supported deployment:
  `Config.Validate` rejects an empty or short `SPEECH_API_TOKEN`, `cmd/gateway`
  passes the validated token to the Gateway handlers, and a live no-header
  read-only `voices` request returned HTTP 401 `unauthorized` (0.069 s). The
  handler helpers skip their token check only when constructed internally with
  an empty token; that state cannot be loaded by the supported Gateway binary.
  No authentication policy/code change was needed.

Focused verification:

- `go test ./internal/config ./internal/gateway ./internal/texttransform` —
  PASS.
- `.venv/bin/python -m unittest scripts.test_qualify scripts.test_acceptance -v`
  — PASS, 51 tests.
- Ruff check and format check for the changed Python files — PASS.
- `make verify PYTHON=.venv/bin/python` — PASS (exit 0), including Go vet,
  configuration and Compose validation, Go race tests, 92 script tests, 63
  TTS tests, Go build, governance and dependency-lock checks.
- Local Markdown link check — PASS, 60 links across seven changed documents;
  none broken.
- `.venv/bin/python scripts/validate_governance.py` — PASS.
- `git diff --check` — PASS.

No inference, cloud request, deployment or restart was performed for this
follow-up.

### M07 comprehensive CLI diagnostics — OBSERVED 2026-10-25

After the earlier M07 qualification observations above, the expanded
diagnostic CLI was exercised against the then-running Gateway. This is a
separate run; its outcomes supersede no historical results.

Offline verification:

- `.venv/bin/python -m unittest scripts.test_qualify scripts.test_roundtrip scripts.test_transform_samples -v`
  — PASS, 79 tests.
- `make verify PYTHON=.venv/bin/python` — PASS (exit 0). Go vet, Ruff
  check/format, Gateway/STT/TTS configuration checks, Compose and release
  validation, Go race tests, 92 script tests, 63 TTS tests, Go build,
  governance checks and dependency-lock checks passed.
- Local Markdown link check across seven changed documents — PASS, 60 links
  checked and none broken.
- `.venv/bin/python scripts/validate_governance.py` — PASS.
- `git diff --check` — PASS.

The coverage matrix is in `docs/operations/qualification-capabilities.md`.
At the time of this run, the CLI exposed the six then-declared OpenAPI
operations (`stt`, `tts`, `transform`, `models`, `voices`, `warmup`) and the
three operational diagnostic routes (health, readiness and metrics). The
follow-up below removes the unsupported catalog operation and command; the
current CLI covers the five operations that remain in the public contract.

Live read-only checks returned HTTP 200 for health, readiness, metrics and
voices. The model-catalog operation returned HTTP 404 `not_found`, consistent
with the Gateway implementation lacking the OpenAPI-declared STT model route.
The request was not retried. Current runtime source and image identities were
the same as recorded in the preceding runtime section. No deployment or
service restart was performed.

One sequential synthetic request per available local inference operation:

- Local STT: HTTP 200, provider `local`, 4.787 s.
- Local-Qwen Written transformation: HTTP 200, provider `host-ollama`, model
  `local-qwen`, 9.937 s.
- Local TTS: HTTP 503 `resource_exhausted`, 0.286 s. No WAV was created and
  there was no retry or warmup. The service remained healthy. A read-only scan
  of 39 TTS log lines found no resource-exhaustion, OOM, error, exception or
  inference-failure message; the underlying cause is NOT ESTABLISHED.

Expected negative-policy probes returned HTTP 403 `cloud_not_allowed` for
Groq text and HTTP 503 `provider_unavailable` for Groq STT. The active Gateway
configuration confirms cloud text is disabled and Groq STT is disabled. No
cloud provider request occurred. Groq success paths therefore remain NOT
ESTABLISHED; a private credential file's existence is not evidence of a valid
or configured Gateway credential.

The OpenAPI bearer-auth declaration and runtime behavior differ: source
enforces the configured token only when nonempty. The CLI supports explicit
auth modes and does not bypass enforcement. No public correlation-ID or log
retrieval contract was available, so server correlation IDs and relevant
server logs could not be attached to these reports. The CLI records safe
response headers when present and provides code-based guidance; logs remain
available only through existing operator tooling.

Warmup, STT timestamps, and STT streaming were not exercised live. The CLI can
probe unsupported STT options, but current Gateway behavior does not provide
timestamps or streaming. TTS has no public provider/model selector, and the
model catalog route is missing at runtime. These limitations require contract
or Gateway work to remove. No automatic root-cause claims are made for the TTS
resource failure. M07 remains in progress; this evidence is not milestone
acceptance or closeout.

### M07 debug log collection and diagnostic follow-up — OBSERVED 2026-10-25

Further source tracing narrows the TTS failure: the Gateway forwards the TTS
worker's non-200 response, and `resource_exhausted` is emitted by the TTS
worker's GPU out-of-memory handlers during model creation/loading or synthesis.
Gateway queue admission returns `429 overloaded`, while missing CUDA returns
`cuda_unavailable`. Thus the returned code identifies worker GPU-memory
exhaustion, not Gateway queue capacity. The exact failed allocation stage and
GPU state at that time remain NOT ESTABLISHED; the report had no correlated
worker log, and the later GPU sample cannot establish the earlier state.

Opt-in `--debug` now collects local logs through the fixed-project
`scripts.compose` helper. It is not used by ordinary requests, and remote
targets skip Docker. For each of Gateway, STT and TTS it requests at most 100
lines within a 30-second to five-minute look-back, then caps saved output at
32 KiB per service. Credential patterns and structured request/payload/message
fields are redacted. Evidence is saved with mode 0600 under `private/` and the
CLI prints only its path. Returned server IDs are matched against logs when
present; without them, collection is labeled as time-window-only. The current
Gateway does not propagate a client request ID or emit a documented server ID,
so its logs cannot be correlated to the earlier TTS request.

Reproducible failure test: `scripts.test_qualify` injects HTTP 503
`resource_exhausted` and mocked per-service log lines containing a returned
server ID plus synthetic text. The resulting private evidence preserves the
HTTP status/error code, selects the matching lines, removes the text, and has
mode 0600. Representative stderr/console output is:

```text
debug evidence saved: private/qualification-debug-<id>.json
guidance: The selected worker reported resource exhaustion; check available GPU/worker capacity and service logs. Do not retry automatically.
diagnostics: request_id=<local-id> stage=gateway_response server_request_id=server-id-42
FAIL tts: HTTP 503; elapsed=0.0s; error=http_error; api_code=resource_exhausted; Gateway returned HTTP 503
```

This is a deterministic mocked failure, not a second live TTS request.

The earlier model-catalog discrepancy is corrected by removing the undeployed
route/schema from OpenAPI and removing the CLI catalog command; contract tests
assert both. The authentication declaration remains mandatory: config
validation rejects an empty/short token and the live no-header `voices` probe
returned 401. The apparent difference exists only in direct internal handler
construction with invalid empty-token configuration, not the supported
Gateway startup path, so authentication behavior was left unchanged.

### Debug log collection empty-window investigation — OBSERVED 2026-10-25

Saved debug evidence showed successful retrieval with zero lines for all three
services in one short, rejected cloud-policy request. Its returned API error was
`cloud_not_allowed`; the saved 503 TTS report does not contain a debug-log
collection or request timestamps, so a historical 503-to-log match is NOT
ESTABLISHED.

The collector and supported manual `make logs` command share
`scripts.compose.run`, which fixes the Compose project, Docker context, env file,
and Compose files. The relevant invocation difference is that debug collection
adds Docker Compose's `--since <bounded-window>`; manual `make logs` only uses
`--tail 100`, so it can display older entries outside the diagnostic window. A
read-only comparison reproduced this: the current 300-second bounded query
returned 0 Gateway and STT lines while unfiltered tails returned 14 and 19 lines;
the bounded TTS query returned 34 current progress lines while its unfiltered
tail returned 71. The collector does no timestamp parsing or additional content
filtering when no server ID is available. This confirms why older manual-tail
entries can coexist with a successful empty bounded collection; it does not
establish that those older entries relate to the failed request.

Service outcomes now distinguish `matched`, `no_matching_lines`, and `failed`;
aggregate status distinguishes matching output, an all-empty successful window,
partial failure, total failure, and non-loopback `unavailable`. The bounded
window, output caps, redaction and private evidence permissions remain
unchanged. A deterministic mocked test reproduces
an empty `--since` result alongside a nonempty unfiltered tail, and verifies
that this is labeled as a successful no-match rather than a retrieval failure.
No inference or service changes were made.

Follow-up verification for the collection-status correction:

- `.venv/bin/python -m unittest scripts.test_diagnostics -v` — PASS, 9 tests.
- Focused CLI suite — PASS, 104 tests.
- `make verify PYTHON=.venv/bin/python` — PASS (exit 0), including 92
  repository script tests and 63 TTS tests.
- `git diff --check` — PASS.

Focused verification:

- `.venv/bin/python -m unittest scripts.test_diagnostics scripts.test_qualify scripts.test_compose_deploy scripts.test_roundtrip scripts.test_transform_samples -v`
  — PASS, 102 tests.
- `go test ./internal/config ./internal/gateway` — PASS.
- Ruff check and format — PASS.
- `make verify PYTHON=.venv/bin/python` — PASS (exit 0): Go vet, Ruff,
  Gateway/STT/TTS configuration, Compose/release validation, Go race tests,
  92 script tests, 63 TTS tests, Go build, governance and lock checks passed.
- Local Markdown link check — PASS, 60 links across seven changed documents;
  none broken.
- `.venv/bin/python scripts/validate_governance.py` — PASS.
- `git diff --check` — PASS.

No live inference, cloud request, deployment or restart was performed.
M07 remains in progress.

### End-to-end request correlation — OBSERVED 2026-10-25

The production Gateway handler now assigns a fresh UUIDv4 per HTTP request,
replaces any caller-supplied `X-Request-ID`, returns the generated value in
that response header, and places the same value in the request context. Gateway
start/completion/failure logs include the ID and safe status metadata; failure
logs extract only a bounded allowlisted API error code, never the response
message or body. Text-provider attempt, completion and failure logs include
the same ID.

For internal STT/TTS worker calls, the Gateway forwards the ID. Workers accept
only canonical UUIDv4 values, echo valid IDs on their internal responses, and
write content-free request lifecycle logs. STT also carries the ID through
supervisor IPC into child inference-failure logs. The qualification CLI
already captures the server-confirmed `X-Request-ID`; local debug collection
uses that exact ID to select matching logs and retains bounded time-window
collection when the header or exact log match is unavailable. Exact ID matches
and time-window-only evidence remain distinct.

The public OpenAPI responses document `X-Request-ID`. No caller-provided ID is
trusted, and no payload, transcript, prompt, or credential is added to logs.
The external Groq request does not receive this internal correlation header.
Worker correlation depends on the request traversing the Gateway and on the
worker receiving a valid forwarded UUIDv4. A Gateway UUID-generation failure
returns a safe 500 without an ID. These paths do not establish correlation
with external-provider logs or shared Ollama logs.

Focused verification:

- `go test ./internal/gateway ./internal/texttransform ./cmd/gateway ./internal/transport` — PASS.
- Focused Python HTTP, runtime, TTS, contract, qualification and diagnostics tests — PASS.
- `make verify PYTHON=.venv/bin/python` — PASS (exit 0), including Go race
  tests, Ruff, configuration/Compose/release checks, repository Python tests,
  STT/TTS tests, build and governance checks.
- `git diff --check` — PASS.

No live inference, cloud request, deployment or restart was performed.

### Current integration verification — OBSERVED 2026-10-26

The following full offline verification was executed from the repository root
on 2026-10-26 against the uncommitted M07 integration work:

- `make verify PYTHON=.venv/bin/python` — PASS, exit 0. Go vet, Ruff check and
  formatting, Gateway/STT/TTS configuration, Compose and release validation,
  Go race tests, repository script tests (95), TTS tests (64), Go build, Python
  AST parsing, governance, and STT/TTS lock validation all passed.
- `git diff --check` — PASS.
- `make status PYTHON=.venv/bin/python` — OBSERVED: Gateway, STT and TTS were
  healthy at source `0628bf763069440189c59944d36a8db8cc3b8bfc` before deployment.

These checks do not establish target deployment or live request acceptance.
Preflight, installation, post-deployment checks, and the four final manual
acceptance requests remain pending. M07 remains in progress; no milestone
closeout is recorded here.
