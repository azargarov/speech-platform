# ADR 0018: Git and Compose as the product operating model

- Status: accepted by operator, 2026-10-20
- Scope: normal installation, runtime operation, and recovery for Speech Platform
- Supersedes: mandatory normal-operation requirements in ADRs 0014–0017; those
  implementations and historical decisions remain preserved and optional

## Context

The service must be straightforward to install and operate from a clean
checkout. Deployment configuration should travel with an immutable Git release
and Docker Compose should own normal container lifecycle. Snapshot/generation
management added substantial operational machinery without being a prerequisite
for the product's speech functionality.

## Decisions

1. Git and Docker Compose are the canonical deployment definition. A supported
   release checkout includes all non-secret production configuration and
   validated examples. Normal installation must not read `private/deployment/`.
2. One canonical Compose deployment describes the supported production service
   set. Host ports, bind address, persistent model store, GPU selection and
   resource bounds are configurable and validated.
3. Normal service recovery is Docker's configured restart policy for process
   crashes. Configuration or artifact failures are diagnosed and repaired by
   redeploying a known-good Git release with Compose.
4. Persistent model artifacts remain outside containers and are mounted
   read-only. The existing verified `/srv/speech-platform/models` store is
   reused; its path remains configurable. No model copy, move or rename is
   implied by this decision.
5. G0 adoption, B1/B2 deployment state, B3 restoration snapshots, immutable
   deployment history, automatic rollback, NAS and external backup are not
   normal installation prerequisites. Existing implementations and tests stay
   available for their optional historical scopes; their prior acceptance
   records are not changed by this ADR.
6. TTS remains health-only. Transcript Refinement is future work. STT v1 owns
   Russian, English and Swedish transcription, automatic or per-request forced
   source language, and an explicit per-request output-language contract.
7. Raw transcription remains available if a translated output is produced.
   The pinned faster-whisper API provides transcription and translation-to-
   English tasks. Same-language output returns the raw transcription. An
   unsupported target pair returns an explicit error; it is never silently
   treated as a transcription. Full arbitrary ru/en/sv translation requires a
   separately qualified local translation backend and resource plan.
8. The public Gateway route is provider-independent. STT owns inference,
   language behavior and model readiness. Gateway forwards the upload, enforces
   public request limits/authentication policy and reports worker availability.
9. The default API bind is loopback. Non-loopback exposure requires a configured
   bearer token; credentials remain outside Git.
10. Future voice dictation keeps STT, optional translation and optional text
    transformation as separate operations. Transformation uses a configurable
    local LLM behind Gateway, never inside the STT worker, and does not block
    ordinary STT when unavailable. Its per-request style modes and desktop/mobile
    clients are planned after STT v1 acceptance in [M05](../milestones/M05/plan.md).

## Consequences

The install/redeploy path becomes a small Make/Compose wrapper around strict
configuration, release, image and model validation. It has no deployment
history or automatic rollback. A failed redeploy is repaired by selecting the
known-good Git release and running the same plan/install commands. External
backup and disaster recovery are separately operated and out of this product
scope.

The public STT schema adds explicit `source_language` and `output_language`
fields while retaining `language` as a compatibility alias for source
selection. The response preserves the existing `text` and `language` fields,
adds the raw `transcription` and explicit language/translation metadata, and
does not fabricate confidence when the backend does not supply it.

## Alternatives

- Require a B1 generation or B3 snapshot for install: rejected because it
  makes ordinary Compose deployment depend on private host state.
- Continue separate experimental and production Compose trees: rejected for
  new product deployment because a release must have one canonical definition.
- Use a cloud translation API implicitly: rejected because it would add an
  undisclosed network and credential dependency.
- Claim Whisper translates to arbitrary requested languages: rejected because
  the backend's translation task targets English.

## References

- [faster-whisper `transcribe.py`](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py)
  documents `task` values `transcribe` and `translate`, and exposes detected
  `language_probability` in its transcription information.
- Historical implementation decisions remain in [ADR 0014](0014-host-local-deployment-state.md),
  [ADR 0015](0015-explicit-plan-approval-and-baseline-adoption.md),
  [ADR 0016](0016-separate-rollback-and-recovery-policy.md), and
  [ADR 0017](0017-private-content-addressed-restoration-snapshots.md).
