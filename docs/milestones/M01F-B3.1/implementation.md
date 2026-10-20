# M01F-B3.1 implementation record

Status: **IMPLEMENTED; verification and operator review pending.**

## Changes

- Added `scripts/baseline_adoption.py`, a deterministic planner over explicit
  read-only runtime evidence. It reuses the release loader, model verifier,
  dependency resolver, B1 state inspection and B2 uncertainty-marker naming.
- Plans include the verified model manifest file list, sizes and SHA-256 values.
- Added a versioned restoration-input contract requiring available retained
  non-secret configuration snapshots with verification attestations, runtime
  references, and secret version identifiers. Secret values are not part of
  the accepted schema.
- Added fixture-only success and refusal tests in
  `scripts/test_baseline_adoption.py`.
- Added `scripts/collect_baseline_adoption.py` as a separate bounded read-only
  collection path. Expected settings come from validated private configuration
  and rendered Compose; container, image, network, mount, security, hash and
  health evidence comes from Docker inspection and live service probes. It
  does not create retained snapshots or managed state.
- Tightened runtime evidence to require image ID, Compose config hash, Docker
  security settings and time-bounded readiness evidence. Shared state roots
  with no project-specific state are now correctly reported as absent.
- Expanded focused coverage from 12 to 20 tests for absent/contradictory
  observations, expected/observed config mismatch, inspection errors and stale
  readiness evidence.
- Follow-up corrected STT runtime identity collection: Docker's observed
  Compose config hash is compared with a hash independently rendered from the
  validated expected Compose inputs. The STT configuration-set hash remains a
  separate observed identity check.
- Added read-only, strict validation for retained content-addressed snapshot
  manifests and blobs, plus proposed [ADR 0017](../../adr/0017-private-content-addressed-restoration-snapshots.md).
  Snapshot verification checks exact deployable file sets, content digests,
  owner-only permissions, immutable release artifacts and secret-version
  references. At that stage it had no writer; the API was added in the
  implementation section below.
- Added regressions for absent/matching/mismatched STT identity and incomplete
  and complete retained snapshot content. Focused coverage is now 28 tests.

## Snapshot writer implementation — 2026-10-20

The operator approved ADR 0017 architecture in principle. Implemented
`capture_snapshot` in `scripts/restore_snapshot.py` with explicit source roots,
an exact project file-role set and conditional local-image evidence roles,
strict private-input permissions/ACL/symlink/hard-link checks, before/after
source identities, shared B2 lock acquisition, fresh independent runtime
observations, captured-byte config validation/rendering/artifact callbacks,
and content-addressed publication. It stages only allowlisted inputs, checks
staged digests, rechecks source bytes and runtime identity, publishes blobs
first and activates the canonical manifest last. It retains all staging and
does not initialize installed state or write operation records.

Factored B1's durable private-directory and file-publication primitives into
`scripts/durable_files.py`; `StateStore` uses the same helpers. Snapshot
publication is always no-replace and accepts existing objects only after
verification. Duplicate identical snapshots are idempotent. Failed captures
may leave private staging, verified orphan blobs or an empty digest directory,
but without a complete manifest they are not eligible.

Added `scripts/test_restore_snapshot.py` with temporary inputs, fake runtime
evidence and injected publication failures. It covers complete and optional
evidence snapshots, missing/unknown/secret inputs, incomplete dependencies,
source and runtime races, publication interruption, duplicate/corrupt/missing
objects, contention, stale runtime, verifier interoperability, symlink and
hard-link rejection, and that the writer has no Docker or model-store writer.
No production adapter invocation or real snapshot was performed.

The target model store remains at
`/var/tmp/speech-platform-m01e-fresh-v012/model-store`; durability for rollback
assurance is not established. ADR 0017 proposes a separate
`/srv/speech-platform/model-artifacts/voiceservice/m01e-fresh-v012/sha256/`
layout. Storage preparation, artifact copying and running-container bind
migration are separate approvals and remain outside B3.1.

## Final snapshot architecture review — 2026-10-20

- ADR 0017 now defines a project-level schema-v2 snapshot, exact file and
  environment allowlists, secret-safe classifications, complete Compose and
  model dependencies, exact host-path binding evidence, canonical manifest
  identity, strict ownership/mode/link checks, hash verification, and an
  interrupted-capture-safe manifest-last protocol.
- `scripts/restore_snapshot.py` verifies retained snapshots and exposes the
  capture API. B1 publication-helper reuse is implemented. No real snapshot
  was created.
- No approved secret resolver exists. Current secret-reference lists must be
  empty; any credential dependency blocks until the operator approves a
  provider and immutable version-reference format.

## Boundaries and deviations

- Runtime collection remains outside the pure planner. The new collector uses
  only Docker inspect, Compose config rendering and read-only HTTP/Docker exec
  probes, and was run against `speech-platform-m01e-fresh-v012`; see the
  verification record for its blockers and limits.
- No production snapshot, deployment-state record, project lock or Docker
  resource was created or altered. Tests used temporary snapshot and lock
  fixtures. The original standalone STT remains untouched.
- Candidate generation ID is a deterministic `g0-` prefix derived from plan
  content. It does not initialize B1 state.
- Current model artifacts are verified in place, but durable retention for the
  target's `/var/tmp` model root is not established; this remains an operator
  decision before any future capture or adoption.

## Final snapshot preparation — 2026-10-20

- Recorded the operator-reported successful complete model check at
  `/srv/speech-platform/models` and worker read access as UID `65532` with
  supplementary GID `988`. No artifact was copied, moved or changed.
- Kept live runtime collection pointed at the existing `/var/tmp` model bind,
  and changed the capture adapter's retained-artifact verifier to check the
  already-existing persistent store at `/srv/speech-platform/models`. This
  separates the runtime mount observation from retained artifact availability.
- The verified model mapping is `large-v3-turbo`, revision
  `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`, manifest SHA-256
  `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`.
  Release v0.1.2 expects its digest directory directly below the supplied store
  root. The retained store is not the current container bind path; no bind
  migration is included.
- Identified the exact absent private storage directories:
  `private/deployment/m01e-fresh-v012/restoration/`, `staging/`,
  `objects/`, `objects/sha256/`, `snapshots/`, and `snapshots/sha256/`.
  The writer creates these under the existing owner-only deployment root
  using the B1 private-directory helper (`0700`; files `0600`). No manual
  initialization or other path is needed.
- Snapshot metadata records project, release, selected services, service
  configuration/runtime identities, immutable image/model artifact references
  and captured input digests. The existing model manifest supplies model ID,
  repository/revision and payload identities. No extra model-store metadata
  file or directory is required or created.
- A separate external-backup destination is outside this capture-readiness
  scope. Snapshot capture remains gated on explicit operator approval.
