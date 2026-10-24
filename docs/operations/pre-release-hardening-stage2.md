# SpeechPlatform v0.2.0 pre-release hardening — Stage 2

Scope: Astra ARCH-005 (TTS readiness after permanent model failure) and
ARCH-010 (Gateway buffered speech concurrency). Implementation and offline
verification are complete; this work is included in the consolidated
release-candidate review. No deployment or live inference was performed here.

## Design

- Keep TTS lazy loading and idle unloading. Mark readiness unavailable only
  after explicit model artifact validation or CUDA-availability checks identify
  a permanent configuration/artifact problem. Do not load models from health or
  readiness requests. Resource exhaustion and other recoverable load failures
  remain retryable and do not latch readiness.
- Retain independent FIFO Gateway admission for public STT and TTS. STT allows
  one active request plus three waiters; TTS allows one active request plus one
  waiter. A route holds its active slot through bounded body reads, worker
  response buffering and downstream delivery. Requests beyond the bounded
  waiting queue receive the existing sanitized 429 response. One STT request
  and one TTS request may proceed together.

## ARCH-005 implementation

`services/tts/lifecycle.py` raises a typed permanent model error only for
explicit artifact absence/identity/content validation failures and missing CUDA
availability. The lifecycle records a sanitized failure category. An
unloaded worker with no known permanent fault remains ready; active inference,
idle unload, transient model-load failure and insufficient VRAM do not latch
readiness. A subsequent synthesis or warmup retries initialization; a successful
load clears the permanent failure without restarting the control process.
`services/tts/server.py` exposes the category and actionable remediation at
`/readyz`, while `/healthz` remains liveness. `api/openapi/internal-tts-v1.yaml`
describes these states. Readiness performs no model initialization.

Unclassified failures raised inside VoxCPM's `from_pretrained` remain
recoverable because the library does not provide a reliable permanent-versus-
transient distinction. This avoids falsely latching resource or library
failures. Persistent malformed weights that pass the explicit manifest checks
may therefore continue to be reported as retryable load failures.

## ARCH-010 implementation and budget

`internal/gateway/handler.go` now admits one active STT request with three FIFO
waiters and one active TTS request with one FIFO waiter, independently. A
cancelled or expired waiter is removed before promotion; waiting time consumes
the same absolute request deadline used for body reading and worker calls.
Request bodies are not read or buffered until a waiter receives its active
lease. Known over-limit Content-Length values are rejected before queue entry;
unknown-length bodies remain bounded by MaxBytesReader once admitted. The
Gateway HTTP server also applies its configured read/header timeouts. The public
input ceiling is 25 MiB; STT worker JSON responses
are bounded at 2 MiB; TTS audio responses are bounded at 64 MiB. The TTS
response reader rejects a declared over-limit length before allocation,
allocates exactly a valid declared length, and uses one fixed 64 MiB plus one
byte buffer for unknown/chunked lengths. It does not use a geometrically
growing `io.ReadAll` buffer for large audio. Each slot remains held through
downstream delivery; cancellation and errors release the corresponding slot.

**INTERPRETATION:** STT and TTS buffers are allowed to coexist. During a
maximum STT upload, Go's geometrically grown `io.ReadAll` buffer can temporarily
hold the previous 16 MiB allocation and new 32 MiB allocation (about 48 MiB),
while the independent TTS route can retain a 64 MiB response. The four queued
requests retain only bounded request/context/connection metadata and unread
body streams, not full uploads or synthesized responses. After the upload,
the STT body remains referenced through dispatch and response handling; its
capacity is at most about 32 MiB, with the STT response bounded to 2 MiB (and
small growth overhead). Thus a conservative peak for large application-owned
speech buffers is approximately 112 MiB during simultaneous maximum STT upload
and TTS response, before HTTP scratch buffers and handler state. Against the
default 256 MiB Gateway limit this leaves approximately 144 MiB nominally for Go
runtime, HTTP transport, handler state and other temporary allocations. This
is a defensible operating margin for the configured limits, but it is not a
hard RSS guarantee: Go heap retention, runtime overhead and container
accounting were not stress-measured. Lower custom Gateway memory limits are
not qualified by this calculation.

