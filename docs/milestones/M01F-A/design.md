# M01F-A — Controlled update and rollback architecture

Status: **FINAL — accepted for M01F-A; implementation is not authorized.**
M01F remains the canonical active parent milestone. B/C/D are implementation
slices beneath it. This document does not authorize service mutation or
deployment.

## 1. Scope and evidence boundary

This design refines [canonical M01F](../../architecture/platform-redesign.md#m01f--update-and-rollback)
and the operator-approved corrections. It covers durable state, baseline
adoption, explicit plan approval, per-service generations, update failure
recording, separately approved rollback, crash reconciliation, and operational
safeguards. Update and rollback mutations are not implemented here.

**OBSERVED (repository, 2026-10-20):** M01E is recorded complete after user
validation. The repository provides a strict immutable release descriptor,
model artifact verification/provisioning, deployment configuration
validation, Compose planning/install support, runtime identity inspection and
health probes. The v0.1.2 descriptor records per-service images, capabilities,
dependencies, model requirements and configuration compatibility declarations.
The existing M01E operational store is not a durable update journal or
installed-generation history.

**OBSERVED:** no update/rollback operation, durable installed state, operation
journal, update lock, approval protocol, adoption operation, or interrupted
mutation recovery protocol exists. Gateway and TTS currently expose health
foundations. STT has an implemented bounded inference smoke capability from
accepted M02 work; future smoke remains conditional on an approved bounded
inference contract.

**INTERPRETATION:** this belongs in a host-side deployment coordinator and
small persistence/validation modules under `scripts/`. Compose remains the
runtime service registry. Gateway owns public routing/authentication; STT and
TTS own independent inference and model lifecycle; consumer business logic
remains outside the platform.

## 2. Responsibilities and operation flow

Dependency direction: Make/CLI adapter → planner and operation coordinator →
strict release/config/artifact validators, durable state store, Compose
adapter, Docker read-only inspector and service probes → host runtime.
Coordinator operations carry explicit dependencies; no hidden global state.
No Gateway/STT/TTS application code participates in host lifecycle control.

- `plan-update`: read-only planning for an explicit immutable target and
  selected service scope; emits a plan ID, target identities, current vector,
  compatibility results, resource observations and exact changes.
- `update`: a distinct invocation supplies the exact plan ID and target
  identity for approval. The coordinator revalidates all plan guards under the
  project lock before recording approval and any mutation intent.
- `adopt-baseline`: a separate explicit approval and Docker-read-only operation
  registers an existing healthy M01E deployment as the first managed
  generation. It never calls Docker lifecycle commands.
- `plan-rollback`: read-only plan for a retained eligible generation.
- `rollback`: a separately approved new operation linked to the failed or
  previously successful operation and the exact source and destination
  generations. It never continues the update operation in place.
- `recover/status`: read-only inspection of Docker and durable state. It never
  changes Docker, generations, installed pointers, or operation records. If
  records disagree, it reports the evidence and may present a proposed
  reconciliation plan without persisting it; any write to a
  generation, installed pointer, or operation record requires a distinct
  reconciliation plan and explicit approval. Reconciliation never invokes a
  Docker lifecycle operation, resumes an update, or rolls back automatically.

Artifact staging and verification complete before any service stop. Exact
Compose project and service names are used; selected services are sequenced by
declared dependencies with `--no-deps`. A nonzero lifecycle command is
potentially mutating until read-only runtime inspection establishes otherwise.
No command is replayed merely because its recorded result is absent.

## 3. Service vector and compatibility

The installed platform is a vector, not one release label. For each installed
service record:

`service → release descriptor identity; image identity (manifest digest and
platform); runtime variant; non-secret effective configuration identity;
model identities (zero or more); dependency/compatibility evaluation;
runtime identity; health evidence.`

The generation also records enabled service membership, Compose project
identity and the canonical generation ID. A whole-platform target descriptor
may supply several service identities, but selected-service update changes
only selected services whose effective identities differ. Unselected services
retain their actual prior identities. UI/reporting must never describe the
result as running a single release unless each service vector entry resolves
to that exact release identity.

Compatibility is evaluated only from explicit canonical release declarations:
declared service dependencies, required model identities, supported platform,
runtime variant rules, and `configuration_compatibility` schema/source
constraints. Every required declaration must resolve against the candidate
and the retained identities of affected and unselected services. An unknown,
missing or contradictory required constraint fails closed. An empty or absent
constraint creates no additional requirement. The coordinator must not infer
compatibility from matching version strings or invent a cross-service matrix.
Unselected services that become incompatible block the plan; operator must
select a wider explicit scope or a compatible target.

## 4. Durable state and generation identity

Default host-local root: `/srv/speech-platform/deployment-state`. Validate
that it is a real directory on an approved local filesystem, owned by the
deployment operator/root policy, not writable by group/other, and contains no
symlink path components. Apply restrictive umask; directories mode 0700,
records and lock mode 0600. Verify filesystem type and fsync/rename semantics
are supported; otherwise fail closed. Do not fall back to repository
`private/` on production host. No secret values, audio or transcripts are
persisted.

Persist immutable generation records under `generations/<generation-id>.json`,
immutable numbered operation revisions under
`operations/<operation-id>/r<sequence>.json`, and a separately replaced
installed pointer. For each operation, revision sequence starts at 1 and
increments by exactly one; each revision contains the operation ID, sequence,
and previous revision's canonical digest (null only for revision 1). The
canonical digest is SHA-256 over canonical UTF-8 JSON (sorted keys, no
insignificant whitespace, no non-finite numbers) with the digest field omitted;
the record also binds schema version, parent/source generation IDs, producing
operation ID, per-service identity vector and creation sequence. On read,
validate canonical encoding, digest, identity, contiguous numbering, previous
digest links, operation identity consistency and cross-record links. Missing,
duplicate, malformed, noncanonical or mismatched revisions are corruption and
fail closed; never skip a sequence or choose a branch. Persist a revision via
same-directory temporary file, file fsync, atomic no-replace rename, then
directory fsync. On restart, temporary files are not committed revisions and
are ignored by readers; a valid renamed revision is checked against its full
chain and links before use. A crash before rename leaves no committed
revision; a crash after rename but before directory fsync has uncertain
durability and requires read-only revalidation. Temporary files may be cleaned
only by an explicit approved state-maintenance action. Terminal operation
revisions are immutable and no later revision may extend them; follow-up or recovery work is
a new linked operation. Corrections are new linked records, never edits.

Configuration content is retained as immutable, versioned non-secret
snapshots. Secret values never enter snapshots or journals. Record approved
secret version references, or a host-keyed identity (for example HMAC) where
identity comparison is necessary; do not use an unkeyed digest of low-entropy
secret content. Secret material is resolved from its protected source at
activation time and its approved identity is checked without logging it.

Each durable transition uses same-filesystem temporary write, file fsync,
atomic rename, and parent-directory fsync. Pointer replacement uses the same
protocol. This provides atomic visibility/durability for an individual
record, not atomicity across the generation, installed pointer, operation
revisions and Docker. Cross-record links are validated during inspection.

### Crash windows and reconciliation

| Crash window | Durable evidence possible | Recovery action |
| --- | --- | --- |
| Runtime activation succeeds before readiness | activation intent; command result may be absent; runtime may be candidate, prior, or partial | Inspect exact containers read-only; classify observed identities and health as prior/candidate/mixed/unknown. Never replay activation. |
| Readiness succeeds before pointer promotion | candidate runtime and readiness evidence may exist; installed pointer still names prior generation | `recover/status` reports the mismatch read-only. A proposed reconciliation must be separately planned and approved; the approved recovery operation may persist evidence and promote the pointer if full candidate state is proved. No Docker lifecycle command is issued. Otherwise preserve prior pointer and report partial/unknown. |
| Pointer promotion succeeds before operation terminal persistence | pointer names candidate generation; operation's latest revision may still be VERIFYING | `recover/status` validates pointer target, generation digest, producing operation, runtime vector and health without writes. If proven, plan and approve a new linked reconciliation operation; it records the established update outcome without extending a terminal operation. Otherwise preserve records and report inconsistency/unknown. |
| Operation terminal persistence before pointer promotion | successful terminal record could conflict with old pointer | Protocol forbids writing terminal success before pointer durability. If encountered, treat as corruption/protocol violation; do not infer success. |
| Any record torn/corrupt, missing link, or pointer/generation mismatch | durable store inconsistent | Preserve files; `recover/status` reports `STATE_INCONSISTENT` and does not write state or invoke Docker lifecycle. Repair requires a separate reconciliation plan and explicit approval; if integrity cannot be established, fail closed and retain evidence for offline repair. |

The ordering is: durable operation intent → activation intent → runtime
activation → read-only runtime/readiness evidence → immutable generation record
→ installed pointer promotion → successful operation terminal record. An
operation is not successful until both the generation and pointer are durable
and terminal evidence is persisted. Read-only recovery never closes this
window by writing records. An explicitly planned and approved reconciliation
can write linked durable evidence after revalidation. It cannot change Docker.
No multi-file atomicity claim is made.

### Backup and restore

Back up the complete state root as a consistent, access-controlled snapshot
while the per-project lock is held, or use a filesystem snapshot with verified
crash consistency. Include generations, operations, event evidence, installed
pointers, schema/version metadata, configuration snapshots and required
host-key material/reference metadata. Exclude secret values; separately back
up the protected secret source using its owner’s process. Encrypt backups at
rest, restrict access, record backup identity and verify by restoring into an
isolated directory and validating every record/link/digest. Restoring state
does not change Docker. After host loss or state restore, runtime reconciliation
is read-only first; mismatches require explicit recovery approval. Define and
test retention, backup cadence, key-loss recovery and restore-point objective
before production implementation.

## 5. Baseline adoption contract

`adopt-baseline` is a distinct, explicit operator action. There is no automatic
adoption on first update or when a pointer is absent. It may register only a
complete, healthy, unmanaged M01E VoiceService deployment as initial generation
`G0`; it performs no Docker lifecycle operation, image pull, model download,
container create/start/stop/restart, network mutation, or cleanup.

Before approval and again under lock, require all of the following:

1. Exact Compose project and full service/container identity are unambiguous;
   all enabled expected services are present and healthy, no foreign or
   partially managed service overlaps, and no update/install is active.
2. Inspect exact immutable image identity, platform and provenance for each
   service. Resolve exact model manifest and every file hash. Resolve complete
   validated deployment inputs and effective rendered configuration identity.
   Verify mounts, networks, ports, resources, security identity, runtime UID,
   restart policy and service dependencies against approved M01E/release
   contracts.
3. Verify runtime identities and Compose configuration have not drifted from
   the complete validated inputs. Refuse tags without immutable digest proof,
   missing artifacts, unknown config/secret versions, unhealthy services,
   extra unmanaged containers, ambiguous identity or partial state.
4. Persist operator, timestamp, approval reference, source M01E evidence,
   release/image/model/config identities, runtime inspection, per-service
   readiness/health evidence, verifier versions and hashes, and adoption
   result. This evidence is provenance, not a claim of independent artifact
   authenticity beyond the verifiers and sources recorded.

Adopted generation eligibility for rollback is conditional: every restoration
input (image/provenance, model content, non-secret config snapshot or immutable
reference, secret version reference/host-keyed identity, and supported runtime
definition) must remain retained and re-verified immediately before rollback.
If any input is absent, ambiguous, unsupported or corrupt, the generation is
not rollback eligible. Adoption does not establish an update; it only records
the verified initial vector.

## 6. Approval, state machines, and failure evidence

Plan ID is supplied in a separate invocation for update approval. The plan
binds target descriptor digest, selected services and closure, current
generation/vector, runtime/container observations, configuration and secret
identities, artifacts, compatibility results, resource observations and
policy/schema versions. Approval binds the exact plan ID and actor/time. Any
guard change makes approval stale; stale approval is rejected, never refreshed
implicitly. Replanning yields a new ID and requires a new approval. Rollback
has its own plan ID and approval.

An update operation has states:

`PLANNED → READY → APPLYING → VERIFYING → SUCCEEDED`

Preflight failure is terminal `REJECTED`; post-intent failure is `FAILED` if
the runtime is fully observed, `PARTIAL` if some services changed, or
`UNKNOWN` if runtime outcome cannot be established. Update outcomes are
`REJECTED`, `FAILED`, `PARTIAL`, `UNKNOWN`, or `SUCCEEDED`, and remain distinct
from rollback eligibility. `ROLLBACK_READY` is an eligibility assessment
attached to or linked from the update result; it never replaces that result,
proves restoration inputs remain available, or triggers rollback. Eligibility
can be reassessed separately as retained inputs change. Update outcome
records are terminal and immutable; follow-up or recovery work uses a new
linked operation.

A rollback operation has states:

`PLANNED → READY → RESTORING → VERIFYING → ROLLED_BACK`

with terminal `REJECTED`, `ROLLBACK_FAILED`, `PARTIAL`, or `UNKNOWN` outcomes.
It records `source_operation_id`, `source_generation_id`, target generation,
and its own operation ID. `ROLLED_BACK` means the selected previous vector is
restored, verified, durably promoted as a new installed generation, and
untouched services are preserved. `ROLLBACK_FAILED` preserves original update
failure evidence and rollback failure evidence in separate immutable linked
records/fields. It never overwrites the original error or claims restoration.

Uncertain runtime observation means inspection cannot prove a complete
candidate or prior vector (for example command timeout, daemon unavailable,
container identity ambiguity, GPU cleanup unknown). It is `UNKNOWN`, not
success or safely unchanged. Recovery stays read-only and requires explicit
operator decision before another mutation. Per-service progress is recorded
as `UNCHANGED`, `INTENT_RECORDED`, `ACTIVATION_POSSIBLE`, `ACTIVE_UNVERIFIED`,
`VERIFIED`, `RESTORE_POSSIBLE`, or `UNKNOWN`; these are observations, not
automatic retry instructions.

## 7. Runtime safeguards and evidence for promotion

- A host-local exclusive deployment lock is mandatory for M01F mutations and
  existing `make install`, scoped by canonical Compose project identity and
  backed by one stable lock file/backend. M01F-B must integrate `make install`
  with that same lock before any M01F update operation is executable; preserve
  install selection, side effects, outputs and existing tests. Lock order is
  always project deployment lock first, then any state-store-local lock; never
  acquire them in reverse order. Hold the project lock across freshness
  recheck and each install/update/adoption/approved reconciliation/rollback
  state transition and lifecycle sequence. Read-only plan/status may run
  without the exclusive lock but must report potentially changing observations
  and revalidate under lock before an approved write or lifecycle action. A
  busy, unavailable, incompatible, or untrusted lock fails before side effects;
  do not fall back to operator discipline. Compatibility means the same
  canonical project identity, lock path, advisory-lock semantics and failure
  behavior. The lock file is never unlinked. External Docker/Compose commands
  can still bypass it and remain detectable only by reinspection.
- External Docker/Compose commands can bypass the lock. Reinspect exact
  container IDs, image/config identity and project state immediately before
  every side effect and before promotion. Any unexpected change invalidates
  freshness and yields `PARTIAL`/`UNKNOWN`; no claim of exclusion from
  non-cooperating actors is possible. Host Docker access is part of the trust
  boundary and must be tightly controlled.
- Before stopping CUDA services, perform point-in-time checks for GPU identity,
  free VRAM/headroom, memory/process use, host RAM/disk and expected model
  artifact availability. These checks do not reserve resources. Record values,
  sources and time. If configured thresholds or identity cannot be checked,
  fail before stop.
- After stopping CUDA STT, verify exact container exit and existing cleanup
  evidence: the process/container is gone and GPU memory/process use has
  returned to the approved safe condition. If GPU cleanup is uncertain, stop
  at the safety boundary: do not start candidate or rollback worker, do not
  reset GPU, do not retry in a loop. Persist uncertainty and require operator
  diagnosis. Downtime is expected.
- Before committing any installed generation, verify exact selected service
  image/platform/runtime and config/model identities; health/readiness for
  each service; bounded STT functional smoke only when an approved bounded
  inference contract exists; Gateway and TTS only against implemented health
  contracts; dependency compatibility; untouched-service preservation; no
  unresolved required identity/constraint; complete durable evidence and
  verified restoration inputs for any generation claimed rollback-ready.
  Resource observations are retained, but do not imply future capacity.

## 8. ADRs and implementation slices

The accepted design decisions are recorded in [ADR 0014](../../adr/0014-host-local-deployment-state.md),
[ADR 0015](../../adr/0015-explicit-plan-approval-and-baseline-adoption.md),
and [ADR 0016](../../adr/0016-separate-rollback-and-recovery-policy.md).
These authorize design decisions only; implementation remains separately
gated.

M01F remains one canonical milestone with three approved slices:

- **M01F-B — Durable state, planner, approval and adoption foundation.** Strict
  schemas and state-store checks; immutable per-service generations and
  operation journals; shared project lock design with `make install`; plan
  freshness and separate plan-ID approval; read-only runtime inspection;
  explicit no-lifecycle `adopt-baseline`; compatibility evaluator; backup and
  restore procedure. Acceptance includes crash-window reconciliation tests,
  corrupt/missing state fail-closed behavior, adoption refusal cases, no Docker
  lifecycle calls on plan/adoption, and no secret values persisted.
- **M01F-C — Selected update and failure recording.** Explicit approved update
  only; verify/stage before stop; per-service dependency ordering; resource and
  CUDA cleanup safety; readiness/smoke; immutable generation/pointer
  promotion; precise `FAILED`/`PARTIAL`/`UNKNOWN` evidence. No rollback
  mutation. Acceptance injects failures around activation, readiness, pointer
  promotion and terminal persistence and verifies reconciliation without
  blind replay.
- **M01F-D — Separately approved rollback and recovery rehearsal.** New linked
  rollback operations, exact retained restoration inputs, reverse dependency
  order, separate failure evidence, operator runbook, isolated controlled
  engine rehearsal and backup/restore rehearsal. Real-host operations remain
  M01G and require separate authorization.

Cross-slice M01F acceptance includes selective preservation, exact per-service
identities, explicit compatibility checks, previous image/model/config
restoration where eligible, applicable health/smoke, crash consistency,
downtime and cleanup uncertainty, and preservation of original CUDA baseline
recovery. No slice advances canonical M01F automatically.

## 9. Remaining risks and open decisions

1. Host filesystem allowlist and behavior (local filesystem, ownership model,
   fsync guarantees, backup mechanism) require target-host evidence before
   implementation defaults are finalized.
2. The shared per-project lock contract is selected: canonical project key,
   stable lock path/backend, project-before-state lock ordering and fail-closed
   contention behavior. M01F-B must implement and verify integration with
   existing `make install` before M01F update operations become executable;
   until then, no M01F lifecycle operation may run.
3. Secret source/version-reference mechanism and host-key lifecycle are not
   selected. A reference that cannot be resolved and verified blocks adoption
   and rollback eligibility.
4. Retention, encrypted backup destination/cadence, restore-point objective,
   and host-key-loss recovery need operator policy and rehearsal.
5. Docker mutations by privileged external actors cannot be prevented by the
   application lock; detection is best effort between inspections.
6. Resource checks are snapshots and GPU cleanup evidence thresholds must be
   grounded in M02/host observations; no safe parallel CUDA capacity is
   established.
7. The release descriptor does not currently define a global compatibility
   matrix. Only its explicit declarations can be enforced until its canonical
   contract is extended through separate design and approval.
8. Adoption's exact relationship to future M01G target operation remains
   subject to target authorization and reviewed rehearsal; this design grants
   no target access.

## 10. Verification boundary

M01F-A changes documentation/governance only. Documentation and requested
repository checks are recorded in the M01F-A verification record. No runtime,
Docker operation, artifact download or lifecycle mutation is part of this
design. The user's separate closeout request authorizes a documentation-only
local commit after review; no push is authorized.
