# M05B Stage 2B — Gateway integration qualification

Status: **Offline integration acceptance and bounded live model compatibility
qualification PASS; operator-accepted 2026-10-22.** The three retained
models each completed their separately authorized synthetic live request(s)
through the isolated Gateway. The compiled-Gateway acceptance controller now
also verifies selection, fallback, rate-limit scope, auth, cloud restrictions,
passthrough, failure handling, readiness and shutdown against deterministic
loopback fake providers. No production deployment, concurrent speech/model
inference or M05B closeout is included. Stage 2A was accepted with its documented
limitations: seven lexical failures per context remain failed, and local Qwen is
retained only for user-reviewed transformations.

## Baseline and scope

**OBSERVED:** repository `/home/master/speech-platform`, branch `main`, HEAD
`0066c9a39fb09725137781cde114f912402033b4`. The worktree was already dirty
before this task with the resumed Stage 2A records/scripts and proposed M06
planning files. Those existing changes were preserved. The Stage 2A result and
its raw private evidence were not edited.

**OBSERVED:** the running product containers at inspection were:

| Service | Image / role | State |
| --- | --- | --- |
| Gateway | `speech-platform-gateway:m03b-high-quality-20261022` | healthy, restart count 0, published only at `127.0.0.1:8080` |
| STT | CUDA worker image revision `3aa5f68c…` | healthy, restart count 0 |
| TTS | `speech-platform-tts:m03b-high-quality-20261022` | healthy, restart count 0 |

Gateway `/healthz` and `/readyz` returned `alive` and `ready`; STT and TTS
`/healthz` returned `alive`. The live Gateway image is an earlier M03B image,
so it cannot establish M05B Stage 1 behavior. The production text route was not
probed. The Gateway was not replaced, restarted or modified. Product
Compose networks are `publish`, `stt_private` and `tts_private`; worker networks
are isolated. The publish bridge has masquerading disabled. The root Compose
file was not edited.

Stage 2A has completed its sequential nine-case 4K/8K comparison. The operator
accepted retaining local Qwen only for user-reviewed transformations; seven
lexical invariant failures per context remain failed, as recorded in
[Stage 2A qualification](stage-2a-qualification.md). Stage 2B below qualifies
only the optional text service through the Stage 1 Gateway source, not speech
pipeline behavior, deployment or production readiness.

## Isolated Gateway profile

Prepared an ignored, mode-0700 directory at `private/m05b/stage2b/` with
mode-0600 files. The private profile reuses the Gateway YAML schema but binds
only `127.0.0.1:18080`, configures separate unused STT/TTS loopback ports, points
host Ollama traffic at `127.0.0.1:11434`, and uses the configured Groq HTTPS
endpoint. It permits cloud only in this private test profile. It does not modify
Compose, production YAML, environment files or running containers. A random
test bearer token is kept in the private `gateway-test.env`; it is unrelated to
the production token. The tracked sample remains unchanged.

The profile sets Ollama `keep_alive: 5s`, the maximum accepted by the current
strict validator. A first private-profile check using `60s` failed with
`text_transform: ollama.keep_alive must be from 0s to 5s`; after setting 5s,
`private/m05b/stage2b/gateway --config
private/m05b/stage2b/gateway.yaml --check-config` passed. The isolated binary
was built from the committed M05B Gateway source with `go build`; its SHA-256 is
`d9d97d1a32bc48d59651edebca32ef6ec5a079a7fbfb2755007ce93f6ec4bbf6`. This is
an implementation/configuration constraint,
not a live provider test. Five seconds is finite and avoids explicit unload,
but may produce a cold start on every later request. No validator or model
configuration code was changed.

The existing `private/groq_api` credential file was confirmed present with
mode 0600. Its value was loaded without display into the isolated Gateway
process environment for the no-inference API smoke; it was not copied to
another file or included in process arguments. Credential validity is not
established. No provider call was made while the process held the key. The
private API bearer file and three synthetic request bodies are also mode 0600
and Git-ignored. Outputs should be saved under the same private directory.

This is a host-local isolated process profile, not a second Compose project.
It does not join production Docker networks or make worker requests. Text
transformation does not require STT/TTS readiness; the isolated Gateway's
`/readyz` is therefore not a live-speech readiness claim. During preparation,
the binary was started briefly on port 18080 for `/healthz`, authentication
rejection and a raw-only passthrough check, then stopped. The raw response
metadata was valid, and metrics showed zero provider attempts and one
passthrough. No model inference occurred in that preparation smoke.

## Provider connectivity findings

- **OBSERVED:** shared Ollama `GET http://127.0.0.1:11434/api/ps` returned
  `{"models":[]}`. This is a read-only API check, not proof that the Gateway
  process can generate or that a model is resident/available.
- **OBSERVED:** a default-trust-store TLS handshake to `api.groq.com:443`
  completed with TLS 1.3 and certificate verification enabled. No Groq HTTP
  request, authentication attempt or inference request was sent.
- **OBSERVED:** `private/groq_api` exists with mode 0600 and was loaded only
  into the isolated process environment for the raw-only smoke. The value was
  not displayed or copied. Credential validity is not established.
- **NOT ESTABLISHED:** live Gateway-to-Ollama generation, Groq authenticated
  access, actual provider request acceptance, reasoning-option compatibility,
  response parsing by the Go process, cloud quota/cost, or model output quality.

No TLS verification disablement, credential output, provider inference, forced
model eviction, or changes to shared Ollama were performed.

## Offline test evidence

**OBSERVED — PASS:** the following commands completed with exit status 0:

```text
go test ./internal/config ./internal/texttransform ./internal/gateway
go test ./...
go build -o private/m05b/stage2b/gateway ./cmd/gateway
private/m05b/stage2b/gateway --config private/m05b/stage2b/gateway.yaml --check-config
docker compose config -q
make verify PYTHON=.venv/bin/python
```

The focused Go packages and full Go module checks passed (some package results
were Go test-cache hits). Existing coverage uses fake generators and local
`httptest` providers to exercise raw passthrough/no provider call, explicit and
automatic selection, `ordered`/`local_first`/`cloud_first`, `local_only`, global
cloud prohibition, fallback order, provider suppression, missing credentials,
bearer auth, invalid requests, context preflight, cancellation, service
shutdown, total deadlines, Ollama serialization, OpenAI-compatible payload
fields including `reasoning_effort`, incomplete responses, refusal and error
classification. These are offline fake-provider tests, not live compatibility
evidence. No GPU work was performed by the checks.

The added cases are `TestTransformationModesFormatsAndLanguagesReachFakeProvider`,
`TestExplicitSelectionUsesEachConfiguredModelWithoutFallback`,
`TestAcceptedGroqModelsSerializeConfiguredReasoningOptions`, and
`TestTextTransformationRunsThroughPublicGatewayRouteWithFakeProvider`, and
`TestProviderTimeoutCanFallbackWithinTotalRequestDeadline`.
`make verify` also passed Go vet, Ruff lint/format, configuration validation,
static Compose/release checks, `go test -race ./...`, Python scripts/STT suites,
build, governance, and STT/TTS lock checks. It did not start or mutate services.

The first focused provider-timeout run hit its 5-second test timeout because
the fake HTTP handler waited indefinitely and `httptest.Server.Close()` waited
for it. The fixture was changed to use a bounded wait. The exact focused
rerun, `go test ./internal/texttransform -run
TestProviderTimeoutCanFallbackWithinTotalRequestDeadline -v -count=1
-timeout=5s`, passed in 0.223s; focused race tests and the full verification
target passed afterward. This was a fake-test fixture defect, not a production
Gateway defect.

**OBSERVED:** `docker compose ps`/`docker inspect` and Gateway/worker health
requests at baseline showed all three product services healthy with zero
restarts. Product health was rechecked after the no-inference isolated-process
smoke below; these observations are not provider qualification.

