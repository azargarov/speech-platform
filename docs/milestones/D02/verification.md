# D02 — Verification Record

Date: 2026-10-25. Environment: repository checkout on `main`, baseline
`6bf5d13de175566c6c84473c3e17051c1ddc1e6e`; changes remained uncommitted.

## Offline checks — OBSERVED

- `.venv/bin/python -m unittest scripts.test_compose_deploy scripts.test_preflight -q`
  — PASS, 60 tests.
- `.venv/bin/python -m ruff format --check scripts/preflight.py scripts/compose.py scripts/deploy_images.py scripts/test_preflight.py scripts/test_compose_deploy.py`
  — PASS, five files formatted.
- `.venv/bin/python -m ruff check scripts/preflight.py scripts/compose.py scripts/deploy_images.py scripts/test_preflight.py scripts/test_compose_deploy.py`
  — PASS.
- `make verify PYTHON=.venv/bin/python` — PASS. Includes Go vet, Ruff, Go config
  checks, Python config checks, Compose/static release validation, `go test
  -race ./...`, full script tests, STT tests (92), TTS tests (63), Go build,
  Python AST parsing, governance tests, and dependency lock checks.
- `git diff --check` — PASS.

The full `make verify` output reported 311 script tests in the prior completed
run before the final D02 test additions; the final focused D02/preflight run
reported 60 tests. The final `make verify` completed successfully after those
additions. Its output was truncated by the terminal capture, so a final aggregate
script-test count is NOT ESTABLISHED here.

## Initial target-host state — OBSERVED, read-only (before migration and commit)

- `make status PYTHON=.venv/bin/python` reported Gateway, STT and TTS running and
  healthy, with source label `9329b574bb5a21fa101d830e26202ff6707b4c4e`.
- Read-only `/readyz` requests to all three current containers succeeded.
- `make preflight PYTHON=.venv/bin/python` returned nonzero on the obsolete
  Gateway image pins. It explained that the two reviewed entries must be removed
  from private `.env`; no values were printed. This blocker was later addressed
  under the authorization recorded below.
- The private `.env` was not modified. No image build, CUDA probe, Compose up/stop,
  inference or service restart occurred.

## Initial target-host qualification — BLOCKED / NOT ESTABLISHED

Live D02 installation, resulting image identities, readiness after recreation,
STT/TTS smoke inference, and Ollama/unrelated-container post-checks remain
unverified. The operator must review the obsolete `.env` entries and separately
authorize a commit or provide a clean committed revision before the new install
path could pass its source guard at that point. The authorized attempt below
records the subsequent commit, migration, and preflight outcome.

## Authorized target-host attempt — 2026-10-25

**OBSERVED — implementation commit and configuration migration:** D02 was
committed with message `refactor(deploy): introduce minimal Make and Compose
deployment`. At the install attempt, clean committed source revision was
`cb627310dd939f7e8a3ce6c5a433007ce57e20b6`. The private
`.env` had mode 0600 and exactly one assignment for each obsolete pin. Before
editing, a timestamped mode-0600 backup was created at
`private/deployment-backups/.env.d02-20261025T095806Z.bak`. Only those two
assignment lines were removed; all other `.env` bytes, including credentials
and cloud settings, were preserved. `preflight.load_env` and
`preflight.validate_environment` accepted the resulting configuration without
printing values.

**OBSERVED — preflight:** `make preflight PYTHON=.venv/bin/python` exited 2.
Host, Docker, local context, GPU, deployment, Compose, Gateway/STT/TTS config,
Ollama eligibility/network/metadata checks passed; one networking warning and
two CUDA probe skips were reported as expected. Both pinned model metadata
checks failed: STT and TTS. No model artifacts were changed.

**OBSERVED — install gate:** `make install PYTHON=.venv/bin/python` verified
clean committed source at the D02 commit, reran preflight, and exited 2 on the
same two model metadata failures. The command stopped before image retention,
image build, CUDA probes, or Compose `up`; no service was replaced or restarted.

**OBSERVED — exact pre-deployment image IDs and post-attempt status:**

