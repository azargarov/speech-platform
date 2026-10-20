# M01F-B3.1 — Baseline adoption planning and validation

Status: **IMPLEMENTATION AUTHORIZED; operator review pending.**

## Scope

Implement deterministic, read-only assessment of an existing Compose-managed
VoiceService deployment as a candidate initial generation. The initial target
identity is `speech-platform-m01e-fresh-v012`; a bounded read-only collector
gathers its runtime observations. The planner consumes those observations
and an expected effective runtime contract, then verifies release and local
model artifacts through existing validators.

Included: exact project and service identity checks, B1 state inspection,
B2 uncertainty-marker inspection without locking, release/model validation,
runtime/configuration/readiness checks, retained restoration-input contract,
canonical plan fingerprint, deterministic fixture tests, read-only collection
against the existing target project, and a private restoration snapshot writer
tested only against temporary fixtures and fake evidence.

Excluded: state initialization or writes, real snapshot capture, Docker lifecycle
commands or mutation, approval, adoption, generation creation, update,
rollback, and lifecycle recovery. Read-only Docker inspection and service
probes against the target are included. The original standalone STT is out of
scope.

## Design

`scripts/baseline_adoption.py` coordinates existing authorities. The release
loader validates the immutable descriptor and the Compose registry; the
existing service resolver supplies dependency closure; `check_models` verifies
the pinned model manifest and file hashes; `StateStore.inspect()` validates
existing durable records; and B2 lock paths identify the project uncertainty
marker without opening/acquiring a lock. The collector renders expected
configuration from validated private inputs and independently observes Docker
state plus live readiness. The pure planner boundary makes fixtures
deterministic and prevents it from issuing Docker commands or filesystem
mutations.

The plan includes project and release identity, per-service immutable image,
platform, provenance, model, configuration and runtime identities, health and
container observations, deployment-state/uncertainty status, candidate G0 ID,
per-file model manifest entries and hashes, required retained inputs, blockers,
eligibility and a canonical SHA-256 fingerprint. The fingerprint is over
sorted-key, compact UTF-8 JSON with the fingerprint field omitted; candidate
G0 is derived from the fingerprint of the same plan body before candidate ID
insertion. A plan is evidence for review, not an adoption approval.

Restoration inventory references one available private project snapshot shared
by Gateway, STT and TTS, plus independent per-service configuration and runtime
identities. The manifest and blob rules, allowlists, transitive dependencies,
secret policy and capture protocol are in
[ADR 0017](../../adr/0017-private-content-addressed-restoration-snapshots.md).
Secret values are rejected and never enter plan metadata or snapshot blobs.
The writer has been implemented and fixture-tested; real snapshot capture and
secret-source backup remain separately gated operations.

Final ADR 0017 review refines this contract to one schema-v2 project snapshot
shared by the selected services. The project manifest digest identifies the
complete captured input set; per-service configuration and runtime identities
remain separate and are matched independently. The exact allowlists, conditional
STT provenance evidence roles, host-binding proof, secret policy and
manifest-last capture protocol are in ADR 0017. Real snapshot capture remains
out of the authorized implementation scope and requires operator review.

Compatibility: no B1/B2 record schema or install behavior changes. The planner
is a new offline API and fails closed when evidence is unavailable, malformed,
stale, unsupported or contradictory. It reports an absent state root without
creating it. Existing malformed state blocks eligibility.

## Acceptance and verification

- Fixture coverage for eligible baseline and every requested blocker case.
- Planning leaves absent state and lock roots absent and does not acquire a
  lock or invoke Docker.
- Run focused tests, `make verify PYTHON=.venv/bin/python`,
  `make governance-check PYTHON=.venv/bin/python`, and `git diff --check`.
- The named existing Compose project is inspected read-only; no lifecycle
  operation or durable-state write is performed.