**OBSERVED — isolated process API smoke:** the private binary started and
`GET /healthz` returned `alive`. A transformation POST without the test bearer
returned 401. An authenticated raw passthrough POST returned 200; the response
had `generated=false`, null model/provider, and the private metrics snapshot
showed `text_transform_attempts_total 0` and
`text_transform_passthrough_total 1`. This confirms the actual isolated Go
process and public route can bind/use port 18080 and reject unauthorized
requests without dispatching inference. The process was stopped cleanly. No
request was sent to Ollama or Groq.

## Offline functional matrix and evidence expectations

| Case | Request / expected outcome | Provider contacted | External cloud? | Bound | Evidence |
| --- | --- | --- | --- | --- | --- |
| Raw passthrough | Raw request returns exact input/options; null model/provider; generated=false | None | No | Gateway request deadline; no provider wait | API response and unchanged fake call count |
| Writing/mode and formatting | `written`, `polite`, `diplomatic` with `normal`, `concise`, `structured`; generated success | Fake selected model | No | 240s total configured cap; offline tests are local | Sanitized status/metadata; fake call count |
| Language options | `none`, `en`, `sv`, `ru` over synthetic text; options retained | Fake selected model | No | Same 240s cap | Sanitized options/model/provider; no output in tracked evidence |
| Explicit models | One each `local-qwen`, `groq-qwen`, `groq-gpt-oss`; never switches aliases | Corresponding fake endpoint | No | Per-provider configured deadline, total 240s | Fake payload summary and returned logical IDs |
| Automatic order | `ordered` and `local_first` choose first local; `cloud_first` chooses configured cloud first | Fake endpoints only | No | 240s | Ordered fake request sequence and metadata |
| Cloud restrictions | Global `allow_cloud:false` and request `local_only:true` prohibit fake cloud calls | Local fake or none | No | 240s | Cloud call counter remains zero |
| Eligible fallback | Simulated local transport failure then configured next fake model; fallback metadata true | Fake local then fake next | No | 240s | Ordered fake call list; no production fault injection |
| Missing cloud credential | Cloud alias unavailable; no cloud request; local-only routes still behave as configured | Local fake or none | No | 240s | Missing-credential outcome and fake call counters |
| Authentication | Missing/invalid test token returns 401 before any fake provider call | None | No | 5s client bound | Status and zero provider calls |
| Context limit | Oversized input rejected before provider call | None | No | 5s client bound | 413 and zero provider calls |
| Incomplete provider response | Malformed/partial fake Ollama or Chat response returns sanitized error; fallback follows existing table only | Fake endpoint | No | Provider timeout <=30s; total 240s | Status/category and call sequence, no raw body in tracked report |
| Provider timeout | Slow fake blocks until provider/total deadline; no unsafe fallback after cancellation | Fake endpoint | No | Provider timeout <=30s; total 240s | Elapsed time/status and fake call sequence |
| Cancellation/shutdown | Caller cancel and service shutdown stop fake request within bounds | Fake endpoint | No | Provider/total timeout plus 10s shutdown | Request completion and no later fallback |

The existing test suite covers these behaviors in package tests. It does not
exercise the production process binary against live providers. For any new
implementation defect found later, preserve the failing case and exact
command; no defect beyond the `keep_alive` bound was established in this
preparation.

## Bounded live matrix — authorized 2026-10-22; attempt recorded below

Maximum **three inference requests total**, sequentially: one explicit
`local-qwen` request, then one explicit `groq-qwen`, then one explicit
`groq-gpt-oss`. Each request has a 240-second Gateway deadline and 245-second
client maximum. No retries, automatic fallback, policy sweep, model-quality
corpus, STT/TTS calls, repeated samples or concurrency. Stop after these calls
for operator review. The provided private request files contain only short
synthetic text; the two Groq requests send those synthetic sentences and their
transformation options to Groq. The local request sets `local_only: true`.

| ID | Request | Expected provider/model metadata | Cloud data exposure | Bound | Required evidence |
| --- | --- | --- | --- | --- | --- |
| L1 | Private `explicit-local.json` | `host-ollama` / `local-qwen`, generated=true, fallback=false | None | 245s | Response privately saved; safe metadata and duration; before/after `/api/ps`, GPU and service health |
| L2 | Private `explicit-groq-qwen.json` | `groq` / `groq-qwen`, generated=true, fallback=false; configured Qwen reasoning fields accepted | One synthetic sentence/options sent to Groq | 245s | Response privately saved; safe metadata, duration/status; no reasoning content in tracked logs |
| L3 | Private `explicit-gpt-oss.json` | `groq` / `groq-gpt-oss`, generated=true, fallback=false; configured GPT-OSS reasoning fields accepted | One synthetic sentence/options sent to Groq | 245s | Response privately saved; safe metadata, duration/status; no reasoning content in tracked logs |

Expected LLM-facing values are pinned in the private profile: Ollama model
`qwen3.5:9b-q4_K_M`, `num_ctx=8192`, `keep_alive=5s`, `think=false`; Groq
models `qwen/qwen3.8-27b` with `reasoning_effort=none` and
`openai/gpt-oss-120b` with `reasoning_effort=low`, both `include_reasoning=false`.
Do not infer reasoning compatibility until the authorized live response is
accepted by the Gateway adapter. Store responses privately for review and keep
only status, model/provider IDs, timings and aggregate findings in tracked
records.

### Live abort conditions

- Gateway `/healthz` failure; production Gateway, STT or TTS health loss or
  restart-count change; any unrelated container/service change.
- GPU memory below 1,024 MiB free; a recognized GPU-driver/CUDA/OOM error; or
  three consecutive one-second memory-telemetry failures. Do not run TTS
  inference or overlap requests.
- Provider/client deadline violation or provider/request failure; an isolated
  Gateway process exit; or a production worker restart/health loss.
- Any request exceeds its 245-second client bound, returns malformed/incomplete
  response, or produces an unexpected provider/model/fallback identity. Stop;
  no retry or automatic fallback in this live matrix.
- Unexpected Ollama generation, residency/expiry behavior, or ambiguous
  concurrent GPU use. No `ollama stop`, unload request, configuration change
  or attempt to evict another client.
- Any need to disable TLS validation, expose a credential, use non-synthetic
  text, change Compose/networking, or restart production services.

After local L1, observe the configured natural expiry passively through `/api/ps`
and GPU samples; never force unload. Check Gateway/STT/TTS health and restart
counts before and after the complete matrix. If health is degraded, stop and
preserve the observations; do not restart shared services as recovery.

## Prepared commands for the bounded live window

These commands document the reviewed procedure. The Gateway start and local
request were attempted; the launch did not persist across command sessions and
the local request failed before HTTP. Neither Groq request was run. Keep shell
tracing disabled (`set +x`):

```sh
set +x
set -a
. private/m05b/stage2b/gateway-test.env
set +a
export GROQ_API_KEY="$(tr -d '\r\n' < private/groq_api)"
private/m05b/stage2b/gateway --config private/m05b/stage2b/gateway.yaml
```

In a second terminal, issue the three sequential calls, saving full responses
only to private evidence and printing only HTTP status and duration:

```sh
mkdir -p private/m05b/stage2b/responses
chmod 700 private/m05b/stage2b/responses
curl --silent --show-error --max-time 245 --config private/m05b/stage2b/curl-auth.conf \
  --header 'Content-Type: application/json' --data-binary @private/m05b/stage2b/explicit-local.json \
  --output private/m05b/stage2b/responses/local.json --write-out 'local status=%{http_code} duration=%{time_total}\n' \
  http://127.0.0.1:18080/v1/text/transformations
curl --silent --show-error --max-time 245 --config private/m05b/stage2b/curl-auth.conf \
  --header 'Content-Type: application/json' --data-binary @private/m05b/stage2b/explicit-groq-qwen.json \
  --output private/m05b/stage2b/responses/groq-qwen.json --write-out 'groq-qwen status=%{http_code} duration=%{time_total}\n' \
  http://127.0.0.1:18080/v1/text/transformations
curl --silent --show-error --max-time 245 --config private/m05b/stage2b/curl-auth.conf \
  --header 'Content-Type: application/json' --data-binary @private/m05b/stage2b/explicit-gpt-oss.json \
  --output private/m05b/stage2b/responses/gpt-oss.json --write-out 'gpt-oss status=%{http_code} duration=%{time_total}\n' \
  http://127.0.0.1:18080/v1/text/transformations
```

