# M01F-B1 — Durable deployment state foundation

Status: **COMPLETE — PASS; operator accepted and closed 2026-10-20**.

## Scope

Implement an offline Python persistence library for strict version-1 installed
service identities, immutable generations, numbered immutable operation
revisions, installed-generation pointer records, operation outcomes and a
separate rollback-eligibility assessment. Add read-only integrity inspection.
Project identity is supplied from the existing validated deployment profile;
service names come from the existing Compose registry. The configured state
root defaults to `/srv/speech-platform/deployment-state` but this slice does
not initialize or write that host path.

Included: private directory validation, canonical JSON/SHA-256, no-replace
record publication, pointer replacement, fsync boundaries, strict cross-record
inspection and deterministic temporary-directory failure tests.

Excluded: shared project locking and `make install` integration (B2), planner,
plan approval, runtime/Docker inspection, baseline adoption, installed-state
initialization on the host, update/rollback lifecycle, backup/restore policy
and target-host filesystem qualification (B3/B4 or later slices).

## Design and boundaries

`scripts/deployment_state.py` owns serialization, validation and filesystem
operations. It has no Docker, Compose, network, model or application imports.
Its caller supplies project identity and data; Compose remains the service
registry and the existing release/config validators remain authoritative for
those identities. Construction validates an existing store. A separately
explicit `initialize` method is available for authorized setup and temporary
tests, but no CLI or host invocation is added.

Each immutable record is written to a mode-0600 same-directory temporary
file, file-fsynced, published without replacement through an atomic hard link,
and followed by parent-directory fsync. Pointer replacement is an atomic
single-file replace with the same fsync sequence. This is per-record
durability only; generations, operation revisions, the pointer and Docker are
not one transaction. Inspection is read-only and reports inconsistency without
repair.

## Acceptance and validation

- Strict schemas reject unsupported versions, missing/unknown fields and
  prohibited sensitive-data field names.
- Store rejects symlink traversal, unsafe ownership and permissive directories.
- Generation and journal records have canonical encoding and deterministic
  SHA-256; revisions are contiguous, chained and terminal revisions cannot be
  extended.
- Publication fails on duplicate immutable paths; pointer target/checksum and
  cross-record references are inspected.
- Inspection reports corruption, gaps, missing links, unfinished operations,
  invalid pointers and unknown schemas; it does not repair files or contact
  Docker.
- Failure injection uses temporary directories and fake fsync/publication
  hooks. No root, Docker, network, GPU or host state is required.
- Run focused tests, `make verify PYTHON=.venv/bin/python`,
  `make governance-check PYTHON=.venv/bin/python`, and `git diff --check`.

## Risk and limitation

Local filesystem type and target-host fsync/rename semantics are not proven by
temporary-directory tests. B1 therefore does not enable operational state use.
The library does not provide concurrency exclusion; M01F-B2 must add and
integrate the mandatory shared project lock before any operational writer is
enabled. B1 records schemas and validation rules for later operation types,
but implements no automatic repair, baseline adoption, update, rollback,
planning or approval behavior. Those remain assigned as follows: B2 shared
locking and `make install` integration; B3 explicit baseline adoption and
read-only runtime inspection; B4 planning, freshness, approval, compatibility
evaluation and backup/restore procedure; M01F-C selected update and failure
recording; M01F-D separately approved rollback and recovery rehearsal; M01G
target-host filesystem qualification and end-to-end operational validation.
