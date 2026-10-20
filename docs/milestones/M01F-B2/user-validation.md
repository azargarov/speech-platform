# M01F-B2 user validation

Status: **ACCEPTED — PASS; operator validation and explicit closeout approval recorded 2026-10-20.**

## Expected behavior

- Independent installs with the same Compose project cannot overlap and a
  contending caller exits before image/model staging.
- Different Compose projects use separate lock files and can proceed at once.
- An interruption after mutation intent leaves an uncertainty marker and
  blocks later installs until an operator performs review.
- Read-only validation and a fully verified healthy no-op leave no uncertainty
  marker. Artifact, Docker runtime or readiness failure after mutation intent
  retains it.
- A healthy unchanged deployment preserves M01E no-op output and runtime
  identity.
- Lock root and file ownership, permissions, symlink handling and filesystem
  semantics match the intended operator account and host.
- Recovery holds the exact project's exclusive lock, verifies project identity,
  inspects runtime and artifacts, records explicit approval and a determination,
  and performs no automatic Docker repair or rollback.

## Suggested review commands

```text
.venv/bin/python -m unittest scripts.test_project_lock scripts.test_service_deployment -v
make verify PYTHON=.venv/bin/python
make governance-check PYTHON=.venv/bin/python
git diff --check
```

The initial implementation review did not perform target-host validation.
Subsequent approved real-host lock and isolated no-op install validation is
recorded below and in the verification record. For host setup and the recovery procedure, review
[m01f-b2-lock-recovery.md](../../operations/m01f-b2-lock-recovery.md). This
review worksheet does not record operator closeout approval.

## Reviewer record

- Date/operator: 2026-10-20; operator (explicit approval in the current session)
- Findings: final acceptance report reviewed; accepted despite the historical
  `make install` process exit code not being captured. No exit code is inferred.
- Decision: **PASS; approve M01F-B2 closeout.**
- Evidence/environment: final report and preserved real-host lock/no-op
  evidence in [verification](verification.md); current local verification
  rerun is recorded below.

## Controlled no-op installation review — 2026-10-20

- Operator authorization: one controlled `make install` for
  `speech-platform-m01e-fresh-v012` using the reviewed explicit private
  configuration; authorization received before execution.
- Observed coordinator output: Gateway, STT and TTS each reported
  `unchanged and healthy`.
- Post-install evidence: exact target container IDs, start times, restart
  counts, image IDs and Compose config hashes matched; target health/readiness
  endpoints returned HTTP 200; uncertainty marker absent; exact project lock
  reacquired and released through `ProjectLock`.
- Existing original STT, experimental VoiceService project, Ollama and Dify
  container records matched their pre-install snapshots; observed health
  endpoints remained successful.
- Verification record: see [controlled no-op installation](verification.md#one-controlled-no-op-installation--2026-10-20)
  for the plan, exact command, before/after evidence and limitations.
- Review status: **ACCEPTED as PASS** within the recorded no-op acceptance
  scope. The `make install` process exit status was not captured when its
  interactive process session expired. The command was not retried; no exit
  code is inferred.

## Final acceptance review — 2026-10-20

- Final focused project-lock/deployment tests: PASS, 78 tests.
- `make verify PYTHON=.venv/bin/python`: PASS, exit 0; 339 script tests and 61
  STT service tests, with remaining listed checks recorded in
  [verification](verification.md#final-review-and-read-only-host-validation--2026-10-20).
- `make governance-check PYTHON=.venv/bin/python`: PASS, exit 0; 2 tests.
- `git diff --check`: PASS, exit 0.
- Read-only target-host checks: all three target services remain running and
  meet implemented health checks; container IDs, start times, restart counts,
  image IDs and Compose hashes match the recorded baseline; target marker is
  absent and the project lock reacquired/released. Original STT, experimental
  VoiceService, Ollama and Dify showed no observed regression.
- Historical install evidence classifications: runtime preservation PASS;
  service health PASS; lock reacquisition PASS; process exit status NOT
  ESTABLISHED. No exit code was reconstructed.
- Technical acceptance and operator decision: **PASS; accepted and explicitly
  approved for closeout on 2026-10-20.** The missing historical exit code
  remains NOT ESTABLISHED and is retained as a limitation.

## Closeout validation — 2026-10-20

The requested local commands were executed after the acceptance decision:

- `make verify PYTHON=.venv/bin/python` — PASS, exit 0.
- `make governance-check PYTHON=.venv/bin/python` — PASS, exit 0.
- `git diff --check` — PASS, exit 0.

No installation or container/network lifecycle action was run during
closeout. See [verification](verification.md#closeout-verification--2026-10-20).