The test bearer value is read from a mode-0600 curl config rather than placed
in command arguments. The Groq credential is read from its private file into
the isolated Gateway's environment. Certificate verification remains enabled.

## Authorized live smoke attempt — 2026-10-22

**OBSERVED — preflight:** before the attempt, the production Gateway, STT and
TTS containers were healthy with restart counts 0 and the same container IDs
and start times recorded in the evidence. Gateway `/healthz` and `/readyz`
returned `alive` and `ready`. GPU baseline was Quadro RTX 5000, 15,360 MiB
total, 2,216 MiB used, 12,694 MiB free, 0% utilization and 35 C. Ollama
`GET /api/ps` returned an empty model list. These findings met the documented
preflight checks.

**OBSERVED — local request stopped:** the exact synthetic request remains in
`private/m05b/stage2b/explicit-local.json` (SHA-256
`5fab9ca140f09b8529c1dbdde3cb43da11243d05f23ebef2d93b285d7e9e1a29`). The
isolated Gateway briefly answered `/healthz` with `alive`; its private log
contains only the startup message. The subsequent single authenticated curl
attempt returned HTTP 000, curl exit 7, and “Failed to connect” to
`127.0.0.1:18080`. No response body was received; the corresponding private
response file is empty. No retry was made. The Gateway process was no longer
running when inspected. Its log contains no transformation/provider request.

**INTERPRETATION:** the isolated process did not remain available across the
separate command sessions used to launch it and issue the request. The client
connection was refused before an HTTP request could be handled. This is a test
process-lifetime/setup failure, not a model-quality result or a provider
compatibility result. The exact launch/session behavior needs correction
before a future authorized live attempt.

**OBSERVED — stopped run and postflight:** no Ollama model became resident;
`/api/ps` remained empty and the final GPU sample was 2,216 MiB used,
12,694 MiB free and 0% utilization. Since inference never started, there was
no loaded model whose natural expiry or memory recovery could be measured.
Production Gateway/STT/TTS remained healthy; their IDs, start times and zero
restart counts were unchanged, and Gateway health/readiness remained
`alive`/`ready`. No production container was restarted or changed.

**OBSERVED — request accounting:** the local request was the only client
request attempted and it failed before reaching the Gateway. Neither Groq
request was sent. Therefore no cloud data was disclosed and no live provider
request was made. Groq authentication, both reasoning-option payloads and
response compatibility remain unverified. No provider/model metadata,
completion, latency, output quality, GPU residency under inference, or natural
recovery result is available from this attempt.

Private diagnostics are under `private/m05b/stage2b/responses/` and
`private/m05b/stage2b/gateway-live.log`, all with mode 0600. Stage 2B live
qualification remains incomplete; do not proceed to Stage 2C or deployment.
Operator review and separate authorization are required before a corrected
live attempt.

## Offline Gateway lifecycle repair — 2026-10-22

**OBSERVED — prior failure evidence:** the prior launch used a shell
background job (`(...) >private/m05b/stage2b/gateway-live.log 2>&1 &`) and
returned from that `exec_command`; the curl ran in a later command session.
The private Gateway log contains its startup line only, the next session's
curl got connection refused, and the process was absent afterward. That
attempt did not record an exit status or terminating signal. No config error,
runtime error, or signal can therefore be established from the old evidence.

**INTERPRETATION:** the test assumed the background child would survive its
short-lived command/session. Losing the shell/process owner at the boundary
between launch and curl best explains the observations. The precise mechanism
(including whether the execution environment sent a signal) is NOT
ESTABLISHED. The configuration had already served `/healthz`; no startup
diagnostic indicating a config failure was captured.

**OBSERVED — correction:** added
`scripts/test_m05b_stage2b_lifecycle.py`, a single offline controller. It
builds a fresh Gateway binary, binds fake worker readiness and an Ollama-shaped
fake provider to loopback, selects a free ephemeral Gateway port on
`127.0.0.1`, points a temporary private config only at those endpoints, and
starts the Gateway as an owned `subprocess.Popen` child in its own session.
The controller waits for liveness/readiness, performs two
authenticated raw passthrough requests and one explicit local-model
transformation sequentially, checks the process after each call, and
terminates/waits/reaps the process in `finally`. It records PID and exit status
privately. The cloud provider is disabled in the temporary profile, no Groq
credential is passed, and no live Ollama/Groq endpoint is called.

**OBSERVED — PASS:**
`.venv/bin/python scripts/test_m05b_stage2b_lifecycle.py` built and ran the
Gateway. `/healthz` was alive and `/readyz` ready. All three authenticated
requests returned HTTP 200; the fake Ollama endpoint received exactly one
request. The Gateway remained alive between every request. Cleanup sent
SIGTERM, the process exited with status 0 and was reaped; a subsequent process
table check found no orphan Gateway. Private evidence is in
`private/m05b/stage2b/offline-lifecycle.json` (mode 0600) and
`private/m05b/stage2b/offline-gateway.log` (mode 0600).

**OBSERVED — production isolation:** before and after the test, production
Gateway, STT and TTS retained identical container IDs and start times, healthy
status and restart count zero. Production Gateway `/healthz` and `/readyz`
continued to return `alive` and `ready`. No production service, STT/TTS worker,
shared Ollama configuration or deployment was changed.

This verifies the corrected offline controller path. Live-provider qualification
remains incomplete; operator review and separate authorization are required
before another inference attempt.

## Authorized live qualification resume — 2026-10-22 19:55 UTC

**OBSERVED — preflight:** the single-owner private controller checked
production Gateway health/readiness, STT/TTS container health and identities,
GPU free memory, empty Ollama residency, the prepared model/request mappings,
five-second keep-alive, and mode-0600 Groq credential presence without
displaying its value. It built the isolated binary, passed `--check-config`,
bound a dedicated ephemeral port on `127.0.0.1`, and observed `/healthz` as
`alive`. The controller did not durably flush its preflight snapshot before
the request; numerical GPU baseline and exact preflight identities for this
run are therefore NOT ESTABLISHED from this run's private report.

**OBSERVED — local request:** exactly one authenticated request was attempted
using the unchanged synthetic `explicit-local.json` payload, explicitly
selecting `local-qwen` with `local_only: true`. The request body was preserved
at `private/m05b/stage2b/live-20261022T195506Z/local.request.json`. The
controller's passive monitor thread crashed immediately after the request
started with `AttributeError` while attempting to call `chmod` on an open file
object. No GPU/residency samples were written. The operator-safe stop sent
SIGINT to the controller; the Gateway client received HTTP 503
`text_transform_unavailable`. Its exact body and headers are preserved in
`local.response.body` and `local.response.headers.json`. Client latency was
not recorded, and no model/provider success metadata or output was returned.

**OBSERVED — provider diagnostic:** Ollama logs show exactly one
`POST /api/generate`, HTTP 500, duration 14.338775556 seconds. Thus the
request reached the local provider boundary. The available sanitized log does
not establish why Ollama returned 500 or whether Gateway shutdown/cancellation
contributed. No completed transformation or model-quality result was
produced. One attempt was made; no retry or fallback occurred.

**OBSERVED — stop accounting:** neither Groq request was sent. Groq
authentication, live protocol compatibility and acceptance of the configured
reasoning fields remain NOT ESTABLISHED. The only client response was the
Gateway error JSON (`text_transform_unavailable`); it contained no reasoning
text or provider-internal fields. No cloud data was sent.

**OBSERVED — postflight:** at 2026-10-22 19:58:23 UTC, Ollama `/api/ps` was
empty and GPU was Quadro RTX 5000, 15,360 MiB total, 2,216 MiB used,
12,694 MiB free, 0% utilization and 35 C. This is an instantaneous recovery
state only; because the sampler failed, model residency, natural expiry and
memory recovery over time are NOT ESTABLISHED. No unload request was issued.
Production Gateway/STT/TTS were healthy with zero restarts and retained
container IDs `03df6c80…`, `02110b11…`, and `cbda986a…`; Gateway health and
readiness were `alive` and `ready`. This run's preflight snapshot was not
durably recorded, so an exact same-run identity comparison is NOT ESTABLISHED.

