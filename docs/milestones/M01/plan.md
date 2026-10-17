# M01 plan

Status: **PASS; closed after user validation** (2026-10-17). The foundation and architecture acceptance criteria passed within the approved scope.

## Scope

Preserve the existing Gateway/worker architecture and repository foundation. Reconcile milestone evidence with the initial commit and ignored private audio path; align Gateway listen-port configuration and Compose publication; make current settings truthful and effective; validate host configuration; tighten existing OpenAPI schemas and response declarations. Original M00 sources were not recovered. By explicit user-approved scope decision dated 2026-10-17, source recovery is deferred and is not a blocker to M01 closure; this does not count as a passed source-preservation test, and benchmark reproduction is not claimed. No inference implementation, authentication enforcement, complete routing, container startup, deployment, M02, or commit.

## Acceptance

- `SPEECH_LISTEN_PORT` drives both the Gateway process and Compose target, and validation rejects invalid or inconsistent values.
- Default and overridden gateway host binding are checked; workers remain private on the internal network.
- Gateway request-size enforcement has boundary tests. Worker settings that cannot be effective before inference are removed/deferred explicitly; worker socket timeout and listener polling are validated and applied.
- Malformed gateway/worker hosts and port boundaries are tested.
- OpenAPI schemas validate, with relevant response codes and machine-readable request/string limits.
- M01 records distinguish baseline-era observations from current state; private audio remains ignored and outside Docker context.
- M00 source status is documented as NOT ESTABLISHED (original sources not recovered); the user-approved scope exception defers recovery without marking preservation passed or blocking M01 closure.
- Required governance and verification checks plus `git diff --check` pass, and user validation confirms local checks and read-only host preflight. M01 closes without a deployment. Runtime service behavior and GPU passthrough remain NOT ESTABLISHED.

## Verification

```sh
make governance-check PYTHON=.venv/bin/python
make verify PYTHON=.venv/bin/python
SPEECH_LISTEN_PORT=8765 SPEECH_BIND_IP=127.0.0.2 make compose-check PYTHON=.venv/bin/python
git diff --check
git check-ignore -v private/audio/russian.m4a
```

No containers or remote systems are to be accessed as part of remediation or local verification. Manual host inspection for user validation is described in [host inspection procedure](host-inspection.md); it is read-only and must be run by the user when ready.
