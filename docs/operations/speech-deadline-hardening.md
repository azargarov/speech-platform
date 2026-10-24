# Pre-release hardening Stage 1 — ordinary speech deadlines

Status: implemented and offline verified; included in the consolidated v0.2.0
release-candidate review. No deployment or live model qualification was performed.
Scope: ARCH-002 only. At this stage ARCH-005/010 had not yet been addressed;
Stage 2 subsequently implemented TTS permanent-failure readiness and bounded
independent Gateway admission. The Astra review remains preserved as historical
evidence in `docs/reviews/2026-10-22-astra-architecture-review.md`.

Gateway owns one effective deadline, the earlier of the caller deadline and the
configured STT/TTS timeout, from handler processing through request-body reading,
worker dispatch, buffered response completion and started delivery. It forwards remaining whole
milliseconds and does not dispatch with less than one representable millisecond.
Deadline exhaustion is sanitized HTTP 504; transport unavailability remains 503.
A started response write is interrupted on cancellation/expiry without extending
the server's existing I/O limits. HTTP status cannot be replaced after headers
have been committed; disconnected or stalled clients may receive incomplete delivery.
Client disconnect stops delivery and cancels waiting, without claiming native work
or CUDA cleanup has stopped. Public request/response schemas remain unchanged.

STT admission retains active/pending job and byte ownership after a caller stops
waiting. Existing supervisor cancellation, fault latching, shutdown and uncertain
cleanup rules remain in force. HTTP waiting may end independently of cleanup.

TTS consumes the existing X-Request-Timeout-Ms header for ordinary synthesis,
capped by optional validated request_timeout_seconds (default 600 for existing
configuration). Missing header retains this default for internal compatibility;
malformed or nonpositive headers are rejected before loading. Warmup is unchanged.
Deadline/disconnection checkpoints precede model loading, speech segments and
mastering. Active native load/inference is not forcibly interrupted. When it
returns, no later segment/mastering or successful late response is permitted.
FFmpeg's existing bound is shortened by the remaining synthesis deadline.

Verification uses expired contexts, controlled transports/clocks/events, fake
models and local HTTP fixtures. Cover successful budgets, reduced forwarding,
503 versus 504, no post-expiry dispatch, SSML checkpoints, cancellation with
retained STT admission/bytes and existing lifecycle regression suites. Run focused
race-enabled Go tests, worker tests, OpenAPI validation and complete make verify.
No deployment, live model inference, commit or push is authorized by Stage 1.

## Implemented changes

- `internal/gateway/speech_deadline.go` and `handler.go`: ordinary speech budget,
  cancellation-aware body reading, remaining timeout header, 504 versus 503,
  response-read checks and cancellation of started writes. Watchers capture the
  original body and finish before connection reuse. Client defaults no longer
  add five seconds to the configured worker budget. Warmup coordination is unchanged.
- `services/stt/admission.py` and `http_server.py`: reject expired admission,
  return cancelled/deadline callers independently of active execution, retain
  pending/active byte ownership until actual completion, and consume late task
  results without cancelling the owning task. Supervisor/shutdown code is unchanged.
- `services/tts/server.py`, `lifecycle.py`, `audio_processing.py`, `config.py`:
  validate timeout metadata; bound/trickle-proof body reads; checkpoint loading,
  native generation entry/exit, SSML segments and mastering. FFmpeg phases use the
  same remaining deadline and retain temporary-file cleanup. The existing single
  HTTP admission slot remains occupied during active native execution.
- `configs/tts.yaml`: request_timeout_seconds=600, validated positive integer up to
  86400. Older configurations missing this additive field default to 600.
- `api/openapi/public-v1.yaml` and `internal-tts-v1.yaml`: document corrected
  deadline semantics and the existing optional positive internal timeout header;
  public JSON schemas are unchanged. Internal timeout responses include 504.

## Verification observed on 2026-10-24

- `go test -race ./internal/gateway -run '^TestSpeech' -count=10`: PASS.
  Covers both ordinary routes, already-expired callers, expiry during upload,
  cancellation before dispatch, shorter caller budget propagation, worker versus
  response-body timeout, unavailability, real fake-worker HTTP timeout, no retry,
  successful responses and interruption of started delivery.
- `GOTOOLCHAIN=go1.27.2 go test -race ./internal/gateway`: PASS.
- New `services/tts/tests/test_deadlines.py`: configuration defaults/validation,
  expired/no-load cases, completion/failure after a deadline, exact native-entry
  checkpoint, no later SSML work after expiry/disconnection, same mastering
  budget/no second FFmpeg phase, bounded stalled uploads and sanitized errors.
- New `services/stt/tests/test_http_deadlines.py` and runtime regression verify
  HTTP/caller completion is separate from execution and retained audio ownership.
- Five repeated focused Python runs: 6 tests per run, all PASS. Synchronization
  uses events/controlled clocks; fake HTTP disconnection waits for observed EOF.
- `make verify PYTHON=.venv/bin/python`: PASS; 558 script tests, 92 STT tests,
  42 TTS tests and 2 governance tests, plus Go race tests, OpenAPI/schema/config/
  Compose checks, lint, builds and dependency-lock validation.
- Ruff lint/format, all three OpenAPI documents and `git diff --check`: PASS.
- Configured redacted Gitleaks source scan: PASS; no secrets found.

Regression development exposed and corrected a body-watch data race. One old
admission test assumed caller return meant completed cleanup; it now synchronizes
on execution completion before its unchanged zero-retained-bytes assertion, and
an additional test explicitly proves retention while active inference remains.
The native-entry test mocks optional model imports, so normal CI needs neither
TTS weights nor a GPU. An initial repeated-test invocation through Python stdin
could not support multiprocessing spawn; the proper unittest CLI repetitions passed.

## Remaining limits and operator gate

Active native load/inference is not forcibly interrupted. Gateway waiting is
bounded, but an internal TTS HTTP thread/admission slot may remain occupied until
that native call returns; it then reports timeout/cancellation and starts no next
segment. Socket-disconnection detection is best effort at checkpoints. Relative
millisecond worker budgets and transport scheduling are not synchronized clocks;
the Gateway deadline remains authoritative for the public request. A timeout is
never evidence of released CUDA resources or stopped shared loading.

No live GPU/deployed-version qualification was performed. This Stage 1 note is
historical evidence; the consolidated Stage 1–3 changes are currently under
release-candidate review. Matching Gateway/TTS deployment requires separate
approval. No cloud authorization, model, quality/default processing, network,
worker scheduling service or public schema changes were introduced by Stage 1.