The isolated Gateway child (PID 2650530) was terminated by controller cleanup,
waited/reaped, and no orphan was present afterward. Its exit status was not
persisted. The controller itself exited 1 because a second defect left
`return_code` unset on keyboard interrupt, causing `UnboundLocalError` while
writing its final report. The partial report was repaired from preserved
request/response files and read-only postflight evidence in
`private/m05b/stage2b/live-20261022T195506Z/` (all private files mode 0600).

**OBSERVED — offline controller repair:** corrected monitor file permission
handling to chmod the path, made monitor-thread exceptions set the abort flag,
initialized the controller exit status, handled keyboard interruption, and
persisted an in-progress request record before sending. A fake-only monitor
smoke wrote mode-0600 samples and passed. Ruff and Python compilation passed.
The live controller was not run again. The live sequence remains stopped after
the failed local request; operator review is required before another
inference attempt.
These are the original preparation commands, not a retry instruction. The
later authorized resume used the private single-owner controller and stopped
after the local request failure; do not resume or repeat any provider request
without operator review. Production Compose remains untouched.

## Risks and disposition

## Ollama HTTP 500 and controller diagnostics — 2026-10-22

**OBSERVED — preserved evidence:** `private/m05b/stage2b/live-20261022T195506Z/`
contains the exact synthetic request and Gateway response. Its report records
one Ollama generation POST, HTTP 500 in `14.338775556s`, and Gateway HTTP 503
`text_transform_unavailable` at 19:55:24 UTC. The Ollama log records runner
startup at 19:55:11, model load completion at 19:55:19, a 270-token prompt,
generation reaching 125 tokens by 19:55:23, then `cancel task` at 19:55:24.
The access log and runner cancellation are within the same second. The raw
Ollama error body was not preserved, so the precise reason for its 500 remains
**NOT ESTABLISHED**.

**OBSERVED — model/resource diagnostics:** Ollama logged a successful CUDA
fit, 12,523 MiB free at fitting, projected 5,142 MiB allocation, successful
model/context initialization and a loaded runner. The retained log contains no
CUDA allocation failure, OOM, runner crash, or model-load error. Read-only
kernel-log filtering and Docker event inspection found no OOM/Xid match or
Ollama restart in 19:54:30–19:58:30 UTC. The failed run has no GPU samples
because its monitor failed. GPU exhaustion is not established; missing log
matches cannot rule out every host or driver event. Postflight at 19:58:23
showed Ollama running with restart count zero, `/api/ps` empty, and GPU at
2,216 MiB used / 12,694 MiB free. Current `/api/tags` reports the same model
tag and digest as Stage 2A, but no exact digest snapshot was saved at request
time.

| Dimension | Successful Stage 2A requests | Failed Stage 2B Gateway request | Evidence / implication |
| --- | --- | --- | --- |
| Model | `qwen3.5:9b-q4_K_M`; digest `56671c2a…` | Same tag in Ollama runner selection; historical digest not captured | Current tags API reports the Stage 2A digest; historical identity match is not proven |
| Context | 4,096 and 8,192 | 8,192 | Runner log reports `n_ctx=8192`; not an out-of-range context |
| Output budget | `num_predict=512` | `num_predict=1024` | Different budgets; only 125 tokens were generated before cancellation |
| Thinking | `think=false` | `think=false` | Runner logged `thinking = 0`; no contradiction observed |
| Keep-alive | `60s` | `5s` | Both finite; residency setting does not explain in-progress cancellation |
| Sampling | temperature 0, top_p 1, seed 20261022, batch 128, threads 8 | Same | Private Gateway config and adapter construction; Ollama logged top_p 1 and temperature 0 |
| Prompt framing | Stage 2A prompt v2 and JSON input | Gateway system instruction, validated-options and JSON-string prompt | Different framing; Ollama counted 270 prompt tokens in Stage 2B |
| Deadlines | 300s direct request | 180s provider, 240s Gateway, 245s client | Failure at about 14.34s; configured deadline expiry is not supported by timing |

**INTERPRETATION — cancellation and status:** the controller report says it
sent SIGINT after the monitor thread failed. The saved Gateway 503 is the
service's `text_transform_unavailable` response for stopped service/root
context. Ollama's task cancellation follows its HTTP 500 access record in the
same second. This makes controller/service cancellation the strongest
explanation for the 500, likely because it interrupted the in-flight provider
request. Without Ollama's response body or a common monotonic timeline, it is
not proven whether Ollama first emitted an independent failure or translated
cancellation into 500. The public 503 is consistent with Gateway lifecycle
cancellation, rather than a direct mapping of the Ollama status.

**OBSERVED — adapter and error policy:** `internal/texttransform/provider.go`
constructs Ollama JSON with model, separate system/prompt fields,
`stream:false`, finite `keep_alive`, and options for `num_ctx`, `num_predict`,
batch/thread, `think`, sampling and seed. The private config yields the values
above with no conflicting duplicate context/output setting. HTTP 5xx maps to
`FailureTransport` without suppression, so automatic selection can continue
according to current fallback order. Explicit selection narrows candidates to
one model, so uninterrupted HTTP 500 handling returns the existing
`503 text_transform_failed` without another provider attempt. Cancellation is
handled separately and does not fall back. No error policy was changed.

**OBSERVED — offline regressions:** the private controller now has explicit
interrupt recording, child termination/wait/reap, durable request/response
records, monitor abort propagation, and a stderr/nonzero failure when final
report persistence fails. New tests cover a monitor fault during an active
fake request, KeyboardInterrupt reporting, durable private evidence and child
reaping. Go coverage sends a fake Ollama HTTP 500 through the explicit-model
Gateway path and checks the existing status/category without retry. Existing
`TestShutdownCancelsActiveTextRequest` verifies Gateway cancellation and
absence of fallback.

**NOT ESTABLISHED:** the Ollama 500's exact cause; instantaneous GPU peak or
whether GPU pressure contributed; exact historical model digest; client
latency; valid output; natural expiry or GPU recovery for this attempt.

**Recommendation:** after offline checks and operator review, a separately
authorized bounded retry may send only the single local request first. The
controller should durably record every preflight value and let any monitoring
fault abort the request. Preserve Ollama's raw error response privately and
capture GPU/residency samples. The two unattempted Groq requests require
separate renewed authorization. This diagnostic work does not authorize
inference.

## Authorized single-local Gateway repeat — 2026-10-22 20:12 UTC

**OBSERVED — offline gate and isolation:** before this run,
`.venv/bin/python scripts/test_m05b_stage2b_controller.py` passed five
controller regressions and `.venv/bin/python scripts/test_m05b_stage2b_lifecycle.py`
passed the sequential isolated Gateway lifecycle test. Ruff lint/format and
Python compilation passed for the private controller and its regression test.
The controller was scoped to one local request, set `allow_cloud:false` in the
isolated copy of the config, omitted `GROQ_API_KEY` from the child environment,
and used controller-owned loopback `/readyz` stubs solely to satisfy the
isolated Gateway's composite readiness check. These stubs did no speech
inference. The request explicitly selected `local-qwen` and `local_only:true`;
no Groq request was possible in this run.

**OBSERVED — preflight and process:** at 20:12:32 UTC the production Gateway,
STT and TTS were healthy with restart count zero and container IDs matching
the prior baseline. Production Gateway `/healthz` and `/readyz` returned
`alive` and `ready`. GPU baseline was Quadro RTX 5000, 15,360 MiB total,
2,216 MiB used, 12,694 MiB free, 0% utilization and 35 C; Ollama `/api/ps`
was empty. The isolated Gateway bound `127.0.0.1:56167`, passed `/healthz`
and `/readyz`, and remained alive through the request. Preflight values and
subsequent samples are preserved in
`private/m05b/stage2b/live-20261022T201232Z/report.json` and
`samples.jsonl` (mode 0600, run directory mode 0700).