Capacity exhaustion continues to return the existing sanitized 429
`overloaded` response. STT saturation does not consume TTS capacity and vice
versa. Capacity remains held while a slow downstream write is blocked and is
released when that request completes, fails or disconnects. No API schema,
response-size ceiling, worker lifecycle, or provider policy changed.

## Provider-aware STT admission

The STT admission primitive stores independent provider capacities and
availability in a small Gateway-local record and dispatches from one bounded
FIFO waiting list. Each waiting request carries a pre-authorized eligibility
set. The dispatcher computes a maximum matching across the at-most-three
queued STT requests, prioritizing the oldest requests when assignments have
equal cardinality. Thus a local-only waiter cannot block a later cloud-eligible
request from using idle cloud capacity, while FIFO is preserved among requests
eligible for the same provider. Provider availability changes are event-driven;
there is no background health polling.

Production integration is unchanged: every public STT request is currently
eligible only for local Faster-Whisper. The internal provider record reserves
future Groq Whisper capacity of two but leaves it disabled and unavailable.
There is no Groq adapter, cloud STT request path, public provider-selection
field, cloud authorization change, or cross-provider retry. A future adapter
must validate permissions, `local_only`, global cloud authorization and any
explicit selection before supplying the eligibility set. Explicit selection
must not be silently rerouted; cloud unavailability must not block local-only
queue operation.

The future cloud capacity must not be enabled without reassessing memory:
active STT uploads are buffered by the Gateway, so additional simultaneous STT
operations can raise retained audio memory. The current public route remains
one active local STT request plus three waiters; queued bodies remain unread
until assignment. The existing one-active TTS plus one-waiting queue remains
independent.

## Verification evidence

**OBSERVED:** On 2026-10-24, the provider-aware bounded FIFO refinement passed:

- `GOTOOLCHAIN=go1.27.2 go test -race ./internal/gateway -run 'TestProviderAdmission|TestSpeechAdmission|TestSTTAndTTSAdmission|TestIndependentAdmission|TestAdmissionRecovers|TestQueuedSpeechDeadline|TestQueuedSpeechWaiters|TestSpeechClientCancellation|TestReadBoundedTTSResponse|TestTTSDeclaredOversize' -count=10`
  — passed ten repetitions, including provider eligibility and capacity,
  maximum matching, same-provider FIFO, cancellation/assignment races,
  shutdown wake-up, queue capacity, deadlines, bounded responses and
  independent STT/TTS progress.
- `GOTOOLCHAIN=go1.27.2 go test -race ./internal/gateway` — passed.
- `make verify PYTHON=.venv/bin/python` — passed, including `go test -race
  ./...`, repository script tests, 92 STT tests, 46 TTS tests, 2 governance
  tests, Ruff, configuration/Compose checks, Go build/vet, lock checks and
  governance validation.
- `git diff --check` — passed after the final edits.

The first full verification attempt exposed a fake TTS response that supplied a
body while declaring `Content-Length: 0`; the response-timeout fixture now marks
its intentionally unknown-length body as `Content-Length: -1`. The final full
verification passed with that contract-correct fixture.

**Coverage:** deterministic tests cover cancellation and deadline removal at
the admission primitive, HTTP queued cancellation, Gateway root-context
shutdown, and a real `http.Server.Shutdown` socket-drain path. Shutdown wakes
queued speech requests without dispatching them. Active requests retain their
leases; the integration test releases its fake active worker and confirms
bounded graceful drain. Go's `Shutdown` does not itself cancel active request
contexts.

**NOT ESTABLISHED:** No production memory-load measurement, OOM qualification,
live CUDA test, or deployment was performed. Independent one-active-request
STT and TTS routes permit cross-service overlap. Same-service requests wait
within the configured FIFO queue and are rejected with the established 429
only after that queue is full. Admission is count-bounded rather than a hard
RSS, socket-memory or GPU-memory reservation; queued connections still consume
server/kernel connection resources, and those resources were not
stress-measured. Although the internal primitive has a disabled Groq capacity
record for future integration, public STT remains local-only and does not
increase active audio buffering.
