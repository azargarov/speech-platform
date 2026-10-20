# M01F-B3.1 user validation

Status: **PENDING operator review and separate snapshot-capture approval.**

Review the implementation, verification record and
[ADR 0017](../../adr/0017-private-content-addressed-restoration-snapshots.md),
then validate the planner contract, STT runtime identity source and private
restoration snapshot ownership policy. The first real capture is prepared but
has not been run. The operator-reported privileged check confirms the complete
v0.1.2 model artifact set at `/srv/speech-platform/models` and worker read
access as UID `65532` with supplementary GID `988`. Live Compose still mounts
the same digest from `/var/tmp`; no copy, relocation or bind migration is
included. The capture adapter checks the retained `/srv` store and collects
live runtime state separately.

Fixture validation passed: a complete eligible fixture produces a
deterministic plan, and missing, stale, incompatible, unhealthy or drifted
inputs block eligibility. Temporary snapshot fixtures exercise both complete
and incomplete retained content. The actual plan did not initialize state or
acquire the B2 lock. See [verification](verification.md) for the current
fingerprint, health and blocker list.

Current read-only checks establish release v0.1.2, configuration/runtime
identities, health/readiness, absent installed state and absent uncertainty
marker. The exact storage paths that the writer will initialize are listed in
[verification](verification.md). No external-backup destination is required
for this capture scope. Secret-reference maps must remain empty; any detected
secret dependency makes capture fail closed.

The one-time capture command, to run only after separate operator approval,
is from `/home/master/speech-platform`:

```sh
sudo -u master -g master -G 988 -- .venv/bin/python -c 'from pathlib import Path; from scripts.snapshot_capture_adapter import capture_project_snapshot; print(capture_project_snapshot(retained_model_store=Path("/srv/speech-platform/models")))'
```

It uses the existing project lock, rechecks source/configuration/runtime and
images, verifies the retained model store, creates only the private snapshot
directories listed in the verification record, and publishes the manifest
last. Expected output contains the project name, schema version, snapshot
digest/reference and `staging_retained: True`. A nonzero exit or missing output
is not a captured snapshot. The exact snapshot reference and resulting
verification report must be reviewed after execution. No real snapshot,
adoption or milestone closeout is authorized by this preparation record.