**OBSERVED — one request, rejected response:** one request started at
20:12:35.941969 UTC and completed at the Gateway with HTTP 502 after
32.898676 seconds. The complete 87-byte public Gateway error response is
preserved privately and reports `invalid_provider_response`; public model and
provider metadata are null because no valid transformation response was
returned. The isolated Gateway log classified the local `host-ollama` /
`local-qwen` attempt as `invalid_response`. No text output passed the adapter,
so there is no semantic text review result.

**OBSERVED — provider completion and interpretation:** Ollama's access log
records `POST /api/generate` HTTP 200 in 32.861139467 seconds. Runner logs
report context 8192, 270 prompt tokens and evaluation of exactly 1,024 output
tokens, matching configured `num_predict:1024`; the Ollama response JSON and
`done_reason` were not retained. The Gateway adapter accepts Ollama output
only when `done` is true and `done_reason` is empty or `stop`, and returned
`invalid_provider_response`. **INTERPRETATION:** the output likely reached
the configured token cap rather than ending naturally, which is consistent
with the adapter's rejection. The exact response completion fields and any
text-quality defects are NOT ESTABLISHED because the provider response body
was not captured and no output was accepted for review. No retry or fallback
occurred.

**OBSERVED — GPU and residency:** 27 passive samples were saved, including 25
during inference. Peak sampled use was 8,638 MiB; minimum sampled free memory
was 6,272 MiB; maximum utilization was 82% and maximum temperature 54 C. The
model appeared resident during inference. Immediate postflight at 20:13:08
still showed Qwen resident, GPU at 8,638 MiB used / 6,272 MiB free, 0%
utilization and 51 C. The request returned an unhandled 502, so the configured
stop condition ended the run before its normal cooldown observation. Natural
expiry and memory recovery were **NOT OBSERVED**. No unload was requested.

**OBSERVED — cleanup and production:** the controller stopped its monitor and
readiness stub, terminated and reaped the isolated Gateway with exit status 0,
and recorded no orphan. Production Gateway/STT/TTS remained healthy with the
same IDs, start times and zero restart counts; Gateway health/readiness
remained `alive`/`ready`. No production container or configuration was
changed.

**NOT ESTABLISHED:** a valid public transformation, public provider/model
success metadata, exact Ollama `done_reason`, output text quality, natural
model expiry or GPU recovery. Groq authentication/protocol compatibility and
all Stage 2B fallback cases remain unqualified.

The single-request run stopped for operator review. Do not retry this model or
begin Stage 2C without renewed authorization. Exact private request, bounded
Gateway response, Ollama logs, samples and controller report are in
`private/m05b/stage2b/live-20261022T201232Z/`.

- Current `keep_alive` validation tops out at 5s, despite Stage 2A's separate
  direct Ollama procedure using 60s. No code change is authorized here. If the
  operator requires a longer resident window, request a separately scoped
  implementation change and offline revalidation before live use.
- Groq TLS reachability is established from the host only; authenticated API
  access and provider model support are not established.
- The production Gateway image is not the M05B source; the isolated source
  profile must be used for qualification. No production deployment is part of
  this stage-preparation task.
- Shared Ollama request ownership remains imperfectly observable. Keep calls
  sequential, use the documented GPU abort conditions and do not claim full
  isolation from a shared client solely from an empty `/api/ps` snapshot.
- Synthetic text sent to Groq is external data disclosure. No user transcripts,
  audio, credentials or private content are permitted.

## Approval state

- Offline integration verification: **PASS**
- Isolated test profile: **prepared; config-valid; health/auth/raw route smoke PASS; process stopped**
- Provider network: **Ollama read-only endpoint reachable; Groq TLS verified**
- Live qualification: **INCOMPLETE; stopped after second local request returned invalid provider response**
- Local provider attempts: **2 total; first cancellation-associated Ollama 500, second Ollama 200 at 1,024 tokens / Gateway 502 `invalid_provider_response`**
- Groq requests: **0; not attempted**
- Production Gateway deployment/restart: **NOT AUTHORIZED; NOT RUN**
- Stage 2B operator acceptance and M05B closeout: **PENDING**

## Invalid Ollama completion diagnosis — 2026-10-22

**OBSERVED — adapter rejection rules:** the Ollama adapter in
`internal/texttransform/provider.go` reads at most the configured response cap
plus one byte (262,144 bytes for this isolated profile; default 1 MiB). A
larger body is `FailureInvalidResponse`. For a successful HTTP status, invalid
UTF-8 or malformed JSON is also rejected. The decoded Ollama response is
rejected when JSON decoding fails, `error` is non-empty, `done` is false,
`done_reason` is non-empty and not exactly `stop`, or `response` is empty or
whitespace after trimming. A missing `done_reason` is accepted when `done` is
true. Additional JSON fields, including separate `thinking`/reasoning fields,
are ignored; only the `response` field can be returned. HTTP failures are
classified before JSON validation: Ollama 5xx maps to transport failure, not
`invalid_provider_response`.

**OBSERVED — saved run evidence:** the public response saved in
`private/m05b/stage2b/live-20261022T201232Z/local.response.body` contains only
the sanitized 502 `invalid_provider_response`. The private Ollama log shows
`n_ctx=8192`, a 270-token prompt, and runner generation of exactly 1,024
tokens, equal to configured `num_predict=1024`. Final runner timing reports
1,024 evaluated tokens and `truncated=0`; it does not record Ollama's JSON
`done`, `done_reason` or final `response`. Thus the evidence establishes that
the generation consumed the complete configured token budget. It does **not**
establish which adapter predicate failed, and does not confirm that Ollama
encoded the reason as `length` rather than a missing/empty response or another
invalid field. Token-limit exhaustion is strongly supported as the generation
stop condition; the precise adapter rejection remains undetermined.

The Ollama log also contains a warning that option `think` is invalid, while
the runner reports `thinking = 0`. This indicates Ollama did not recognize
that request option at its option-parsing layer; the run nevertheless used a
non-thinking runner and the warning alone does not explain the invalid final
response. No request setting was changed in this diagnostic.

| Dimension | Successful Stage 2A cases | Stage 2B rejected request | Finding |
| --- | --- | --- | --- |
| Model | `qwen3.5:9b-q4_K_M` | Same selected tag | Historical Stage 2B digest was not captured, so digest identity is not proven |
| Context | 4,096 / 8,192 | 8,192 | Same as one Stage 2A context |
| Output budget | `num_predict=512` | `num_predict=1024`; observed `eval_count=1024` | Stage 2B consumed the full larger budget |
| Keep-alive | `60s` | `5s` | Idle residency difference; does not explain completion validation |
| Thinking | `think=false` in request | `think=false`; Ollama warned this option was invalid, runner logged `thinking=0` | No evidence of reasoning output, but response fields were not retained |
| Sampling | temperature 0, top_p 1, seed 20261022, batch 128, threads 8 | Same configured values | No observed sampling difference |
| System prompt | Stage 2A prompt v2: detailed preservation rules and direct-transformation guidance | Fixed production `systemPrompt` in `provider.go`: concise modes/format rules and preservation constraints | Material wording differs; prompt content was not changed here |
| User framing | Compact JSON object with mode, formatting, target language and text | `Validated options (JSON): <options>` then blank line then `User text (JSON string): <JSON-quoted text>` | Different serialization/framing; Stage 2B Ollama counted 270 prompt tokens |
| Ollama envelope | Direct `/api/generate` harness | Adapter sends top-level `model`, `system`, `prompt`, `stream:false`, `keep_alive`; `options` contains context, prediction, batch/thread, think and sampling values | No contradictory duplicate context/output field in adapter construction |

The saved Stage 2A cases had much smaller observed completions (the one short
8K smoke used `num_predict=64`; the nine-case qualification used 512). The
successful Stage 2A outputs therefore do not show whether this Stage 2B prompt
would have completed within 1,024 tokens. The adapter's strict rejection is
unchanged; no automatic budget increase, prompt edit or validation relaxation
was made.

