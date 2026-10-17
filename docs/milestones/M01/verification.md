# Verification

OBSERVED on 2026-10-17 in local development workspace: Go 1.27.2 linux/amd64, Python 3.13.15, Docker Engine 29.7.2, Docker Compose 5.6.0. No GPU used.

- `make fmt PYTHON=.venv/bin/python`: PASS; intentional formatter run.
- `make verify PYTHON=.venv/bin/python`: PASS (exit 0). Checks gofmt, go vet, Ruff lint/format, all three configuration files, Compose validation and rendered safety checks, race-enabled Go tests, six Python acceptance groups, all three OpenAPI schemas, Go build and Python source parsing. [Captured output](evidence/make-verify.txt).
- `docker compose -f deployments/compose/compose.yaml build`: PASS (exit 0), all three images built after final source changes. No containers started.
- `bash -n scripts/archive-m00.sh`: PASS.
- `git check-ignore russian.m4a`: PASS; private recording ignored. Docker context also excludes audio.
- Read-only SSH source retrieval: FAIL, alias could not resolve. No remote file modified.

Acceptance groups cover missing/unknown/duplicate fields, invalid ports/limits/timeouts, health 200/readiness 503, unavailable inference routes, API document validity, worker import separation, private audio exclusion, nonroot/read-only Compose with private worker ports and internal network, and deployment address literals absent from application sources. Go tests exercise gateway configuration and HTTP handlers. Python HTTP checks start ephemeral loopback servers only, then shut them down.

An initial verification attempt found that this Compose version renders memory byte counts as strings. The checker was corrected to parse those values. Subsequent full runs passed. No inference workload was run.

INTERPRETATION: the local foundation satisfies automated M01 source/build acceptance checks.

NOT ESTABLISHED: user validation; target-host image execution, GPU functionality, inference, routing/auth enforcement, real request cancellation, production throughput or benchmark reproducibility. GitHub Actions is configured but has not run remotely. No claim of full milestone completion.
