# M01F-B1 implementation record

## Changes

- Added [`scripts/deployment_state.py`](../../../scripts/deployment_state.py),
  an offline persistence library. It imports the existing project-name
  validator and does not maintain a service registry or invoke Docker/Compose.
- Added [`scripts/test_deployment_state.py`](../../../scripts/test_deployment_state.py)
  with isolated temporary stores and injected filesystem/fsync/publication
  behaviors. Final review added a regression for unhashable malformed health
  and rollback-eligibility values; both now fail with `StateError` rather than
  leaking `TypeError`. Publication directory-open and temporary-file creation
  errors are also classified as `StateError`.
- Added B1 plan, verification, user-validation and result records. `PLANS.md`
  now records B1 COMPLETE — PASS while retaining M01F-B as the active
  implementation slice and B2 as the next step.

## Layout and models

For project `P` under the configured root:

```text
P/
  installed.json
  generations/<generation-id>.json
  operations/<operation-id>/r<sequence>.json
```

The default root is `/srv/speech-platform/deployment-state`. Existing-store
construction validates and never initializes it. Explicit `initialize` is
available to callers that separately own setup; this work did not call it on
the host.

Generation schema 1 records a project, parent generation, producing operation,
creation time and service vector. Each service identity has a fixed field set:
release ID and descriptor digest, immutable image reference/manifest digest,
platform, runtime variant, non-secret configuration digest, model identities,
compatibility result, runtime identity digest, health status and evidence
digest. Operation schema 1 stores operation ID/type/time/state, actual outcome,
optional rollback-eligibility assessment, allowlisted metadata, revision
number, previous revision digest and its own digest. Outcome and rollback
eligibility are separate values. The installed pointer names a generation and
binds its digest.

Within an operation, `operation_id`, `operation_type`, `created_at`, and the
complete `metadata` mapping are immutable. They identify the operation and its
authorization/provenance links. `state` advances only along the M01F-A state
machine; `outcome` must equal a terminal state. `rollback_eligibility` is an
assessment and may evolve between revisions. Revision number, previous digest
and record digest are revision-specific. Writers and inspection apply the same
transition and immutability rules.

Pointer promotion requires a matching generation digest, a parent equal to the
currently installed generation (or null for the first generation), compatible
and healthy service identities, and a valid producing operation chain. The
producer must have reached `VERIFYING`, `SUCCEEDED`, or `ROLLED_BACK`.
`VERIFYING` is allowed because the approved crash protocol promotes the pointer
after verification but before persisting the terminal operation revision.
Inspection accepts this crash window while reporting the operation unfinished.
A generation without eligible producer evidence is orphaned and cannot be
promoted; generation presence alone does not establish success.

Unknown fields and schema versions fail closed. The schema contains no secret,
credential, audio, transcript, host path or diagnostic payload fields. Metadata
is restricted to actor/approval and source/target references. Generation and
operation content use canonical UTF-8 JSON (sorted keys, compact separators,
no non-finite numbers); SHA-256 excludes only the record's own digest field.

## Durability and failure behavior

The store accepts only ext4, XFS or Btrfs as identified by Linux mountinfo.
Directories must be owned by the configured operator UID and exactly mode
0700; records must be owned by that UID and exactly mode 0600. Every path
component is checked for symlinks, and parent traversal and non-absolute roots
are rejected. Reads use no-follow descriptor-relative opens, verify metadata on
the opened file, and reject files with multiple hard links. Publication uses a
no-follow directory descriptor, exclusive no-follow temp creation, no-replace
hard-link publication for immutable records and descriptor-relative pointer
replacement. These measures narrow path-swap races. The trust boundary assumes
the configured root and ancestors are controlled by the host operator and that
no privileged or same-UID adversary mutates the store concurrently; B1 has no
interprocess lock. Target mount identity and durability remain unqualified.

Each record is written to a mode-0600 same-directory temp file, flushed and
file-fsynced, atomically hard-linked to its immutable destination without
replacement, then the parent directory is fsynced. Pointer replacement uses
atomic `os.replace` with the same file and directory fsync protocol. Directory
creation also fsyncs the new directory and parent. A failure before publication
leaves no committed record; a parent-directory fsync failure after publication
leaves a visible record whose crash durability is uncertain and reports an
error. An interruption can leave a `.pending-*` file. Read-only inspection
reports it as `STATE_INCONSISTENT`, does not treat it as committed, and never
deletes or repairs it. Any cleanup requires separate operator review.

These guarantees apply to individual filesystem records only. There is no
multi-file atomicity across generations, operation revisions and pointer, and
no atomicity with Docker. Hard-link, rename and fsync behavior is exercised on
the active filesystem during writes and unsupported filesystem types fail
closed. Target-host semantics remain unverified.

## Inspection and operator boundary

`StateStore.inspect()` is read-only. It validates canonical encoding, schemas,
checksums, generation identity/project and parent/producer links, contiguous
operation revision filenames and numbering, previous-revision hashes,
type-specific state transitions, immutable operation identity/metadata,
unfinished outcomes, generation promotion evidence, and pointer field/type,
target and digest consistency. It reports `STATE_INCONSISTENT` with issue
descriptions and preserves all files. Interrupted `.pending-*` publication
files are reported and preserved. Inspection neither contacts Docker nor
repairs, deletes, completes or reconciles state. Missing state does not trigger
baseline adoption.

B1 supplies no process lock. It is not an operational writer until B2
integrates the mandatory project lock with `make install`. Baseline adoption
is reserved for B3, along with read-only runtime inspection. B4 owns planning,
freshness, approval, compatibility evaluation and backup/restore procedure.
M01F-C owns selected update and failure recording; M01F-D owns separately
approved rollback and recovery rehearsal. M01G owns target-host filesystem
qualification and end-to-end operational validation. B1 has no automatic
repair, lifecycle executor or Docker lifecycle operation. No host state,
running containers, networks or deployment artifacts were modified by this
implementation.