**OBSERVED — offline regression:** `TestOllamaCompletionValidation` covers
`done=true` with `done_reason=stop`, token-limit reason `length`, missing and
blank final text, a separate `thinking` field, malformed JSON and a body above
the configured cap. The private controller regression also runs an
Ollama-shaped fake through a loopback metadata proxy, verifies that response
bytes are forwarded unchanged, and verifies that the durable metadata file
contains completion reason/counts and character counts but no prompt, output
text or reasoning content. The proxy is enabled only in the private isolated
controller; it does not change the Gateway adapter or production config.

**NOT ESTABLISHED:** the exact `done_reason`, whether the final `response` was
present/non-empty, the exact adapter predicate for the saved HTTP 502, and
semantic quality of the rejected output. No live request was made for this
diagnosis.

**Recommendation:** for a separately authorized bounded local request, use the
private controller's tested loopback metadata proxy. It forwards the bounded
upstream body transiently to the isolated Gateway while durably recording only
an allowlist (`done`, `done_reason`, token counts, durations, model, response
and thinking character counts, body size and JSON keys) in mode-0600 private
evidence. If it records `done_reason=length`, treat that as a model output
budget result and review the output privately before proposing any prompt or
budget change. Preserve the current cap and validator until that evidence is
available. No Ollama or Groq request is authorized or performed by this task.

## Authorized metadata-capture attempt — 2026-10-22 20:20 UTC

**OBSERVED — offline gate and preflight:** before the authorized request,
`.venv/bin/python -m unittest scripts.test_m05b_stage2b_controller -v` passed
six tests, including the fake Ollama response-forwarding and metadata privacy
test. Ruff lint and formatting checks passed. The controller recorded
production Gateway/STT/TTS healthy, unchanged container identities and zero
restarts; Gateway health/readiness were `alive`/`ready`. GPU baseline was
15,360 MiB total, 2,216 MiB used / 12,694 MiB free, 0% utilization, 35 C;
Ollama `/api/ps` was empty.

**OBSERVED — one request and abort:** the controller used the same private
synthetic request file and explicit `local-qwen`, `local_only:true`, context
8192, `num_predict:1024`, `keep_alive:5s`, fixed prompt, 240-second Gateway
deadline, 180-second provider deadline and 245-second client limit. It sent
exactly one request, with no retry or cloud candidate. At the first inference
sample, `nvidia-smi` listed a newly appearing 118 MiB GPU process as `[No
data]`; the monitor treated its unrecognized identity as an unexpected GPU
process and aborted. It closed the Gateway client request. The isolated
Gateway returned HTTP 503 `text_transform_unavailable`; Ollama logged that the
client connection closed before its runner finished loading, then returned
HTTP 499 at 20:21:05.419 UTC. The controller exited 1, terminated/reaped the
isolated Gateway with status 0, and recorded the monitor abort reason. The
private metadata file was not created because Ollama did not return a
completion body. No `done`, `done_reason`, token counts, response/thinking
presence, or provider request duration is available for this attempt.

**INTERPRETATION:** this was a controller-monitor abort during Ollama model
loading, not a completed inference and not an adapter validation result. The
earlier HTTP 502's exact rejection condition therefore remains unknown. The
monitor's process-name identity check does not tolerate transient NVIDIA
`[No data]` entries even when an authorized local Ollama load is in progress.
The single-request authorization has been consumed; do not retry under it.

**OBSERVED — recovery and production postflight:** controller postflight
sampled 8,634 MiB GPU use / 6,276 MiB free / 11% utilization / 38 C with the
Qwen runner process visible while `/api/ps` was empty. Passive read-only
sampling recorded three consecutive empty-residency samples at baseline
2,216 MiB used / 12,694 MiB free / 0% utilization / 36 C by 20:21:39 UTC.
This is natural recovery after the canceled load; no unload was sent.
Production Gateway health/readiness remained `alive`/`ready`; Gateway, STT and
TTS retained the same container IDs, healthy status, start times and zero
restart counts. The isolated Gateway was reaped with no orphan recorded.

**NOT ESTABLISHED:** completion metadata, whether this prompt reaches the
output budget, any adapter predicate for this aborted attempt, transformed
text quality, or the previous 502's exact cause. Evidence for this attempt is
private under `private/m05b/stage2b/live-20261022T202053Z/`, including the
controller report, samples, sanitized 503 response and post-abort recovery
samples. Ollama logs remain in the local service log and show the canceled
load/HTTP 499; sanitized matching lines are preserved in
`private/m05b/stage2b/live-20261022T202053Z/ollama-abort.log`.

**Recommendation:** correct and offline-test the monitor's transient GPU
process identity handling before requesting another diagnostic attempt. A
future attempt requires renewed operator authorization; keep the same prompt,
model, token budget and response validation until completion metadata is
captured. Stage 2B remains stopped for operator review.

## Stage 2B GPU monitoring policy revision — 2026-10-22

The private controller now treats GPU memory safety, telemetry reliability,
process attribution and measurement contamination as separate observations.
It retains one-second samples and the existing 1,024 MiB minimum-free-memory
threshold.

**Immediate abort conditions:** sampled GPU free memory below 1,024 MiB; a
recognized NVIDIA driver/CUDA/OOM error reported by GPU telemetry; three
consecutive failed or invalid GPU memory samples; production Gateway/STT/TTS
health loss, identity/start-time/restart-count change (health snapshots every
five samples); isolated Gateway loss; Ollama residency/monitor failure;
provider/request/client deadline or request failure; or failure to cleanly
stop/reap the owned Gateway. Provider failures remain single-attempt and do
not retry.

**Recorded uncertainty without immediate abort:** `[No data]`, blank, N/A or
other unknown GPU process names; changes in process names for the same PID;
temporary failure to read the compute-process list; and a known additional
GPU process while memory remains above the safety floor. Unknown identities
are retained by PID and in per-sample attribution events. If a later sample
resolves an identity as Ollama-related, correlation requires all of: the
authorized local-inference/cooldown phase, expected Qwen residency in Ollama's
`/api/ps`, and the GPU PID/process observation. The controller records that
correlation as non-exclusive because `/api/ps` and process names cannot prove
which client owns a shared Ollama model. A known additional process that does
not meet that combined evidence marks the measurement contaminated; it does
not by itself cancel inference while resource and health gates remain safe.

GPU memory query failures are counted independently from process attribution:
one or two consecutive failures are recorded as a temporary measurement gap;
a valid subsequent sample resets the streak and records recovery. Three
consecutive failed/invalid memory samples abort. A compute-process query error
with valid memory is an attribution gap, not loss of resource measurement.
Every report summarizes resource-gap count/completeness, unresolved process
PIDs, process-list gaps, contamination status and attribution events. These
observations are private; sanitized qualification records contain only
aggregate results.

Offline regressions cover transient `[No data]` followed by an identified
Ollama process, a request continuing during attribution uncertainty, an
additional process with safe memory headroom, the hard memory floor, transient
and persistent memory telemetry failures, immediate driver-error abort,
production worker health degradation, and child cleanup after an abort. No
live request was performed for this policy change.

**OBSERVED — verification:** controller regressions passed 15 tests, the
Gateway lifecycle regression passed one test, Ruff lint/format and Python
compilation passed, and `git diff --check` passed. Exact commands and test
coverage are recorded in [verification.md](verification.md). No Go source was
changed. The policy change remains offline-only and Stage 2B awaits operator
review before another request.

## Single-request Ollama completion diagnosis — 2026-10-22