| Service | Container | Image ID | Exact image object available | State after install attempt |
| --- | --- | --- | --- | --- |
| Gateway | `f2d1ebf6a398` | `sha256:105b8ab16496d9160d267fa3ab5a9f1e4250d8eb6231987e92553122aa38c320` | Yes | running, healthy, 0 restarts |
| STT | `22c6961ffeed` | `sha256:7e89999512a2a2e7da952616cce78a9f252918be2f9fde6dc140f3e4cc9fb87c` | Yes | running, healthy, 0 restarts |
| TTS | `1308a8fcd148` | `sha256:2fe78236c87ea0e3c9b63e565fedfb32cc73fe20a2f596987f41c252ea03a5b7` | Yes | running, healthy, 0 restarts |

`make status PYTHON=.venv/bin/python` exited 0 after the attempt and reported
the same image IDs/source label as before. The private backup's contents match
the migrated `.env` byte-for-byte after excluding the two removed assignments.
No STT/TTS inference smoke was run because the new stack was not installed. No
cloud inference, Ollama mutation, network change, or unrelated Docker change
occurred.

**NOT ESTABLISHED — recovery selection:** the exact pre-deployment image
objects are present by ID, and a compatible private configuration backup is
available. However, preflight stopped before `deploy_images.retain`, so the D02
rollback tags were not created by this attempt. More importantly, the documented
rollback path checks out a previous source revision and rebuilds it; it does not
select retained image IDs directly. Therefore the requested retained-image
rollback procedure is not established. Do not replace services until this
recovery path and the active model-store access check are resolved. No rollback
rehearsal was performed.

## Model-store access-check correction — 2026-10-25

**OBSERVED — permission and identity assumptions:** the preflight metadata scan
(`_model_metadata`) runs as the host operator. It checks pinned model metadata,
walks the known digest's artifact tree, and checks readability of each artifact
file. The subsequent `model-store access` check also ran as the host operator;
it did not inspect or impersonate the worker container identity. Compose instead
runs both workers as `65532:65532`, adds configured reader GID `988`, and mounts
only the pinned digest directory at `/models` read-only.

The host model-store parent is owned by `root:988` and has mode `2710`; each
pinned digest and artifact directory is `root:988` mode `2750`. The configured
reader group therefore has search/traverse permission on the parent, but no
permission to list that parent. The worker's bind source is the digest directory,
not the parent; GID 988 has read/search on that mounted directory and its files.

**INTERPRETATION — root cause and fix:** after successful pinned metadata
validation, preflight redundantly required both `R_OK` and `X_OK` on the parent
store root. The missing parent-directory read bit is intentional and not needed
to traverse to the known digest. Requiring `R_OK` caused the false model-store
access failure. Preflight now checks only `X_OK` for the parent, while retaining
the existing metadata walk and per-file read checks. It still does not claim to
probe worker-container access; that runtime boundary remains enforced by the
Compose UID/GID/group_add and read-only bind mount, and worker startup checks.
No permission, ownership, ACL, model file, or service was changed.

**OBSERVED — regression and validation:**

| Command | Result |
| --- | --- |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest scripts.test_preflight.ModelStoreAccessTests -v` | PASS; 2 focused tests ensure traversal is required without requesting directory-list permission, and missing traversal remains rejected. |
| `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest scripts.test_preflight -q` | PASS; 49 tests. |
| `sg stt-model-reader -c 'make preflight PYTHON=.venv/bin/python'` | PASS; both STT/TTS metadata checks passed, zero failures, READY TO INSTALL. No install was run. |
| `make preflight PYTHON=.venv/bin/python` | In this execution process, exit 2 because its active supplementary groups do not include GID 988, so the metadata walk cannot read the pinned artifacts. Account database membership for `master` includes `stt-model-reader`; the running process group list is stale. This is distinct from the corrected parent-directory read-bit check. |
| `make verify PYTHON=.venv/bin/python` | PASS, exit 0. |

No deployment, Docker mutation, service restart, inference, or credential change
occurred. The ordinary preflight must be rerun in a process with the operator's
current `stt-model-reader` supplementary group before install authorization is
considered again.
