# M01E result — open

Status: **Experimental CUDA STT deployment acceptance: PASS for the bounded
real-host scope recorded below. Overall M01E remains OPEN pending the full
agreed acceptance scope, user validation and explicit closeout approval.**

The user-reported target evidence records a READY experimental plan, successful
install and readiness, a real transcription with HTTP 200 (`en`, 1.399 seconds),
health of both original and experimental STT, post-inference GPU memory, and
matching container identity/timestamps after repeated installation. The
experimental profile uses a 4,096 MiB pre-load admission threshold. The regular
profile retains its separate 14,336 MiB threshold.

The initial private config access failure and Compose-based readiness probe
failure, plus their implementation corrections, are documented in
[implementation.md](implementation.md) and [verification.md](verification.md).

Parallel inference stress testing was not performed. Concurrency behavior,
sustained performance and peak/process-attributed GPU use under parallel
inference remain NOT ESTABLISHED. The bounded deployment PASS does not satisfy
that remaining agreed scope and does not close M01E. M01F has not started.

## M01E-C result — service selection

The M01E-C implementation acceptance is satisfied by deterministic release
dependency resolution, private enabled-service validation, explicit resolved
service plan output, early rejection of invalid selections, and explicit
`BLOCKED: NOT IMPLEMENTED` dispatch for enabled TTS/Gateway selections. Focused
tests and full local verification are recorded in [verification.md](verification.md).
This phase result does not close M01E. M01E-D, M01E-E, remaining canonical
acceptance, user validation and explicit closeout remain outstanding.
