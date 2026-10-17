# M01 verification

## Historical baseline evidence

The original verification was recorded on 2026-10-17 in the local development workspace before the initial baseline commit. It reported `make verify`, a Docker image build and an ignore check for the then-root-level audio path as passing. That evidence is retained in [make-verify.txt](evidence/make-verify.txt), but it is not a current remediation run. The old root audio path is obsolete; the recording now resides in ignored `private/audio/russian.m4a`.

## Current remediation evidence

OBSERVED on 2026-10-17 in the local development workspace: Go 1.27.2 linux/amd64, Python 3.13.15 and Docker Compose 5.6.0. No GPU was used. Final local checks were rerun during M01 closeout after recording user validation.

- `make governance-check PYTHON=.venv/bin/python`: PASS, exit 0. See [captured output](evidence/remediation-governance.txt).
- `make verify PYTHON=.venv/bin/python`: PASS, exit 0. Go vet, race-enabled Go tests, Go build, Ruff lint/format, all sample config checks, rendered Compose safety/port checks, 14 Python tests, OpenAPI validation, Python parsing and governance validation passed. See [captured output](evidence/remediation-verify.txt).
- `make compose-check PYTHON=.venv/bin/python`: PASS with sample/default settings.
- `SPEECH_LISTEN_PORT=8765 SPEECH_BIND_IP=127.0.0.2 make compose-check PYTHON=.venv/bin/python`: PASS. Rendered process port and Compose target matched; configured bind matched.
- `SPEECH_LISTEN_PORT=8765 go run ./cmd/gateway --config configs/gateway.yaml --check-config`: PASS, exit 0.
- `git check-ignore -v private/audio/russian.m4a`: PASS; `.gitignore` root `/private/` rule applies. See [captured output](evidence/remediation-config.txt).
- `git diff --check`: PASS, exit 0. See [captured output](evidence/remediation-config.txt).
- Focused tests also cover invalid/inconsistent Compose ports, default/overridden binding, worker isolation, malformed hosts, port and request-size boundaries, worker socket/poll settings, and OpenAPI response/size constraints.
- An early focused invocation of `python -m unittest scripts.test_acceptance scripts.test_compose -v` failed because the new test imported `check_compose` as a top-level module. The import was corrected to `scripts.check_compose`; the focused discovery run and subsequent canonical suite passed.

No Docker image build, container start, deployment or remote access was performed in this remediation.

INTERPRETATION: source/configuration checks can validate the updated Compose mapping and implementation behavior without starting services. Manual read-only target-host checks are prepared in [host-inspection.md](host-inspection.md) and have not been run by Codex.

NOT ESTABLISHED: runtime deployment behavior, image build after remediation, remote CI, inference, authentication enforcement, GPU passthrough, available VRAM at host inspection time, and original M00 source recovery/preservation. User-reported read-only host inspection found no listener on port 8080 at inspection time; this does not establish availability at a later deployment time. Original source recovery is deferred under the user-approved scope exception; it is not a passed preservation check and is not a blocker to M01 closure. User validation has been recorded in [user-validation.md](user-validation.md).
