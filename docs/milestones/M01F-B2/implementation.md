# M01F-B2 implementation record

Status: **IMPLEMENTED; accepted for the bounded B2 scope and closed 2026-10-20.**

## Changes

- Added `scripts/project_lock.py`, a reusable Linux `flock` lock keyed by the
  validated Compose project identity. It validates an absolute owner-only
  directory on an approved local filesystem and opens a persistent, regular,
  owner-only lock inode with `O_NOFOLLOW`. It does not write or trust PID
  ownership metadata.
- Added explicit uncertainty marker creation immediately before a required
  image pull, missing-model provisioning, or Compose lifecycle request. Read-only
  validation and verified no-op paths do not create a marker. It is removed and
  the directory synced only after successful readiness completion. A stale
  marker blocks ordinary installs. The lock inode is never removed.
- Integrated locking in the shared `run_deployment("install")` coordinator.
  After acquisition it re-renders Compose, rechecks project state and GPU
  admission, stages artifacts while locked, rechecks the target service before
  each `compose up`, waits for readiness, then clears the marker. `plan` stays
  read-only and unlocked. The Make entrypoint exposes `LOCK_ROOT` and direct
  CLI callers can set `SPEECH_PLATFORM_LOCK_ROOT`.
- Replaced `subprocess.run` with a `Popen` process-group runner. Under install,
  the lock descriptor is passed into subprocesses. Release only closes the
  coordinator descriptor; it never issues `LOCK_UN`. Timeouts/interruption
  request TERM then KILL. Normal child completion checks for process-group
  survivors and cleans them up, then reports uncertainty. Failure to confirm
  termination produces `UncertainSubprocessError`; the marker remains and future
  cooperating installs fail closed.
- Moved the default lock/marker root to
  `/srv/speech-platform/deployment-state/locks`, under the accepted durable B1
  state root. Added an explicit recovery-lock mode and audited resolution record
  written before marker removal. Added host setup and recovery instructions in
  [the B2 operations guide](../../operations/m01f-b2-lock-recovery.md).
- Added cross-process lock, replacement, filesystem-safety, process lifecycle,
  subprocess timeout/signal and install contention/staging tests.

## Design boundary

No change was made to service selection, immutable artifact validation,
admission decisions, Compose project scope, readiness criteria or deployment
state schemas. B2 install does not access the B1 durable state store. Future
state writers must acquire `ProjectLock` first and then any state-local lock.
No update, rollback, adoption or repair behavior was implemented.

## Residual limitations

`flock` cannot prevent external Docker/Compose activity. Descendants that
escape the observed process group or close their inherited descriptor cannot
be proven absent. The Docker daemon can still finish an accepted request after
the client exits. The durable marker protects cooperating installs after
potential mutation until explicit runtime/artifact reconciliation and approved
resolution. Lock filesystem semantics and owner setup require target-host
validation.
