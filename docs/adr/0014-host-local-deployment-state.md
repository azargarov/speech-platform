# ADR 0014: Host-local durable deployment state

- Status: accepted for M01F-A architecture; implementation separately gated
- Date: 2026-10-20

## Context

M01F update, adoption and rollback need durable provenance across process and
host interruption. Journals and installed state must not live in Git or depend
on the lifecycle they describe. A collection of independently replaced files
cannot be treated as one atomic transaction, and Docker state cannot be
atomically committed with a filesystem record.

## Decision

- Use host-local durable state rooted by default at
  `/srv/speech-platform/deployment-state`, with strict ownership, mode,
  symlink, filesystem and fsync/rename validation. Fail closed if the store
  cannot meet requirements.
- Store immutable versioned generation records and immutable numbered
  operation revisions with explicit IDs, canonical content digests, parent
  links and producing operation IDs. Operation revisions start at 1, increase
  contiguously, and link to the preceding revision digest. Canonical identity,
  encoding, digest, sequence and links are checked on every read; gaps,
  duplicates, forks, malformed data or mismatches are corruption and fail
  closed. Persist each revision through a same-directory temporary file, file
  fsync, atomic no-replace rename and directory fsync. A terminal operation
  revision is immutable and cannot be extended; subsequent work is a new
  linked operation.
- Retain immutable non-secret configuration snapshots. Keep secret values out
  of snapshots, journals and events. Use protected version references or a
  host-keyed identity where comparison is required, never an unkeyed digest of
  low-entropy secret content.
- Persist individual records with same-filesystem temporary write, file fsync,
  atomic rename and directory fsync; this does not provide multi-record or
  Docker/filesystem atomicity. `recover/status` is strictly read-only for
  Docker, generations, installed pointers and operation records; a proposed
  reconciliation plan is not persisted by status. Any reconciliation that writes a
  generation, installed pointer or operation record requires a distinct plan
  and explicit approval. Approved durable reconciliation is host-local and
  never invokes Docker lifecycle operations. Crash ambiguity is reported until
  revalidated; read-only recovery never repairs or completes records itself.
- Back up a lock-consistent or crash-consistent complete state snapshot,
  protect it at rest, verify isolated restore, and keep secret-source backup
  under its separate owner process. State restore never changes Docker.

## Alternatives considered

- Repository-local `private/` as production state: rejected because it couples
  host state to a checkout and has inappropriate operational lifecycle.
- A database or distributed state service: rejected for the one-host Compose
  scope; it adds dependencies without providing atomicity with Docker.
- One mutable JSON state file: rejected because it obscures provenance and
  allows successful history to be rewritten.

## Consequences

State history is auditable and individual durable records have a clear write
protocol. Recovery validates links and compares Docker observations without
writing durable installed state; it cannot blindly replay. Host filesystem
semantics, backup/restore policy,
retention and host-key lifecycle require validation before production use.

M01F-B must use one mandatory per-project deployment lock shared by existing
`make install` and every M01F operation that writes state or changes lifecycle
state. It must preserve existing install behavior and tests. Acquire the
project lock before any state-store lock; fail before side effects when the
shared lock is unavailable or incompatible. M01F update operations are not
executable until this shared-lock integration exists.
