# M01F-B2 lock setup and uncertain deployment recovery

## Host setup

B2 stores project lock files and uncertainty markers in
`/srv/speech-platform/deployment-state/locks` by default. This is below the
host-local durable state root accepted by [ADR 0014](../adr/0014-host-local-deployment-state.md);
`/run` is not suitable because it is normally cleared at reboot. The directory
must reside on `ext4`, `xfs` or `btrfs`, and its owner must be the non-root
account that runs deployment coordination. The deployment operator must be
able to create the root and `locks/`; both directories must be owned by that
account with mode `0700`. Project lock files, uncertainty markers and recovery
audit records are created with mode `0600`. Do not use symlinks, ACLs, shared
network filesystems or world/group-accessible directories. An alternate root
may be configured with `SPEECH_PLATFORM_LOCK_ROOT`/`LOCK_ROOT`, but it must meet
the same checks and be durable across reboot.

For first-time host setup, an administrator provisions the directory, then
hands ownership to the designated deployment account. For example, substitute
the approved account and ensure `/srv/speech-platform/deployment-state` is the
existing B1 state root before running these commands:

```sh
sudo install -d -o <deployment-operator> -g <deployment-operator> -m 0700 \
  /srv/speech-platform/deployment-state/locks
```

Do not initialize or alter production state as part of B2 validation. If the
state root is not already provisioned, stop and use the separately approved
host-state setup procedure. The operator account must be able to traverse each
parent; the program rejects unsafe symlink components, owner/mode mismatch,
unsupported filesystem types and lock inode replacement.

## Recovery gate

An uncertainty marker means a pull, artifact write or Compose lifecycle request
may have been accepted. It remains until explicit, audited resolution. A failed
subprocess or readiness check does not prove that mutation failed. Do not
retry install, delete the marker, remove containers/images/models, or issue
Docker repair/rollback commands as part of recovery.

1. Open an incident/change record and obtain explicit operator approval for
   recovery. Record the project name and exact approved host/repository.
2. Acquire the exclusive recovery lock for the **exact validated Compose
   project name**, using `ProjectLock(project).acquire(recovery=True)`. This
   recovery-only mode still validates the root, lock file and marker and
   obtains the same exclusive `flock`; it merely permits the operator to
   inspect an existing marker. Keep the lock held through inspection and
   resolution. If lock acquisition fails, stop. Never unlink/recreate a lock
   file or use a force-unlock procedure.
3. Verify identity from the validated private deployment profile and rendered
   Compose project name. Compare the exact project label on every relevant
   container and network. Do not infer identity from names alone. Stop on
   missing, duplicate, foreign or ambiguous resources.
4. Perform read-only inspection of project containers, health/readiness,
   networks, image IDs/digests, local artifact identities and model manifest
   checksums. Capture the exact observations and commands in the incident
   record. Docker inspection is read-only; do not run `up`, `down`, `pull`,
   `rm`, prune, restart, repair or rollback.
5. Determine whether the marked mutation completed and whether the intended
   release and artifacts are complete and healthy. If evidence is incomplete,
   contradictory or indicates partial work, leave the marker in place and
   escalate. The lock is released by closing its descriptor; do not call
   `flock(LOCK_UN)` or manipulate the lock inode.
6. Only after explicit approval and a documented determination, while still
   holding the recovery lock, call
   `resolve_uncertainty(approval_reference=..., determination=...)`. Use a
   change/incident identifier and a concise sanitized summary. The method
   writes and fsyncs a mode-`0600` resolution record before unlinking and
   syncing the marker directory. It performs no Docker action, repair or
   rollback. Preserve the audit record under the host's normal protected
   backup/retention policy.
7. Release the lock and review the recorded resolution. A subsequent install
   remains a separate operator action and must follow normal preflight.

## Lock and Docker limits

`flock` coordinates only processes using the same lock inode and compatible
local filesystem semantics. Inherited descriptors keep the kernel lock held
while ordinary descendants retain them, and the coordinator never explicitly
unlocks the shared open-file description. The coordinator terminates the child
process group on timeout/interruption and checks for process-group survivors
before treating a normally exited client as complete. A descendant that calls
`setsid`, closes the descriptor, or escapes the observed process group cannot
be reliably discovered by this mechanism. A Docker CLI exiting also does not
prove the daemon has finished asynchronous work already accepted. The durable
uncertainty marker therefore remains the fail-closed control after any
potential mutation until runtime and artifact reconciliation plus explicit
operator resolution. External Docker clients do not participate in this lock.
