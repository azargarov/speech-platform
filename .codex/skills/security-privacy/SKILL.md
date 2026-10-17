---
name: security-privacy
description: Assess and implement Speech Platform protections when changing sensitive-data
  handling, authentication, dependencies or network trust boundaries.
---

# security-privacy

## Triggers

Use for changes involving audio/transcripts, secrets, authentication, temporary storage, network exposure or dependency/container security. Routine prose edits need no security audit.

## Required inputs

Feature data flow, trust boundaries, deployment exposure, data retention needs, dependencies and existing controls.

## Workflow

1. Perform a proportional threat assessment: identify sensitive assets, callers, entry points and plausible abuse/failure cases; document controls and residual risk.
2. Keep secrets out of source and evidence; use configured secret files or equivalent deployment facilities. Define access, rotation and failure behavior without recording credential values.
3. Keep audio transient and logs free of audio/transcripts by default. Define temporary-data ownership, restrictive permissions, retention and cleanup on success, failure and cancellation; avoid unsafe shared filenames.
4. Apply least privilege, private workers, bounded inputs/resources and safe network exposure. Distinguish build/model provisioning network access from restricted runtime access.
5. Review new dependencies, version provenance and container user/capabilities/mounts. Use an available dependency/image scanner when justified; otherwise inspect declared dependencies and report that scanning was not performed.
6. Add proportionate abuse/error tests and document actual verification, operational controls and remaining risks without embedding private samples.

## Expected outputs

Threat/control notes, focused protections and tests, sensitive-data lifecycle and explicit residual-risk/verification record.

## Validation checklist

- [ ] No secrets/private recordings in Git or verification artifacts.
- [ ] No sensitive payload logging by default; temporary-data cleanup specified.
- [ ] Exposure and privileges minimized; dependency/container review scope explicit.

## Stop and escalation

Pause an action that would expose secrets, persist private data unexpectedly or weaken a trust boundary outside authorization. Report the specific conflict and request only the decision needed; continue safe independent work.

For stage gates and proportional artifacts, consult [methodology](../../../docs/development/methodology.md). Repository rules remain in [AGENTS.md](../../../AGENTS.md).