**OBSERVED — preflight:** all 15 controller tests and the lifecycle test passed;
the fake Ollama proxy test is included in the controller suite and confirmed
metadata-only capture. The private profile and synthetic request hashes before
and after the run were unchanged. The effective isolated request used explicit
`local-qwen`, `local_only: true`, context 8192, `num_predict: 1024`,
`keep_alive: 5s`, `think: false`, temperature 0, `top_p: 1`, seed 20261022,
and the configured 240-second Gateway / 245-second client deadlines. No Groq
credential was passed to the child process and cloud selection was disabled in
the isolated config. Production Gateway/STT/TTS were healthy, all restart
counts were zero, and container IDs matched before and after. Baseline GPU use
was 2,216 MiB with 12,694 MiB free; Ollama had no resident model.

**OBSERVED — one authorized inference:** the request reached Ollama and
completed in 33.557 seconds client-observed (33.509 seconds at the proxy).
Ollama returned HTTP 200 for `qwen3.5:9b-q4_K_M` with `done: true`,
`done_reason: "length"`, `prompt_eval_count: 270`, and `eval_count: 1024`.
The `response` key was present but its text length was zero. A separate
`thinking` key was present with 4,267 characters; the text itself was not
retained in metadata. There was no provider error. Private whitelisted metadata
is in `private/m05b/stage2b/live-20261022T205331Z/ollama-completion-metadata.jsonl`;
the bounded response and process evidence remain in that ignored private run
directory.

**OBSERVED — Gateway classification:** public response was HTTP 502
`invalid_provider_response`. The adapter rejects an Ollama response when
`done_reason` is non-empty and not `stop` (it accepts empty or `stop`), and
then separately rejects a blank trimmed `response`. This response met both
rejection conditions. The first condition encountered is the
`done_reason="length"` validation. The configured 1,024-token output cap was
exhausted exactly (`eval_count == num_predict`), so token-limit termination is
confirmed for this request. The separate `thinking` field is not treated as
the final response by the adapter. This establishes why the Gateway returned
502; it does not establish that a larger budget would yield a semantically
valid transformation.

**OBSERVED — resources and recovery:** one-second controller samples recorded
8,638 MiB sampled peak GPU use and 6,272 MiB minimum free; the 1,024 MiB abort
threshold was not approached. Ollama residency was observed while the request
was active. The controller stopped immediately after preserving the failed
response and reaped the isolated Gateway (exit status 0); a follow-up passive,
read-only 15-sample observation recorded no resident Ollama model and GPU
memory at the 2,216 MiB baseline (12,694 MiB free) in every sample. No unload
request was sent. The isolated process PID was absent after cleanup. Production
Gateway `/healthz` and `/readyz` returned alive/ready; Gateway/STT/TTS container
IDs, health, start times and zero restart counts were unchanged.

**INTERPRETATION:** the failure is caused by the configured output budget
ending generation while Ollama emitted content only in `thinking`, with no
final `response`. The smallest next change to evaluate is a separately reviewed
increase to the local model's `num_predict` (and a bounded prompt/output review)
before another explicitly authorized single request. Do not relax provider
validation or infer success from `done_reason=stop` alone. No prompt, model
parameter, adapter or production configuration was changed in this diagnosis.

**NOT ESTABLISHED:** output quality under a larger token budget, whether a
changed reasoning setting would produce final text, general provider
qualification, Groq compatibility, deployment readiness, or M05B closeout.
The one-request authorization is consumed; stop for operator review.

## Ollama thinking-control serialization diagnosis — 2026-10-22

**OBSERVED — Gateway request construction:** before this correction,
`internal/texttransform/provider.go` serialized the Ollama Generate body with
top-level `model`, `system`, `prompt`, `stream`, and `keep_alive`, and an
`options` object containing `num_ctx`, `num_predict`, `num_batch`, `num_thread`,
`think`, temperature, `top_p`, and seed. The actual body from the failed live
request was not retained, but the adapter/config reconstruct this shape and
Ollama logged `WARN ... msg="invalid option provided" option=think` at
19:55:09.738 UTC (also at 20:12:35.951 UTC in the subsequent attempt). The
warning matches Ollama receiving the unknown `think` member inside
`options`. This explains why configured `think: false` was ignored.

