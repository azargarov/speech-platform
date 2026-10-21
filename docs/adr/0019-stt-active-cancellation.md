# STT active inference cancellation and IPC ownership

Status: accepted for M02-D implementation; runtime validation remains pending.
Supersedes the active-request termination clause of [ADR 0007](0007-stt-execution-lifecycle.md).

## Context

The STT supervisor uses one persistent child and a serialized request/response
pipe. Terminating that child when a cancellation grace expires avoids waiting
for an unresponsive native inference call, but couples cancellation to process
replacement and GPU cleanup. The grace can expire while the child is producing
the original response; reusing the pipe without consuming that response risks
associating it with a later request.

## Decision

For an active request, signal cooperative cancellation and keep polling and
consuming that request's terminal response. Return the caller's cancellation or
deadline error and discard any result once the response has been consumed. Do
not send another request over the channel until this completes. A fatal response
still latches the worker fault and reaps the child, even when cancellation was
also observed.

`cooperative_cancel_grace_seconds` remains a required, validated configuration
field and its existing internal constructor argument remains accepted for
compatibility. It no longer controls active-request termination. Bounded
terminate/kill/reap behavior remains for explicit shutdown, fatal backend
responses, child crashes and IPC protocol/transport failures.

## Consequences

This prevents a late response from being read as another request's result while
preserving a healthy child after ordinary cancellation. Cancellation latency
can extend until native inference returns; the request deadline bounds caller
waiting at the HTTP/admission layer, but does not stop the native call. The
active slot, audio accounting and child remain owned until completion. This
behavior does not establish real CUDA cancellation latency or GPU cleanup.

## Alternatives

- Terminate the child after the grace interval: rejected because active
  cancellation would cause normal worker destruction/reload, and it carries
  increased GPU cleanup and availability costs.
- Add request IDs to responses and discard mismatches: rejected because the
  existing pipe is intentionally single-flight and serialized; retaining that
  invariant is simpler and avoids accepting a response from an old child.
