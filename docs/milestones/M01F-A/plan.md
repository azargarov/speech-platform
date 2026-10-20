# M01F-A plan — finalize architecture decisions and ADRs

## Objective

Finalize a reviewable design for controlled VoiceService updates, baseline
adoption, durable state, per-service generations and separately approved
rollback. Preserve canonical M01F and define approved B/C/D implementation
slices without starting them.

## Scope

- Inspect existing architecture, release/configuration contracts, roadmap,
  repository instructions and working tree.
- Revise the architecture design and canonical M01F text for approved
  corrections.
- Record ADRs for durable state, explicit approval/adoption, and rollback and
  recovery policy.
- Update PLANS.md and the M01F-B/C/D slice plan under M01F.
- Run requested governance, repository verification and diff hygiene checks;
  record actual evidence.

## Exclusions

No lifecycle implementation, Docker/Compose operation, running-container
change, artifact download or target-host access. At plan time, milestone
completion and commit were pending their respective explicit approvals; this
closeout request supplies both approvals for the documentation scope only. No
push is authorized.

## Acceptance criteria

1. Design defines state ownership, persistence/crash protocol, baseline
   adoption, per-service compatibility and generation model, operation state
   machines, read-only recovery status and approved durable reconciliation,
   backup, mandatory shared deployment locking and external-mutation
   safeguards.
2. ADRs cover durable state, explicit plan-ID approval/adoption, and separate
   rollback policy.
3. Canonical M01F and PLANS.md agree that B/C/D are slices and implementation
   remains gated.
4. Documentation/governance checks available in the repository are executed;
   outcomes and limitations are recorded without claiming unrun checks.

## Validation commands

- `make governance-check PYTHON=.venv/bin/python`
- `make verify PYTHON=.venv/bin/python`
- `git diff --check`

The user requested these exact checks. The repository verification target
includes application tests; no Docker lifecycle or runtime deployment checks
are in scope.
