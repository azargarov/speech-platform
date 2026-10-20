# M01F-B2 — Shared deployment locking

Status: **COMPLETE — PASS; operator validated and explicitly closed 2026-10-20.**

## Scope

Implement the accepted host-local project lock contract from M01F-A and ADR
0014, and integrate it into every current `make install` path through
`scripts.stt_deployment`. Keep M01E service selection, pinned image/model
verification, admission, Compose project scoping, readiness and no-op behavior.
No update, rollback, baseline adoption, state initialization, deployment, or
container mutation is authorized by this slice.

## Design and boundaries

- `scripts.project_lock.ProjectLock` owns project identity validation, safe
  lock root/file validation, nonblocking `flock`, persistent lock inode,
  interruption marker and explicit release.
- The existing coordinator owns install planning, state/runtime freshness
  checks, artifacts, Compose lifecycle, health/readiness and completion.
- The lock key is the validated Compose project name. Root is configured with
  `SPEECH_PLATFORM_LOCK_ROOT` (or Make variable `LOCK_ROOT`) and defaults to
  `/srv/speech-platform/deployment-state/locks`, beneath ADR 0014's durable
  host-local state root.
- Install performs read-only preflight, acquires the project lock, repeats
  Compose rendering, current project inspection and GPU admission, then records
  mutation intent immediately before a required image pull, missing-model
  provisioning or Compose lifecycle request. Verified no-op installs do not
  create uncertainty state.
  The B1 state library is not accessed by install. Future operations must take
  this project lock before any state-store-local lock.
- The lock descriptor is inherited by deployment subprocesses. Release closes
  only the coordinator's descriptor; it never explicitly unlocks the shared
  open-file description. Children run in a new process group; timeout or
  interrupt requests TERM then KILL, while normal exit checks for process-group
  survivors. A durable uncertainty marker stays if mutation did not reach
  confirmed readiness or descendants remain. Later cooperating installs block
  pending explicit recovery review.
- Every coordinator entrypoint shares this path because Make and direct module
  invocation both enter the same `run_deployment("install")` function.

## Compatibility and acceptance

Existing install service selection, immutable artifact checks, admission
policy, project scoping, readiness and healthy no-op behavior remain intact.
Concurrent same-project installs fail before staging; different projects can
proceed concurrently. Lock creation/opening rejects symlinks, wrong ownership,
unsafe permissions, unsupported filesystem types and lock inode replacement.
The lock file is never unlinked; PID text is never used to infer ownership.

Tests use temporary directories and fake Compose/artifact providers. Required
verification commands:

```text
.venv/bin/python -m unittest scripts.test_project_lock scripts.test_service_deployment -v
.venv/bin/python -m unittest discover -s scripts -p 'test_*deployment*.py' -v
make verify PYTHON=.venv/bin/python
make governance-check PYTHON=.venv/bin/python
git diff --check
```

## Risks and limits

The advisory lock coordinates only processes using the same lock root and
filesystem semantics. External Docker clients bypass it. Docker daemon work is
asynchronous and can outlive the CLI; a persistent marker blocks cooperating
installs until explicit reconciliation. A privileged `SIGKILL` between
mutation and durable marker cleanup is covered because the marker is synced
before the first possible side effect. Descendants that escape the observed
process group or close the inherited descriptor cannot be proven absent;
operator recovery is required for uncertainty. See the host setup and recovery
procedure in [the B2 operations guide](../../operations/m01f-b2-lock-recovery.md).
Target-host filesystem semantics remain unestablished. Future lifecycle
executors must reuse this lock and lock-before-state ordering.

## User validation gate

Operator review should confirm lock root ownership/mode and local filesystem on
the intended host, same-project exclusion across independent Make invocations,
different-project independence, no-op install behavior, and recovery handling
for an interruption marker. No production install or Docker runtime test is
part of this implementation validation.
