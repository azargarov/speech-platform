# M01F-B2 result

Status: **COMPLETE — PASS; operator validated, accepted and explicitly closed 2026-10-20.**

## Acceptance assessment

| Criterion | Current assessment |
| --- | --- |
| Shared project-scoped exclusive lock used by install | Implemented; focused and full local verification passed. |
| Safe durable lock root, file checks and stable persistent inode | PASS; local tests and real-host ownership, mode, filesystem, stable inode and acquisition/release observations recorded. Default is under ADR 0014's durable state root. |
| Lock held through descendant lifetime, artifacts and readiness | PASS; latest focused and full local verification passed, including child-spawned descendant retaining the inherited descriptor and contention before staging. Escaped descendants remain outside process-group detection. |
| Mutation-phase uncertainty behavior | PASS; local tests verify preflight/no-op remain marker-free; image/model preparation, runtime and readiness failures retain the marker; confirmed readiness clears it. Target marker remained absent through the no-op validation. |
| Recovery procedure | Documented with exact project identity checks, exclusive recovery lock, runtime/artifact inspection, explicit approval, durable audit record and no automatic Docker repair/rollback. |
| Docker daemon and target-host behavior | Bounded no-op behavior PASS on target host; daemon work can outlive CLI completion and external Docker clients bypass `flock`. Those remain documented limitations. |
| Existing install behavior and no-op preserved | PASS; one authorized no-op run reported Gateway, STT and TTS unchanged and healthy; exact before/after identities, health and protected project state matched. The install process exit status is NOT ESTABLISHED. |
| No update, rollback, baseline adoption, production install or state initialization | Update, rollback and baseline adoption are not implemented. No production install or state initialization was performed as part of closeout. |

## Evidence and limits

See [implementation](implementation.md), [verification](verification.md) and
[user validation](user-validation.md). Operator validation and explicit
closeout approval were received on 2026-10-20. The historical controlled
`make install` process exit code was not captured and remains NOT ESTABLISHED;
the command was not retried, and no exit code is inferred. External Docker
clients remain outside `flock` coordination; escaped descendants cannot be
proven absent; Docker daemon work may continue after the CLI exits. Update,
rollback and baseline adoption have not been implemented. M01F-B3 has not
started.