**OBSERVED — Ollama contract and runtime:** installed Ollama reports version
0.33.1. Read-only `/api/show` for `qwen3.5:9b-q4_K_M` reports capabilities
`completion`, `vision`, `tools`, and `thinking`, plus `requires: 0.30.0`;
its `thinking` detail is null and does not enumerate modes. Ollama's
[Generate API documentation](https://docs.ollama.com/api/generate) defines
`think` as a top-level body field and says boolean `false` requests no thinking
output. The version-pinned [Ollama 0.33.1 GenerateRequest type](https://github.com/ollama/ollama/blob/v0.33.1/api/types.go)
also defines `Think` with JSON name `think` at the request root and documents
false as the no-thinking value. The installed runtime and model metadata are
consistent with supporting this API field; however, no inference was performed
to prove the corrected field's runtime effect on this exact installed model.

**OBSERVED — comparison:** both `scripts/m05a_eval.py` and the successful
`private/m05b/stage2a-20261022/run.py` construct `/api/generate` requests with
`"think": false` at the top level and keep it outside `options`. The previous
Gateway adapter was the outlier. Stage 2A's successful requests are consistent
with correct serialization, though their prompt framing and smaller output
budgets do not by themselves prove the Gateway's corrected live behavior.

**CORRECTION:** the Gateway adapter now places configured `think` at the
top-level of `/api/generate`; `options` retains only generation options.
`think: false` remains explicitly serialized when configured false. Context,
`num_predict`, keep-alive, all sampling values and strict completion validation
are unchanged. The focused fake-server regression asserts top-level boolean
false, absence of `think` in `options`, and the unchanged generation options.

**OBSERVED — offline verification:** `go test ./internal/texttransform -run
'TestHTTPGeneratorOllamaSerialization|TestOllamaCompletionValidation' -count=1
-v` passed, including all completion-validation cases. No live inference,
production deployment/restart, or shared Ollama configuration change was
performed. The full `make verify PYTHON=.venv/bin/python` target also passed,
including `go test -race ./...`, all discovered scripts and STT tests, lint,
configuration/Compose checks, build, and governance/lock checks.

**INTERPRETATION:** placing `think` in `options` caused Ollama to ignore the
intended false setting, allowing reasoning tokens to consume the entire
1,024-token budget and leaving an empty final response. This is the most likely
explanation directly supported by the invalid-option warning, the captured
thinking-only completion, the source serialization and the versioned API
contract.

**NOT ESTABLISHED:** whether the corrected request will produce a nonempty
final response within the unchanged output budget, semantic quality, or wider
Stage 2B provider qualification. One separately authorized bounded live
request is needed to confirm runtime behavior. The prior single-request
authorization is consumed; stop for operator review.

## Single-request Ollama thinking-control verification — 2026-10-22

**OBSERVED — preflight:** focused Go wire-format and completion-validation
tests passed. The Stage 2B controller suite passed 15 tests, including its
fake metadata-proxy test; the isolated Gateway lifecycle test passed. The
private profile still configured one explicit `local-qwen`, `local_only: true`
request with context 8192, `num_predict: 1024`, `keep_alive: 5s`, temperature
0, `top_p: 1`, seed 20261022, batch 128, threads 8, and the production
transformation prompt. Request and profile hashes matched the prior approved
profile. The controller built a fresh Gateway binary in the private run
directory from the corrected source and its configuration check passed. The
offline serialization regression captured top-level `think: false` and
verified `options` contains no `think`; the live proxy intentionally does not
capture request bodies.

**OBSERVED — one live request:** Ollama returned HTTP 200 for
`qwen3.5:9b-q4_K_M`, with `done=true`, `done_reason="stop"`,
`prompt_eval_count=272`, and `eval_count=34`. The final `response` was present
and 144 characters. The `thinking` field was absent. Ollama provider duration
was 10.597 seconds; client-observed Gateway latency was 10.646 seconds. The
Gateway returned HTTP 200 with logical model `local-qwen`, provider
`host-ollama`, `generated=true`, and `fallback_occurred=false`.

**OBSERVED — output review:** the transformation retained the meeting timing,
budget amount, name, and delivery date. It changed “should keep” to “must
maintain,” strengthening the obligation. This is a minor meaning/register
drift to review; it did not affect the lifecycle verification result.

**OBSERVED — GPU and lifecycle:** baseline GPU use was 2,216 MiB with 12,694
MiB free. One-second samples peaked at 8,638 MiB used / 6,272 MiB free. The
last sample with Qwen resident was at 21:03:17.149 UTC; the next sample at
21:03:18.250 UTC showed Ollama residency empty and GPU back at baseline. Eight
additional passive read-only samples from 21:04:21.725–21:04:29.115 UTC showed
no Ollama model resident and GPU at 2,216 MiB used / 12,694 MiB free. No unload
request was sent.

Production Gateway/STT/TTS were healthy before and after, with identical
container IDs, start times and zero restart counts. The isolated Gateway exited
with status 0, was reaped, and its PID was absent. Cloud was disabled in the
isolated configuration, and no fallback or Groq request occurred.

The controller's original report left the request entry marked
`in_progress` and omitted late-added response/recovery fields because it copied
the result before response validation. The preserved response, headers, Ollama
metadata, GPU samples and service snapshots were reconciled in the private
`result-reconciliation.json`; no raw output was added to tracked evidence.

**NOT ESTABLISHED:** whether other transformations will meet text-quality
invariants, broader provider compatibility, Groq compatibility, deployment
readiness or Stage 2C readiness. The single-request authorization is consumed;
stop for operator review.

## Two-request Groq provider qualification — 2026-10-22

**OBSERVED — controller correction:** the prior successful local request had
been copied into `report.json` before response parsing and validation, and no
final state transition followed. The private controller now persists partial
request details while state remains `in_progress`, marks the request
`success` only after schema, metadata, nonempty text, no-fallback and Gateway
liveness checks pass, and finalizes incomplete work as `failed` or
`interrupted`. Finalization copies enriched response metadata, latency and
status into the durable report. Request bodies and bounded responses remain
mode 0600 under the ignored private run directory. No production Gateway code
was changed.

**OBSERVED — offline preflight:** all 19 Stage 2B controller/lifecycle tests
passed, including regression cases for successful result propagation,
preservation of failed partial results, and rejection of success state for
incomplete/interrupted work. Ruff lint and format checks, Python compilation,
`go test ./internal/config ./internal/texttransform ./internal/gateway
-count=1`, fresh `go build -o /tmp/m05b-stage2b-preflight-gateway
./cmd/gateway`, and `git diff --check` passed. The controller also built and
configuration-checked its own fresh private Gateway binary before requests.

**OBSERVED — safety and authorization:** the private profile was loaded into a
new mode-0600 per-run configuration with cloud enabled only in that isolated
copy. The source profile and both prepared synthetic request payloads were
unchanged. The existing `private/groq_api` file was present with mode 0600;
its value was passed only through the isolated Gateway process environment
and was not printed or copied. Production Gateway/STT/TTS were healthy before
and after with unchanged container identities/start times and restart counts
of zero; Gateway health/readiness were `alive`/`ready`. GPU baseline and
post-run samples both showed 2,216 MiB used / 12,694 MiB free, with no Ollama
model resident. No local inference or GPU stress test occurred.

**OBSERVED — exactly two sequential live requests:** both were explicitly
selected synthetic transformations through the isolated Gateway; no retry,
fallback, or extra Groq/local request occurred.

| Logical model / upstream configuration | Reasoning option | Gateway result | Client latency | Public metadata |
| --- | --- | --- | ---: | --- |
| `groq-qwen` / `qwen/qwen3.8-27b` | `none` | HTTP 200 | 0.236 s | model `groq-qwen`, provider `groq`, generated true, fallback false |
| `groq-gpt-oss` / `openai/gpt-oss-120b` | `low` | HTTP 200 | 0.360 s | model `groq-gpt-oss`, provider `groq`, generated true, fallback false |

Both outputs were complete, nonempty Swedish/Russian transformations and the
public responses contained only the documented transformation fields; no
reasoning text or internal provider metadata appeared in transformed text.
The Swedish output preserved uncertainty, the 1,250-dollar amount and November
18 date. The Russian structured output preserved urgency, the unresolved
cause, Maria's ownership, and the November 18 commitment. No material
meaning/name/number/date loss was observed in these two samples. Successful
authenticated responses establish credential acceptance for this run and
live protocol compatibility for these request configurations. Existing
offline provider tests verify `reasoning_effort=none` and `low` serialization;
the live calls completed without provider errors under those configured
options. The test does not capture raw upstream request/response bodies, so it
does not independently prove how Groq internally interpreted the reasoning
controls.

**OBSERVED — cleanup:** the isolated Gateway PID was 2825958; it exited with
status 0, was waited/reaped, and no process remained. The controller exited 0,
recorded both request states as `success` with status, latency and public
metadata, and reported no monitor abort or cleanup error. Private response
evidence and the full sanitized report are in
`private/m05b/stage2b/live-20261022T211011Z/`.

**NOT ESTABLISHED:** broad model quality across the corpus, automatic
selection/fallback behavior against live providers, cloud quota/cost behavior,
production deployment, and Stage 2C readiness. Stage 2B remains subject to
operator review; this qualification does not authorize deployment or
advancement.

## Consolidated offline Gateway API acceptance — 2026-10-22

**OBSERVED:** added
`scripts/test_m05b_stage2b_gateway_acceptance.py`, a standard-library test
controller that builds and owns the actual Gateway executable for each
scenario. It points the isolated profile at deterministic loopback Ollama and
OpenAI-compatible fake providers. The fake cloud endpoint uses a temporary
test certificate installed as a trusted root for that child process; TLS
verification remains enabled. Temporary keys/configuration live under a
private temporary directory, and a sanitized scenario summary is saved at
`private/m05b/stage2b/offline-gateway-acceptance.json` with mode 0600.

The process-level acceptance run passed four tests and exercised:

- `ordered`, `local_first`, and `cloud_first` selection with provider-call
  counts and returned logical model/provider metadata.
- Automatic local-to-cloud fallback and `fallback_occurred=true`.
- Model-scoped HTTP 429 continuing to another model on the provider, and
  provider-scoped HTTP 429 suppressing that provider before local fallback.
- Explicit selection failing without model substitution; global cloud
  prohibition and `local_only` with zero cloud calls.
- Authentication rejection before provider invocation; absent cloud
  credentials returning a transformation-unavailable response while Gateway
  readiness (backed by fake STT/TTS health endpoints) remains ready.
- Exact raw passthrough preserving CRLF and whitespace, with no provider call.
- Sanitized provider HTTP errors, invalid completion rejection and total
  deadline behavior.
- Active provider request cancellation on Gateway SIGTERM with no fallback.

The existing Gateway/provider tests additionally cover caller cancellation,
service-root shutdown cancellation, provider timeout and fallback within the
total deadline, malformed/oversized provider bodies, invalid options, and
credential-resolution behavior. These use deterministic fake generators and
`httptest` boundaries rather than live providers. No STT/TTS model was invoked.

**OBSERVED — full verification:** `make verify PYTHON=.venv/bin/python` exited
0. This includes Go vet and race tests, Ruff lint/format, config and static
Compose checks, release validation, all discovered Python script tests (which
include the new process-level integration controller), all STT tests, build,
governance and STT/TTS lock checks. The separately requested
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest
services.tts.tests.test_tts -v` exited 0 with all 22 TTS/SSML tests passing.
`git diff --check` passed after documentation updates. No Compose services were
started or changed by verification.

**INTERPRETATION:** Stage 2B's Gateway/provider integration acceptance
criteria are met for the implemented configuration and fake-provider cases,
alongside the separately accepted live compatibility observations. The
evidence does not constitute production deployment acceptance, broad
linguistic validation, shared-GPU coexistence or guaranteed cloud capacity.

**NOT ESTABLISHED:** production resource isolation, real provider rate-limit
behavior under quota pressure, all-model quality across the corpus, and
production deployment readiness. Stage 2C deployment qualification should
remain a separate operator decision; the unresolved Stage 2A output-quality
review must be considered before enabling this feature for users.
