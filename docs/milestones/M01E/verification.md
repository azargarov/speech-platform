# M01E verification history and final acceptance review

Current overall status: **OPEN**. The phase-specific records below retain their
original provenance; the final acceptance review at the end supersedes stale
intermediate pending statements. The M01E-F2 controlled fresh install passed
for its approved scope; user validation and milestone closeout are pending.
Current recommendation: **KEEP OPEN**.

## Phase A verification — historical record

Status: focused local tests passed; full repository verification is incomplete
because required Go tooling, Ruff and two test dependencies are unavailable.
Target host is intentionally not accessed in this phase.

## Evidence

- OBSERVED: host facts in the M01E request, including Docker/Compose/GPU,
  existing STT project and model-store permissions. These are user-reported
  manual inspection results, not independently observed by this workstation.
- NOT ESTABLISHED: target artifact hash verification, sudo group-context
  behavior, target Compose compatibility/rendering, project-name uniqueness,
  GPU free-memory state at startup, GPU container mapping, model load, and
  service coexistence.

## Executed checks

- OBSERVED, 2026-10-18, local checkout/system Python 3.12.3:
  `python3 -m unittest scripts.test_model_artifacts scripts.test_stt_deployment_profile -v`
  — exit 0; 62 tests passed. Coverage includes immutable artifact reuse,
  unchanged bytes/modes/mtimes after verification, preservation of historical
  sibling evidence, configured GPU selection, UUID mismatch and free-VRAM
  rejection, and a non-default configured host GPU index.
- OBSERVED: `python3 -m compileall -q scripts/stt_deployment_profile.py scripts/test_stt_deployment_profile.py scripts/test_model_artifacts.py`
  — exit 0.
- OBSERVED: `git diff --check` — exit 0.
- OBSERVED: `make verify PYTHON=python3` — exit 2 at the lint prerequisite:
  `gofmt` and `go` are not installed. Later Make verification stages did not
  run.
- OBSERVED: `.venv/bin/python -m unittest ...` could not import PyYAML;
  `.venv/bin/python -m ruff ...` could not import Ruff. System Python has
  PyYAML 6.0.1 but no Ruff. No dependency installation was attempted.

NOT ESTABLISHED: formatting/lint via Ruff, Go lint/tests/build, Compose render
against target settings, target group-context access, target model integrity,
target GPU headroom, CUDA/container behavior or shared-service coexistence.
No target-host command was run.

## Make plan/install implementation verification

- OBSERVED, 2026-10-18, local checkout, Python 3.12.3 and Docker Compose 5.6.0:
  `PYTHONPATH=. python3 -m unittest scripts.test_stt_deployment scripts.test_model_artifacts scripts.test_stt_deployment_profile -q`
  — exit 0; 68 tests passed after the release-binding, local immutable-image,
  project resource conflict, read-only artifact and GPU preflight changes.
- OBSERVED: `python3 -m compileall -q scripts/stt_deployment.py scripts/test_stt_deployment.py scripts/stt_deployment_profile.py scripts/test_stt_deployment_profile.py scripts/test_model_artifacts.py`
  and `git diff --check` — exit 0.
- OBSERVED: `make -n plan` and `make -n install` — exit 0 and printed the
  expected Make-driven commands. Neither command was executed against target
  configuration.
- OBSERVED: `make release-check PYTHON=python3` — exit 0; release v0.1.2
  validated.
- OBSERVED: `make compose-check PYTHON=python3` — exit 0, including static CUDA
  overlay validation. This used local static sentinels; it does not establish
  target settings or host runtime behavior.
- OBSERVED: `make verify PYTHON=python3` — exit 2 because `gofmt` and `go` are
  unavailable; it stopped during `lint` before later Make verification stages.
- OBSERVED: `python3 -m ruff check scripts/stt_deployment.py scripts/test_stt_deployment.py`
  — unavailable because Ruff is not installed. No dependency installation was
  attempted.
- OBSERVED: `PYTHONPATH=. python3 -m unittest discover -s scripts -p 'test_*.py' -q`
  — 198 tests discovered, with 2 import errors because `openapi_spec_validator`
  and `aiohttp` are unavailable. The focused M01E tests above passed.
- NOT ESTABLISHED: target Make `plan`, target Compose resource enumeration,
  image presence/digest inspection, group-context artifact verification, live
  GPU headroom, Compose startup, CUDA behavior and shared-service coexistence.
  Per request, no target command, install, pull, container mutation or service
  inspection was performed. User-reported `verified: large-v3-turbo` remains
  attributed to the target-host command they supplied, not a local observation.

## Phase B target configuration preparation

- OBSERVED, 2026-10-18, `llm` (Ubuntu 24.04.5, x86_64): read-only host,
  resource, GPU, listener and Compose-project inspection was performed. GPU 0
  is a Quadro RTX 5000, UUID
  `GPU-8087d1a4-299e-cf92-471b-f96acbdf7d6a`, with 15,360 MiB total and
  12,694 MiB free at inspection. Loopback port 18082 had no listener. Existing
  projects included `speech-platform-stt-runtime-smoke-20261018` and Dify's
  `docker` project. The selected project
  `speech-platform-stt-cuda-m01e-v012` had no containers or networks.
- OBSERVED: `getent group stt-model-reader` returned GID 988. The existing
  private candidate profile records artifact owner UID 0 and reader GID 988;
  those values were reused. The current `master` account is not a member of
  GID 988, and `namei` could not traverse the digest release. `sudo -n stat`
  returned “a password is required.” Model contents, current ownership/modes,
  ACLs and hashes were therefore not independently checked in this phase.
- OBSERVED: read-only `docker image inspect` for the v0.1.2 STT CUDA reference
  reported no local image. `docker buildx imagetools inspect --raw` and
  `--format '{{json .Image}}'` queried registry metadata without pulling the
  image; the pinned manifest maps to config digest
  `sha256:752277812b28e922eac228a80bedd4baf0f616fa5091cb718248c1227f43235a`,
  and its labels matched the release source revision, base digest and CUDA lock.
- OBSERVED: private path/mode validation, profile v2 and STT config schema and
  cross-file checks with `verify_files=False`, exact release/model binding, and
  Docker Compose rendering passed. Model file/hash/permission checks were
  explicitly deferred because the current account lacks the reader group.
  Compose output validated project isolation, loopback Gateway port 18082,
  private un-published STT, selected GPU and read-only mounts.
- OBSERVED: `python3 -m unittest scripts.test_stt_deployment scripts.test_stt_deployment_profile -q`
  — exit 0, 61 tests passed. `git diff --check` — exit 0.
- OBSERVED: profile GPU preflight failed with `GPU free memory is below the
  configured admission gate`; observed 12,694 MiB is below the configured
  14,336 MiB (14 GiB) threshold.
- OBSERVED: exact requested command `make plan SERVICE=stt` — exit 2. Complete
  output:

  ```text
  python3 -m scripts.stt_deployment plan --profile "private/deployment/stt-cuda/profile.yaml" --application-config "private/deployment/stt-cuda/stt-application.yaml" --deployment-config "private/deployment/stt-cuda/stt-deployment.yaml" --worker-config "private/deployment/stt-cuda/stt.yaml" --release "releases/voiceservice-v0.1.2.yaml" --env-file "private/deployment/stt-cuda/compose.env"
  FAIL: deployment plan rejected: model release path is not readable/traversable by the current account; use the configured artifact-reader group context
  make: *** [Makefile:96: plan] Error 2
  ```

- INTERPRETATION: planning from an account with the established reader group
  context will still require the exact v0.1.2 image to be present locally and
  at least 14,336 MiB free on the configured GPU. Planning does not pull an
  image or change host permissions.
- NOT ESTABLISHED: fresh model file/hash/ACL verification, plan success, runtime
  GPU mapping, service startup, inference or coexistence under the new project.

## Phase A continuation verification — 2026-10-18

- OBSERVED: `python3 -m unittest scripts.test_stt_deployment -v` — exit 0;
  12 tests passed. Added behavioral coverage for read-only plan behavior,
  `READY`/`BLOCKED` GPU results, install-time GPU recheck, deployment command
  scope, immutable image provenance and protected operational project refusal.
- OBSERVED: `PYTHONPATH=. python3 -m unittest scripts.test_stt_deployment scripts.test_model_artifacts scripts.test_stt_deployment_profile -q`
  — exit 0; 75 tests passed.
- OBSERVED: `python3 -m compileall -q scripts/stt_deployment.py scripts/stt_deployment_profile.py scripts/test_stt_deployment.py`
  — exit 0; `git diff --check` — exit 0.
- OBSERVED: `make compose-check PYTHON=python3` — exit 0; all base, CPU, CUDA
  build and static CUDA Compose checks passed. These rendered configurations
  without starting containers.
- OBSERVED: `make release-check PYTHON=python3` — exit 0; v0.1.2 release
  descriptor validated.
- OBSERVED: read-only `make plan SERVICE=stt` against the configured local
  target inputs — exit 2 with a complete plan report. It reported release
  v0.1.2, the expected immutable image digest and `image_provenance=verified`,
  large-v3-turbo revision/location, project
  `speech-platform-stt-cuda-m01e-v012`, no project conflicts, 12,694 MiB free
  against 15,032,385,536 bytes (14,336 MiB), and `admission=BLOCKED`. Reasons
  were insufficient free VRAM and current-account model path traversal. The
  existing `compose.env` bytes/mode/mtime and all-container Docker inventory
  were unchanged across the command; 15 containers were present before and
  after. No container lifecycle command was issued.
- OBSERVED: `docker inspect` reported the supplied container's Compose project
  as `speech-platform-stt-runtime-smoke-20261018` and service `stt`, matching
  the code's protected project name. `ss -ltn` showed only loopback port 18081
  listening among 18081, 18082 and 18083.
- OBSERVED: `make verify PYTHON=python3` — exit 2 because `gofmt` and `go` are
  unavailable; it stopped in the lint prerequisite before Python repository
  tests. Focused Python and Compose/release checks above ran independently.
- OBSERVED: `load_and_validate(..., verify_files=False)` on the ignored
  experimental profile reported project
  `speech-platform-stt-cuda-m01e-exp-v012`, profile port 18083, worker port
  8082, target GPU UUID, reader GID 988 and threshold 15,032,385,536 bytes.
  This establishes schema/cross-file validation only, not model bytes or
  permissions.
- INTERPRETATION: tests show planning uses only read-only Compose rendering
  and that install does not reach Compose `up` when its immediate GPU
  recheck fails. Target daemon state and real process environment were not
  exercised by these mocks.
- NOT ESTABLISHED: model integrity/access under reader GID, two-worker VRAM
  use, CUDA startup/readiness,
  transcription, or Ollama/Dify coexistence. No `make install`, image pull,
  container operation, or test procedure was run.

## M01E experimental threshold approval and read-only plan — 2026-10-18

- OBSERVED: the user approved `minimum_free_gpu_bytes_before_load` of
  4,294,967,296 bytes (4096 MiB) for `private/deployment/stt-cuda-experimental/`
  only. Updated that profile's deployment configuration. The operational
  `private/deployment/stt-cuda/` profile and regular deployment configuration
  were not changed.
- OBSERVED: current shell `id` lacks supplementary GID 988, while `id -G
  master` and `getent group stt-model-reader` show `master` belongs to GID 988.
  `namei` could not traverse the model release in the stale shell context.
  `sg stt-model-reader -c 'id && namei ...'` showed GID 988 active and
  successfully traversed the release. This explains the reported blocker as
  the invoking process's stale supplementary-group list, not missing account
  membership. No permission or membership change was made.
- OBSERVED: read-only `make plan SERVICE=stt` with all five Make inputs pointed
  at `private/deployment/stt-cuda-experimental/`, executed inside
  `sg stt-model-reader`, exited 0. It verified release v0.1.2, the pinned
  registry image provenance, and large-v3-turbo artifact files. It reported
  project `speech-platform-stt-cuda-m01e-exp-v012`, no project conflicts,
  12,694 MiB free, threshold 4,294,967,296 bytes, and `admission=READY`.
  This is a point-in-time planning observation only.
- OBSERVED: `nvidia-smi --query-gpu=index,uuid,memory.total,memory.free
  --format=csv,noheader` reported GPU 0, the configured Quadro RTX 5000 UUID,
  15,360 MiB total and 12,694 MiB free.
- OBSERVED: experimental configuration validation and a Docker Compose render
  followed by `validate_rendered_compose` succeeded. Rendered services are
  gateway, stt and tts; the planned install command targets only the explicitly
  named `stt` service in the isolated Compose project. STT has no host-published
  port. The profile Gateway binding is exactly `127.0.0.1:18083 -> 8080`.
- OBSERVED: `ss -ltnp` showed no listener on host port 18083. Read-only Docker
  inventory showed the pre-existing STT container/project, Ollama container,
  and Dify `docker` project; the experimental project name has no existing
  resources. Compose project labels and the dedicated internal STT network
  namespace keep planned `compose up ... stt` scoped to the experimental
  project. No container or network lifecycle operation was issued.
- INTERPRETATION: with GID 988 in the process group context, the model-reader
  blocker is resolved for this plan. The experimental profile's GPU admission
  check currently passes. A future startup still needs a fresh GPU check and
  may be blocked if concurrent GPU use reduces free memory below 4 GiB.
- NOT ESTABLISHED: two-worker VRAM peak, safe coexistence under simultaneous
  workload, CUDA container mapping, service readiness, transcription, and
  sustained GPU headroom. The 4 GiB gate is an approved experimental setting,
  not a measured guarantee or authorization to start a second CUDA container.
- NOT RUN by instruction: `make install`, any Compose lifecycle operation,
  image pull, container start/stop, model permission change, or shared-service
  change. Stop after this read-only plan; milestone advancement and closeout
  remain pending.

## Phase A continuation — Make profile selection and target plan — 2026-10-18

- OBSERVED: `PYTHONPATH=. python3 -m unittest scripts.test_stt_deployment scripts.test_model_artifacts scripts.test_stt_deployment_profile -v`
  — exit 0; 77 tests passed. New Make-level regression checks exercise the
  default regular mapping, explicit regular mapping, experimental plan and
  install mapping, and unknown-profile rejection before the Python command.
  Existing planning coverage checks compose.env/config preservation and rejects
  Docker lifecycle commands.
- OBSERVED: `make -n plan SERVICE=stt`, `make -n plan SERVICE=stt
  PROFILE=regular`, `make -n plan SERVICE=stt PROFILE=experimental`, and
  `make -n install SERVICE=stt PROFILE=experimental` — exit 0; each command
  selected only the expected profile directory. An unknown profile dry run
  exited nonzero during Make parsing and emitted no deployment command.
- OBSERVED: Python compile check and `git diff --check` — exit 0.
- OBSERVED: `make compose-check PYTHON=python3` and
  `make release-check PYTHON=python3` — exit 0. Compose checks rendered static
  configurations only; release check validated v0.1.2.
- OBSERVED, target host, using `sg stt-model-reader`:
  `make plan SERVICE=stt` exited 2 and reported pinned image provenance
  verified, model artifact validated, no project conflicts, 12,694 MiB free,
  15,032,385,536-byte (14,336 MiB) threshold, and `admission=BLOCKED` solely
  for insufficient free VRAM. The model path was readable in this group
  context.
- OBSERVED, target host, using `sg stt-model-reader`:
  `make plan SERVICE=stt PROFILE=experimental` exited 0 and reported the same
  verified release/image/model, isolated project
  `speech-platform-stt-cuda-m01e-exp-v012`, no project conflicts, 12,694 MiB
  free, 4,294,967,296-byte (4,096 MiB) threshold, and `admission=READY`.
- OBSERVED: SHA-256 digests for the four regular files, four experimental
  files, and regular compose.env were identical before and after both target
  plans. The regular compose.env size, mtime and mode also remained identical.
  The deployment planner uses Docker image/container/network inspection and
  Compose config rendering; no Docker lifecycle command was run. Plans used
  Python bytecode writing disabled by the Make target.
- NOT RUN by instruction: `make install`, Compose lifecycle operations, image
  pulls, permissions changes, or changes to running services. Static results
  and the experimental READY observation do not establish concurrent runtime
  safety or M01E PASS. User validation and closeout remain pending.
## M01E experimental startup correction — 2026-10-18

- OBSERVED: read-only `docker inspect speech-platform-stt-cuda-m01e-exp-v012-stt-1`
  reported the container exited with code 1, `OOMKilled=false`, health
  `unhealthy`, runtime user previously reported as UID/GID 65532:65532, and
  supplementary group 988. It showed three config bind mounts from
  `private/deployment/stt-cuda-experimental/{stt.yaml,stt-application.yaml,stt-deployment.yaml}`
  to `/config/...`, each `Mode=ro`, `RW=false`; the model mount is also
  read-only. No config contents were read or printed.
- OBSERVED: `stat` and `namei -l` showed `private`, `private/deployment`, and
  the experimental directory at mode 0700 owned by `master:master`; the four
  profile/config files were mode 0600, also `master:master`. Thus UID 65532
  and supplementary GID 988 had no path traversal or file read permission.
- OBSERVED: `chgrp 988` on only the experimental config path/parents failed
  with `Operation not permitted`; `sudo -n` reported a password is required.
  No mode or owner/group change occurred. The required host permission fix is
  therefore NOT ESTABLISHED in this workspace.
- OBSERVED: `python3 -m unittest scripts.test_stt_deployment -v` — exit 0,
  22 tests passed, including unreadable file, preflight blocking before any
  Docker command, early container exit, unhealthy state, ready state and
  bounded startup timeout regressions.
- OBSERVED: `python3 -m py_compile scripts/stt_deployment.py
  scripts/test_stt_deployment.py` — exit 0. `docker compose ps --help` — exit
  0. No Compose lifecycle command was run.
- INTERPRETATION: with POSIX mode access corrected, the new install preflight
  prevents container creation for any selected config file the worker identity
  cannot read. Compose success is no longer treated as installation success;
  Docker health must reach `healthy` before the CLI returns zero.
- NOT ESTABLISHED: post-start health behavior on the target, actual config
  access after permission correction, model startup, inference, and continued
  baseline health. No container was restarted or otherwise mutated.

### Read-only retry commands

The individual config mounts need no container traversal through their host
parent directories. Preserve those directories at mode 0700 and leave the
three group-readable config files at mode 0640. Run the plan in the configured
model-reader group context to satisfy traversal for the `/models` directory
mount:

```sh
sg stt-model-reader -c 'make plan SERVICE=stt PROFILE=experimental'
```

The plan remains isolated to `speech-platform-stt-cuda-m01e-exp-v012` and
retains the experimental 4 GiB GPU admission threshold. `make install` is
outside this correction and requires separate approval.

## M01E individual config bind-mount correction — 2026-10-18

- OBSERVED: `deployments/compose/compose.stt-cuda.yaml` declares each STT config
  source as an individual read-only file mount (`source:/config/name:ro`);
  `/models` is the directory bind mount. `deployments/compose/compose.yaml`
  sets `user: "65532:65532"`, and the CUDA overlay adds the configured reader
  GID through `group_add`.
- OBSERVED: the experimental profile remains mode 0600, its three individually
  mounted config files are mode 0640 owned by `master:stt-model-reader`, and
  their private parent directories remain mode 0700.
- OBSERVED: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m unittest
  scripts.test_stt_deployment scripts.test_stt_deployment_profile -q` — exit
  0; 76 tests passed. `git diff --check` — exit 0.
- OBSERVED: `make plan SERVICE=stt PROFILE=experimental` exited 2 after passing
  the config permission preflight. It reported image provenance verified,
  `conflicts=matching project reusable`, and GPU free memory 12694 MiB against
  the approved 4096 MiB threshold. Admission remained BLOCKED because the
  current account cannot traverse the model release path; the planner advised
  using the configured artifact-reader group context. No container lifecycle
  command or permission change was run.
- INTERPRETATION: individual file bind mounts remove the need for the
  container identity to search host-side config parent directories. The
  remaining plan blocker is model-release directory access, which is still a
  real directory-mount requirement and retains strict traversal checks.
- NOT ESTABLISHED: the plan has not yet completed under the configured model
  reader group context; no install, container restart, inference, or baseline
  health check was run.

## M01E readiness correction verification — 2026-10-18

- OBSERVED: `python3 -m unittest scripts.test_stt_deployment -v` — exit 0;
  28 tests passed. New cases cover healthy running state, starting then
  healthy, exited, unhealthy, multiple matching containers, wrong image,
  bounded timeout, absence of Compose commands during polling, and sanitized
  `CalledProcessError` diagnostics.
- OBSERVED: `python3 -m py_compile scripts/stt_deployment.py
  scripts/test_stt_deployment.py` — exit 0.
- OBSERVED: `git diff --check` — exit 0.
- OBSERVED: executed the original read-only readiness probe:
  `docker compose --env-file /dev/null -f deployments/compose/compose.yaml -f deployments/compose/compose.stt-cuda.yaml --profile cuda ps --all --quiet stt`
  — exit 1. Captured output was classified in memory as a Compose
  configuration/environment error; raw stderr was not printed or recorded.
  This confirms the suspected failure mode. The command failed during Compose
  configuration parsing and did not issue a lifecycle operation.
- OBSERVED: `python3 -m ruff check scripts/stt_deployment.py
  scripts/test_stt_deployment.py` — unavailable; system Python has no Ruff
  module. No dependency installation was attempted.

## Experimental CUDA STT deployment acceptance — 2026-10-19

Provenance: the following target-host results were supplied by the user as
verified real-host acceptance evidence. They are recorded as **OBSERVED,
user-reported**; no corresponding target command was run from this workspace.
This evidence establishes the bounded experimental deployment acceptance
listed here, while the parallel inference stress scope remains open.

- OBSERVED, user-reported: release `v0.1.2`, STT service, experimental profile;
  image digest
  `sha256:31440127a13a1892f07fe480f013f1185c2d978ee981b5ce56fcd4a09a702ad8`;
  model `large-v3-turbo`, pinned revision
  `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`.
- OBSERVED, user-reported: `make plan SERVICE=stt PROFILE=experimental` —
  READY; `make install SERVICE=stt PROFILE=experimental` — PASS; readiness
  check — PASS.
- OBSERVED, user-reported: real transcription returned HTTP 200 with
  `language=en` in 1.399 seconds.
- OBSERVED, user-reported: both original and experimental STT remained
  healthy. GPU memory after inference was 4,428 MiB used and 10,482 MiB free.
- OBSERVED, user-reported idempotency comparison before and after repeated
  install: container ID
  `bf7e4255aecf77bbe84a5f1e048849d645514b38f0aa7a2bb9dcea4276cc52f7`;
  `Created=2026-10-18T22:59:04.90174038Z`;
  `StartedAt=2026-10-18T23:11:03.948795311Z`;
  image ID
  `sha256:31440127a13a1892f07fe480f013f1185c2d978ee981b5ce56fcd4a09a702ad8`;
  health `healthy`. The original STT remained running and healthy.
- INTERPRETATION: matching ID, creation/start times and image ID with healthy
  status before and after the repeated install support idempotent reuse of
  this matching experimental container. These measurements do not establish
  behavior for mismatched resources or other target states beyond the existing
  deterministic tests.
- INTERPRETATION: the approved experimental GPU admission threshold is
  4,096 MiB free before model load. The regular profile threshold remains
  14,336 MiB. These are distinct profile settings; the successful experimental
  admission does not override or validate regular-profile admission.
- NOT ESTABLISHED: parallel inference stress testing was not performed.
  Sustained throughput/latency under concurrent requests, peak or
  process-attributed GPU memory, and safe headroom during parallel inference
  remain unverified. This gap keeps the full agreed M01E acceptance and
  milestone closeout open. M01F has not started.
- No new container command was run from this workspace for this documentation
  update. No running container was restarted, stopped, or recreated.

## Documentation update verification — 2026-10-19

- OBSERVED: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m unittest scripts.test_stt_deployment scripts.test_stt_deployment_profile scripts.test_model_artifacts -q` — exit 0; 91 tests passed.
- OBSERVED: `make compose-check PYTHON=python3` — exit 0; base, CPU, CUDA build and static CUDA Compose render checks passed. No lifecycle operation was invoked.
- OBSERVED: `make release-check PYTHON=python3` — exit 0; v0.1.2 release descriptor passed for three services on `linux/amd64`.
- OBSERVED: relative Markdown link check over `PLANS.md`, the five M01E records and `docs/operations/stt-cuda-deployment.md` — PASS; all local relative targets exist. `git diff --check` — exit 0.
- BLOCKED: `make governance-check PYTHON=.venv/bin/python` — exit 2 because `.venv/bin/python` has no `yaml` module. No dependency was installed.
- BLOCKED: `make verify PYTHON=.venv/bin/python` — exit 2 in lint prerequisites because `gofmt` and Go are unavailable; Python repository tests were not reached through this target.
- NOT RUN: target-host checks were not repeated. No container lifecycle command, restart, stop or recreation was issued.

## M01E-C service selection and full local verification — 2026-10-19

- OBSERVED: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m unittest scripts.test_service_selection scripts.test_stt_deployment scripts.test_stt_deployment_profile scripts.test_model_artifacts -q` — exit 0; 100 focused tests passed. Coverage includes STT/TTS/Gateway resolution, default enabled-set selection, missing/disabled dependencies, unknown/disabled services, cycles, stable dependency order, unsupported-service no-fallback, and existing STT planning/preflight behavior.
- OBSERVED: `make plan SERVICE=bogus` — exit 2 with `unknown service: bogus`. `make plan SERVICE=tts` — exit 2 with `service is disabled: tts` from the private host config. Both stopped before STT profile validation and Docker inspection. No files or containers were changed by these commands.
- OBSERVED: when enabled, TTS and Gateway are intentionally reported as `BLOCKED: NOT IMPLEMENTED` by the resolver dispatch test. Example resolved plan lines using the current release graph:

  ```text
  SERVICE=stt:     PLAN: services=stt
  SERVICE=tts:     PLAN: services=tts
                   BLOCKED: NOT IMPLEMENTED for selected service(s): tts
  SERVICE=gateway: PLAN: services=gateway
                   BLOCKED: NOT IMPLEMENTED for selected service(s): gateway
  SERVICE unset:   PLAN: services=stt
  ```

  The default example reflects the ignored local enabled-services file, which
  currently contains only `stt`. Release v0.1.2 declares no dependencies for
  these three services; resolver tests exercise dependency closure and ordering
  with synthetic release metadata.
- OBSERVED: initial `make verify` with system `python3` — exit 2 because Ruff
  was unavailable in that interpreter. No package was installed. Rerun with the
  repository environment, `make verify PYTHON=.venv/bin/python` — exit 0:
  `go vet`, Ruff lint/format, application config checks, base/CPU/CUDA Compose
  checks, release validation, Go race tests, all 255 script tests, Go build,
  Python AST parsing, governance checks and STT lock checks passed. Environment:
  Python 3.12.3, Go 1.24.0, Docker Compose 5.6.0.
- OBSERVED: `make governance-check PYTHON=.venv/bin/python` — exit 0; governance
  structure/reference validation and two governance tests passed.
- OBSERVED: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m unittest discover -s scripts -p 'test_*.py' -q` — exit 0; 255 script tests passed.
- OBSERVED: `git diff --check` — exit 0.
- NOT ESTABLISHED: GitHub Actions CI for these uncommitted changes; no claim is
  made that CI passed. No install, artifact staging, target validation,
  container lifecycle operation, or service mutation was run for M01E-C.

## M01E-D local implementation verification — 2026-10-19

- OBSERVED: focused mocked service-deployment and STT regression command
  `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m unittest scripts.test_service_selection scripts.test_service_deployment_profile scripts.test_service_deployment scripts.test_stt_deployment scripts.test_model_artifacts scripts.test_stt_deployment_profile -q`
  — exit 0; 121 tests passed. Coverage includes Gateway-only and TTS-only
  selection, dependency closure, all-enabled installation, selective addition,
  healthy reuse, changed-service isolation, invalid/disabled selections,
  image/model staging and verification failures, readiness failure/deadline,
  exact-project scoping and existing CUDA STT cases.
- OBSERVED: `make governance-check PYTHON=.venv/bin/python` — exit 0;
  governance structure/reference validation passed and 2 governance tests
  passed.
- OBSERVED: the first `make verify PYTHON=.venv/bin/python` stopped at Ruff's
  format check for the edited deployment test. After applying Ruff formatting,
  the same command completed with exit 0. The successful run passed Go vet,
  Ruff lint/format, application config checks, base/CPU/CUDA Compose checks,
  release validation, Go race tests, 276 script tests, 61 STT tests, Go build,
  Python AST parsing, governance checks and STT lock checks.
- OBSERVED: no target deployment plan or install was run for M01E-D. Tests use
  mocks and isolated temporary fixtures. No image was pulled, model was
  downloaded, or container lifecycle operation was issued.
- NOT ESTABLISHED: target Compose/Engine behavior for the expanded shared
  project, target-specific private service configuration, Gateway/TTS host
  readiness, multi-service selective-add behavior on the real host, and
  coexistence under parallel inference load. These remain M01E-E acceptance
  work; overall M01E remains OPEN.

## M01E-E real-host multi-service deployment plan — 2026-10-19

- OBSERVED: prepared ignored `private/deployment/m01e-e/` for the existing
  experimental Compose project `speech-platform-stt-cuda-m01e-exp-v012`.
  Directory mode is `0700`; enabled-services and service-profile files are
  `0600`; Gateway and TTS configs are `0640`, group `988` (`stt-model-reader`).
  The private profile enables Gateway, STT and TTS, uses loopback port 18083,
  and matches the experimental STT project's port, listen port and reader GID.
  `git check-ignore -v` confirmed all four files are ignored.
- OBSERVED: ran the real target command under the configured reader group:

  ```sh
  sg stt-model-reader -c 'make plan SERVICE= ENABLED_SERVICES_CONFIG=private/deployment/m01e-e/enabled-services.yaml SERVICES_DEPLOYMENT_CONFIG=private/deployment/m01e-e/services.yaml GATEWAY_DEPLOYMENT_CONFIG=private/deployment/m01e-e/gateway.yaml TTS_DEPLOYMENT_CONFIG=private/deployment/m01e-e/tts.yaml PROFILE=experimental PYTHON=.venv/bin/python'
  ```

  Actual output (exit 2 because Gateway and TTS images are not present locally):

  ```text
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m scripts.stt_deployment plan --service "" --enabled-services "private/deployment/m01e-e/enabled-services.yaml" --services-profile "private/deployment/m01e-e/services.yaml" --gateway-config "private/deployment/m01e-e/gateway.yaml" --tts-config "private/deployment/m01e-e/tts.yaml" --profile "private/deployment/stt-cuda-experimental/profile.yaml" --application-config "private/deployment/stt-cuda-experimental/stt-application.yaml" --deployment-config "private/deployment/stt-cuda-experimental/stt-deployment.yaml" --worker-config "private/deployment/stt-cuda-experimental/stt.yaml" --release "releases/voiceservice-v0.1.2.yaml" --env-file "private/deployment/stt-cuda-experimental/compose.env"
  PLAN: services=gateway,stt,tts
  PLAN: dependencies=none
  PLAN: compose_project=speech-platform-stt-cuda-m01e-exp-v012 gateway=127.0.0.1:18083->8080
  PLAN: service=gateway image=ghcr.io/azargarov/voiceservice-gateway@sha256:cab80ebc04bc78ec608c1f81c69ce1dfc8e048227e4892053c86783833064d30 artifact=BLOCKED action=install
  PLAN: service=stt image=ghcr.io/azargarov/voiceservice-stt-cuda@sha256:31440127a13a1892f07fe480f013f1185c2d978ee981b5ce56fcd4a09a702ad8 artifact=verified action=unchanged
  PLAN: service=tts image=ghcr.io/azargarov/voiceservice-tts-health-only@sha256:6ac1e87e1290f657dae613faf45cbcdd83239b4529b0482a4cd2d12b642739d6 artifact=BLOCKED action=install
  PLAN: gpu_free_mib=10482 admission_threshold_bytes=4294967296
  PLAN: admission=BLOCKED
  BLOCKER: gateway immutable image is missing locally; install will stage it
  BLOCKER: tts immutable image is missing locally; install will stage it
  make: *** [Makefile:110: plan] Error 2
  ```

- OBSERVED: dependency closure is empty for all three v0.1.2 services. The
  regular `make plan` default was not used; `PROFILE=experimental` selects the
  already running experimental STT configuration. STT release image and
  digest-addressed model artifact validated. Current GPU free memory was
  10,482 MiB against the experimental 4,096 MiB gate. This is point-in-time
  admission evidence only.
- OBSERVED: read-only `docker buildx imagetools inspect --raw` metadata for all
  three registry references returned raw manifest SHA-256 values matching the
  v0.1.2 descriptor: Gateway `cab80e…64d30`, STT `314401…02ad8`, and TTS
  `6ac1e8…42739d6`. This queried registry manifests; it did not fetch image
  layers or add images to the local daemon. Local Docker image inspection found
  STT present and Gateway/TTS absent.
- OBSERVED: target Docker inspection showed the operational baseline container
  `ff12dafa6bd4` running and healthy in project
  `speech-platform-stt-runtime-smoke-20261018`, bound only to
  `127.0.0.1:18081`, with zero restarts. The experimental container
  `bf7e4255aecf` was running and healthy in project
  `speech-platform-stt-cuda-m01e-exp-v012`, with no published ports and zero
  restarts. The plan's before/after Docker snapshot matched for all container
  IDs/statuses, network inventory, local image inventory, pinned model-tree
  metadata and the experimental/private deployment config bytes, modes and
  modification times (`READ_ONLY_STATE_UNCHANGED=True`).
- OBSERVED: actual rendered Compose validation reported `stt_private` and
  `tts_private` both `internal: true`; Gateway attaches to both; STT attaches
  only to `stt_private`; TTS attaches only to `tts_private`. The only published
  port is Gateway `127.0.0.1:18083 -> 8080`. `ss -ltn` showed only the
  baseline's `127.0.0.1:18081` listener among ports 18081–18084.
- INTERPRETATION: after image staging, the approved Make invocation should
  pull only the missing Gateway and TTS references by digest. The model is
  already present and verified, so no model download is expected; install will
  verify it again. The selected service order is Gateway, STT, TTS. Compose
  runs one explicit service per `up` with `--no-deps --no-build --pull never`;
  the healthy STT action is `unchanged` and is skipped. Expected changes are
  new Gateway and TTS containers plus the project's internal `tts_private`
  network; Gateway connects to existing `stt_private` and new `tts_private`.
  The operational baseline and Ollama/Dify projects are outside these
  commands.
- NOT ESTABLISHED: plan admission is not READY until the two immutable images
  are staged and re-planning verifies them locally. Current GPU headroom may
  change before installation. Gateway/TTS health, shared-service behavior
  after adding the network and containers, STT identity after actual install,
  and inference coexistence remain unverified.
- Proposed controlled install command, **not run**:

  ```sh
  sg stt-model-reader -c 'make install SERVICE= ENABLED_SERVICES_CONFIG=private/deployment/m01e-e/enabled-services.yaml SERVICES_DEPLOYMENT_CONFIG=private/deployment/m01e-e/services.yaml GATEWAY_DEPLOYMENT_CONFIG=private/deployment/m01e-e/gateway.yaml TTS_DEPLOYMENT_CONFIG=private/deployment/m01e-e/tts.yaml PROFILE=experimental PYTHON=.venv/bin/python'
  ```

  Based on current planner actions, the only Compose lifecycle commands this
  invocation should issue are the following, in order; neither command was
  executed:

  ```sh
  docker compose --project-name speech-platform-stt-cuda-m01e-exp-v012 --env-file /dev/null -f deployments/compose/compose.yaml -f deployments/compose/compose.stt-cuda.yaml --profile cuda up -d --no-build --pull never --no-deps gateway
  docker compose --project-name speech-platform-stt-cuda-m01e-exp-v012 --env-file /dev/null -f deployments/compose/compose.yaml -f deployments/compose/compose.stt-cuda.yaml --profile cuda up -d --no-build --pull never --no-deps tts
  ```

- OBSERVED: focused M01E deployment/configuration tests passed:
  `PYTHONPATH=. .venv/bin/python -m unittest scripts.test_stt_deployment scripts.test_stt_deployment_profile scripts.test_service_selection scripts.test_service_deployment scripts.test_service_deployment_profile -v`
  — exit 0; 110 tests. `make verify PYTHON=.venv/bin/python` first reported
  Ruff formatting in the changed test; after `.venv/bin/python -m ruff format
  scripts/test_stt_deployment.py`, rerun completed exit 0, including Go vet,
  Ruff, config and Compose checks, release validation, Go race tests, script
  and STT tests, build, governance and lock checks. `git diff --check` — exit
  0.
- NOT RUN: `make install`, Docker image pull, model download, network/container
  create or update, container restart, or any shared-service operation. M01E
  remains OPEN pending image staging, a READY re-plan, controlled real-host
  installation, user validation and explicit closeout.

## M01E-E — Gateway health and host port verification

- OBSERVED, 2026-10-19, local target Docker Engine 29.1.3 / Compose 5.6.0:
  read-only `docker inspect` of the active M01E-E Gateway showed
  `Config.Healthcheck=null`, no `State.Health`, Entrypoint `/gateway`, and the
  v0.1.2 digest image `ghcr.io/azargarov/voiceservice-gateway@sha256:cab80e…`.
  `docker image inspect` showed a Distroless image with `/gateway` entrypoint
  and no healthcheck metadata. The source exposes `/healthz` and `/readyz`;
  `/readyz` is 503 for the current foundation behavior. No shell/curl/wget or
  healthcheck command is present in the image definition; no container exec
  or image mutation was used to investigate it.
- OBSERVED: the same container had `HostConfig.PortBindings["8080/tcp"]` set
  to loopback port 18083, while `NetworkSettings.Ports["8080/tcp"]` was null.
  `docker port` returned no mapping, `ss -ltnp` showed no listener on 18083,
  and a read-only Python GET to `/healthz` at that port failed with connection
  refused. Its network was `stt_private`, an internal bridge. No container or
  network state was changed.
- INTERPRETATION: internal bridge topology caused Docker Engine to retain the
  requested HostConfig mapping without realizing publication. A dedicated
  Gateway-only non-internal bridge with IP masquerading disabled is the
  proposed correction; see [ADR 0013](../../adr/0013-gateway-port-publication.md).
  This is a target-reported Engine observation plus Docker/Moby documentation,
  not a post-fix runtime verification.
- OBSERVED: `python3 -m unittest scripts.test_service_deployment
  scripts.test_compose scripts.test_service_deployment_profile
  scripts.test_stt_deployment -q` — exit 0; 64 tests passed. Coverage includes
  missing actual host publication, unhealthy state, timeout with missing
  image healthcheck, and successful host readiness without Docker health.
- OBSERVED: `make compose-check PYTHON=.venv/bin/python` — exit 0; base, CPU,
  CUDA build and static CUDA Compose configurations rendered and passed checks.
- OBSERVED: `make verify PYTHON=.venv/bin/python` — exit 0 after formatting the
  touched Python files. Go vet, Ruff lint/format, application config checks,
  Compose checks, release validation, Go race tests, Python tests, build,
  governance and STT lock checks all passed. The first system-Python attempt
  stopped because Ruff was unavailable; the first venv attempt reported
  formatting and a stale acceptance assertion, both corrected before the
  passing rerun.
- OBSERVED: `git diff --check` — exit 0.
- NOT ESTABLISHED: the new network's realized host publication, loopback
  reachability, effective egress restriction, or service coexistence after
  deployment. No install, container/network lifecycle operation, image build,
  image publish, TTS deployment, or shared-service operation was performed.

## M01E-E — Compose topology validator alignment — 2026-10-19

- OBSERVED: aligned the STT rendered-Compose validator and shared Compose
  checker with the approved `gateway_publish`, `stt_private`, and `tts_private`
  topology. Coverage rejects missing/extra network definitions or attachments,
  invalid publication bridge settings, worker port exposure, and non-loopback
  Gateway publication. Existing GPU, image, model, mount, resource, and
  provenance checks remain in the STT profile validator.
- OBSERVED: the initial repeated plan was blocked because the existing Gateway
  container still had its old private-only attachment. The planner now treats
  that approved old Gateway attachment as a replacement condition while
  continuing to reject worker network mismatches and unknown networks.
- OBSERVED: focused checks
  `.venv/bin/python -m unittest scripts.test_service_deployment
  scripts.test_stt_deployment scripts.test_stt_deployment_profile
  scripts.test_compose -q` — exit 0; 113 tests.
- OBSERVED: `make compose-check PYTHON=.venv/bin/python` — exit 0.
- OBSERVED: `make verify PYTHON=.venv/bin/python` — exit 0; Ruff, config and
  Compose checks, release validation, Go race tests, Python tests, build,
  governance, and STT lock checks passed.
- OBSERVED: read-only repeated plan command:
  `sg stt-model-reader -c 'make plan SERVICE= ENABLED_SERVICES_CONFIG=private/deployment/m01e-e/enabled-services.yaml SERVICES_DEPLOYMENT_CONFIG=private/deployment/m01e-e/services.yaml GATEWAY_DEPLOYMENT_CONFIG=private/deployment/m01e-e/gateway.yaml TTS_DEPLOYMENT_CONFIG=private/deployment/m01e-e/tts.yaml PROFILE=experimental PYTHON=.venv/bin/python'`
  — exit 0. Gateway action `replace`; STT `unchanged`; TTS `install`;
  admission `READY`. GPU free memory was 10,482 MiB against the 4,096 MiB
  experimental threshold at plan time.
- NOT ESTABLISHED: Gateway replacement, TTS installation, created network
  state, realized Gateway publication, and service health after installation.
  No installation, container/network change, image build, commit, or push was
  performed.

## M01E-E — TTS configuration access and diagnostics — 2026-10-19

- OBSERVED: the host TTS config `private/deployment/m01e-e/tts.yaml` is owned
  by UID 1000 and GID 988 with mode `0640`. The supplied real-host evidence
  reports TTS runtime UID:GID `65532:65532`, no Compose `group_add`, and
  `PermissionError` opening `/config/tts.yaml`. The release digest matched
  v0.1.2. Therefore the reader group had no access inside the container; the
  individually bind-mounted file does not require traversal through its host
  parent directories.
- OBSERVED: TTS receives `SERVICE_CONFIG_READER_GID` as a supplementary group;
  private file policy remains group-readable only, the process remains
  `65532:65532`, and TTS remains on `tts_private` without published ports.
  Preflight checks file readability before Docker inspection or creation.
  Rendered Compose and deployment validators reject a missing/wrong group.
  Readiness reports exited state and exit code before runtime drift, while
  running containers retain strict image, group, mounts, resources, networks,
  port and per-config hash checks.
- OBSERVED: focused command
  `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m unittest
  scripts.test_compose scripts.test_stt_deployment
  scripts.test_stt_deployment_profile scripts.test_service_deployment -q` —
  exit 0; 120 tests passed. Coverage includes allowed/denied config access,
  private parent semantics, missing group, incorrect mount, exited state and
  genuine runtime/config hash mismatch.
- OBSERVED: `make compose-check PYTHON=.venv/bin/python` — exit 0.
- OBSERVED: `make verify PYTHON=.venv/bin/python` — exit 0; Ruff, application
  config, Compose, release, Go race tests, Python tests, build, governance and
  STT lock checks passed.
- OBSERVED: `git diff --check` — exit 0.
- OBSERVED: final read-only all-enabled plan command, run as the configured
  `stt-model-reader` group:

  ```sh
  sg stt-model-reader -c 'make plan SERVICE= ENABLED_SERVICES_CONFIG=private/deployment/m01e-e/enabled-services.yaml SERVICES_DEPLOYMENT_CONFIG=private/deployment/m01e-e/services.yaml GATEWAY_DEPLOYMENT_CONFIG=private/deployment/m01e-e/gateway.yaml TTS_DEPLOYMENT_CONFIG=private/deployment/m01e-e/tts.yaml PROFILE=experimental PYTHON=.venv/bin/python'
  ```

  Result: Gateway `unchanged`; STT `unchanged`; TTS `replace`; GPU admission
  `READY` (10,482 MiB free against the 4,096 MiB experimental threshold).
  The plan reported the release-pinned images and verified artifacts. It ran
  after all implementation changes and was read-only.
- NOT ESTABLISHED: TTS replacement, health/readiness after replacement, or
  post-change HTTP behavior. No install, restart, stop, recreate, model change,
  commit or push was performed.

## Final acceptance review — 2026-10-19

This review used read-only Docker, network, socket and HTTP inspection on the
existing target plus the explicitly requested local checks. It did not invoke
`make install` or mutate containers, networks, firewall, images or models.

### Current host state

- OBSERVED: `docker inspect` returned Gateway ID
  `efc4aef7b7ada5422ce6c5e0ce0d44ecc178bf37e0b584f09b10da8858c533c0`,
  StartedAt `2026-10-19T19:48:03.614960334Z`, running; CUDA STT ID
  `bf7e4255aecf77bbe84a5f1e048849d645514b38f0aa7a2bb9dcea4276cc52f7`,
  StartedAt `2026-10-18T23:11:03.948795311Z`, running/healthy; and TTS ID
  `cbe5adcb28832d900c883763e1d32fa6453b432dec6de15b2a572eb1ad1130a0`,
  StartedAt `2026-10-19T19:58:24.542931694Z`, running. All match the supplied
  pre-install identities exactly.
- OBSERVED: `GET http://127.0.0.1:18083/healthz` returned HTTP 200 with
  `{"status":"alive"}`. `/readyz` returned HTTP 503; this health-only
  Gateway foundation does not currently pass readiness. The user acceptance
  request required `/healthz` and the deployment CLI's host health check.
- OBSERVED: direct read-only GET to TTS container address
  `172.23.0.3:8082/healthz` returned HTTP 200 with `{"status":"alive"}`.
  STT's Docker health state is `healthy`; the original baseline's
  `127.0.0.1:18081/healthz` returned HTTP 200.

### Network isolation and coexistence

- OBSERVED: Gateway attaches to `gateway_publish`, `stt_private`, and
  `tts_private`; CUDA STT attaches only to `stt_private`; TTS attaches only to
  `tts_private`. Both worker networks report `Internal=true`. No STT/TTS host
  port bindings are present. Gateway's only binding is
  `127.0.0.1:18083 -> 8080/tcp`; inspected port data and host listener agree.
- OBSERVED: `gateway_publish` is a Docker bridge with `Internal=false`, IPv6
  disabled, and `com.docker.network.bridge.enable_ip_masquerade=false`.
  INTERPRETATION: disabling bridge masquerading removes the usual Docker
  source-NAT path for that bridge; it does not prove egress isolation. Host
  routes, forwarding/firewall policy, direct routing and other host networking
  paths may still permit access. `iptables -t nat -S` could not read rules
  (`Permission denied`); firewall rules and effective egress were therefore
  NOT ESTABLISHED. No network or firewall change was attempted.
- OBSERVED: original operational baseline
  `ff12dafa6bd45de664e58928acf427ebd40ba876983ea2b046bbd495a464d996`
  remained running/healthy with zero restarts, its original
  `127.0.0.1:18081` binding and recorded start time
  `2026-10-18T17:35:13.123050511Z`. This is an unchanged current-state
  observation against the prior deployment record; no baseline project was
  operated.
- OBSERVED: Ollama container
  `72d0ee33e0e6ff0adeb04a6a53c6d35dde5325ed3ac1b632967ba035a764a1ba` is
  running (`Up 2 days`) and publishes `0.0.0.0:11434` plus `[::]:11434`.
  Docker reports no health state; health is not established. Dify project
  inspection showed its API, web, workers, nginx, plugin daemon, Qdrant and
  SSRF proxy running; API, Redis, PostgreSQL and sandbox report healthy;
  `init_permissions` is exited with code 0 from four months ago. These are
  actual per-container states, not a claim that the whole project is healthy.
  No shared service was changed.

### Acceptance matrix

Statuses below apply to canonical M01E acceptance in
`docs/architecture/platform-redesign.md`. "Local" means implementation and
mocked tests; target claims are separately marked as current inspection or
user-reported deployment evidence.

| Requirement | Status | Evidence and limits |
| --- | --- | --- |
| Read-only planning validates host, release, image, model, config, resources, networks and exact changes | PASS | Local validation and prior read-only target plan recorded above; plan does not install. |
| No service selects all enabled; explicit service selects declared dependency closure; invalid selections fail before side effects | PASS | Local resolver/deployment tests, including all-enabled and invalid/disabled cases. Real host all-enabled installation is user-reported. |
| Selected-service installation and dependency handling | PASS | Mocked tests cover dependency closure/order and exact project/service scope. Controlled host all-enabled deployment is user-reported; v0.1.2 declares no dependencies. |
| Immutable image validation and missing-image staging | PASS | Mocked tests verify exact digest pull then local identity/provenance. Controlled all-enabled installation passed per user report; exact per-image pull transcript was not preserved in this record. |
| Model artifact verification and missing-model staging | NOT TESTED | Existing cached model was validated/reused. Mocked tests cover staging/failure. Empty-cache target staging was not rehearsed. |
| Selective addition while retaining healthy existing services | PASS | Mocked selective-add tests and target state show pre-existing STT retained while Gateway/TTS were added. User reports successful all-enabled install; current identities match. |
| Post-install health verification; liveness distinct from readiness | PASS | Local mocked tests plus current Gateway `/healthz` 200, CUDA STT healthy, and TTS private `/healthz` 200. Gateway `/readyz` remains 503 by current foundation behavior. |
| Repeated installation is idempotent | PASS | User-reported repeated-install comparison; current Gateway, STT and TTS IDs/start times match supplied expected values. |
| Service isolation and port policy | PASS | Current Docker network membership and bindings match requirements; actual egress isolation is not claimed. |
| Isolated fresh installation from no VoiceService project/state | NOT TESTED | Current deployment reused the existing experimental STT project, model cache and configuration. |
| Original STT baseline preserved; Ollama/Dify non-interference | PASS | Current read-only inspection shows baseline healthy/unchanged; Ollama and Dify status captured above. No shared service was modified. |
| Real CUDA inference and resource behavior | PASS | Prior user-reported real HTTP 200 transcription and resource observation are recorded in experimental deployment evidence. This does not establish concurrency behavior. |
| Parallel inference/coexistence stress | NOT TESTED | No parallel-load run is recorded. |
| Full user validation and explicit milestone closeout | BLOCKED | Reviewer feedback and explicit closeout decision remain pending in `user-validation.md`. |

### Evidence classes and remaining limits

- OBSERVED local implementation: selected-service resolution, dependency
  handling, immutable artifact checks, selective addition, health gates,
  idempotency and isolation behavior have deterministic mocked test coverage.
- OBSERVED real host, this review: service identity/times, endpoint status,
  actual network attachment, port bindings, baseline status and shared-service
  container states above.
- OBSERVED user-reported real host: successful all-enabled installation,
  real CUDA transcription, and repeated-install outcome recorded in the
  experimental deployment evidence. This review did not rerun inference or
  installation.
- NOT ESTABLISHED: fresh-install rehearsal with no project/state; clean-target
  model staging/download and promotion; exact image-pull/staging transcript;
  parallel inference stress and effective Gateway egress policy.

### Requested local verification

- OBSERVED: `make governance-check PYTHON=.venv/bin/python` — exit 0; structural
  governance validation passed and 2 governance tests passed.
- OBSERVED: `make verify PYTHON=.venv/bin/python` — exit 0; Go vet, Ruff lint
  and format checks, application config checks, base/CPU/CUDA Compose checks,
  immutable release validation, Go race tests, 291 script tests, 61 STT tests,
  Go build, Python AST parsing, governance checks and STT lock checks passed.
- OBSERVED: `git diff --check` — exit 0.
- OBSERVED: `git ls-files private` returned no tracked private paths. `git
  check-ignore -v` confirmed M01E private configuration inputs are covered by
  the root `/private/` ignore rule. Private configs, audio and model files
  remain under ignored `private/`; their contents were not printed or added.
- OBSERVED: no commit or push was made.

### Review conclusion

M01E-E controlled all-enabled deployment is accepted for its observed scope,
and current service identity/network checks pass. Overall M01E remains OPEN
because canonical acceptance explicitly requires an isolated fresh-install
rehearsal, clean artifact-staging evidence and user validation/closeout;
parallel stress also remains unperformed. Do not start M01F.

## M01E-F — isolated rehearsal preparation — 2026-10-19

### Configuration and project isolation

- OBSERVED: created nine independent files under ignored
  `private/deployment/m01e-fresh-v012/`: enablement, service profile, Gateway,
  TTS, STT worker, STT application, STT deployment, CUDA deployment profile,
  and generated Compose environment. `git check-ignore -v` resolved the files
  to the root `/private/` ignore rule. Profile/service selector are `0600`,
  worker-facing configs are `0640` with GID 988, and the containing directory
  is `0700`.
- OBSERVED: private config validation passed with Gateway, STT worker,
  CUDA application/deployment and TTS check-config commands. The direct CUDA
  profile validation used `verify_files=False` because the required model is
  intentionally absent; it validates schemas, values, release-pinned image
  identity and deployment settings but does not verify model files or model
  path permissions.
- OBSERVED: the model store
  `/var/tmp/speech-platform-m01e-fresh-v012/model-store` is empty. Its parent
  and root are `1000:988`, mode `2750`, with no digest release child. `/var/tmp`
  was chosen because the CUDA worker cannot traverse `/home/master` and the
  repository path to a model store under `private/`; host-managed temporary
  storage retention is a limitation to recheck before any later staging.
  Existing `/srv/speech-platform/models` was not changed.
- OBSERVED: exact-project read-only inventory returned no containers and no
  networks with Compose project label
  `speech-platform-m01e-fresh-v012`.
- OBSERVED: read-only plan command, run under `stt-model-reader` with explicit
  `STT_DEPLOYMENT_DIR=private/deployment/m01e-fresh-v012`, rendered and
  validated project `speech-platform-m01e-fresh-v012`, Gateway
  `127.0.0.1:18084 -> 8080`, and all three immutable v0.1.2 service images.
  It reported Gateway/STT/TTS action `install`, GPU free memory 10,482 MiB,
  and `admission=BLOCKED` with reason `required model artifacts are missing;
  install will stage pinned files`. Make returned exit 2 because this expected
  blocker remains. No project containers or networks were created.
- OBSERVED: the first plan invocation omitted `STT_DEPLOYMENT_DIR` and selected
  the existing experimental config path; private permission validation rejected
  it before Docker inspection. The corrected invocation explicitly selects
  the fresh profile and is recorded in
  [the rehearsal procedure](../../operations/m01e-fresh-install-rehearsal.md).

### Provisioning and cleanup design

- OBSERVED: release v0.1.2 pins
  `dropbox-dash/faster-whisper-large-v3-turbo` revision
  `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`, manifest SHA256
  `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`,
  five files, 1,621,665,983 bytes total. The exact future provisioner API
  command uses the empty independent store, owner UID 1000, primary reader GID
  988, setgid directory mode `2750`, file mode `0640`, pinned HTTPS source,
  manifest size/SHA256 verification, atomic digest-directory activation, and
  verified reuse. See the runbook. It was not executed.
- OBSERVED: cleanup design inventories the exact Compose project label,
  container labels and service membership, network IDs/labels/attachments, and
  exact model path/ownership/content before cleanup approval. It uses exact
  reviewed container/network IDs and the dedicated model digest path. No
  cleanup or destructive operation was executed.
- NOT RUN: artifact download, `make model-fetch`, image pull, Compose install,
  container/network creation or lifecycle, model-store mutation, or cleanup.

### GPU resource review

- OBSERVED, read-only host commands on 2026-10-19: Quadro RTX 5000 UUID
  `GPU-8087d1a4-299e-cf92-471b-f96acbdf7d6a`, 15,360 MiB total, 4,428 MiB
  used, 10,482 MiB free. `nvidia-smi --query-compute-apps` showed two Python
  CUDA processes at 2,212 MiB each. `docker top` maps them to the existing
  M01E experimental STT worker and the original STT runtime-smoke container.
  `docker stats` showed 416.4 MiB container RAM for the experimental worker and
  535.5 MiB for runtime-smoke; these are host RAM measurements, not GPU memory.
- OBSERVED historical measurement: `releases/stt-cuda-baseline-001.yaml`
  records one STT process at 2,212 MiB GPU memory and 12,694 MiB free after
  inference; it explicitly classifies those values as point-in-time, not peak.
  The current two-process observation is consistent with roughly 2.2 GiB per
  worker. INTERPRETATION: a third worker with similar use would leave about
  8,270 MiB free from the current 10,482 MiB, around 4,174 MiB above the
  configured 4,096 MiB pre-load threshold. The measured headroom is enough to
  consider one controlled, bounded test after a fresh preflight and separate
  approval; it is not a guarantee or capacity reservation.
- NOT ESTABLISHED: workload peak VRAM, third-worker worst-case use, GPU memory
  behavior under simultaneous inference, or a bound from the 12 GiB container
  RAM limit. That RAM limit does not cap VRAM. No third worker was launched.

### Local verification

- OBSERVED: fresh private config checks passed for Gateway, TTS, STT worker and
  CUDA application/deployment. A direct private service/profile identity
  validation passed; full artifact verification remains deferred until staging.
- OBSERVED: focused command
  `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m unittest
  scripts.test_model_artifacts scripts.test_stt_deployment
  scripts.test_stt_deployment_profile scripts.test_service_selection
  scripts.test_service_deployment scripts.test_service_deployment_profile
  scripts.test_compose -q` — exit 0; 148 tests.
- OBSERVED: new planner regression
  `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m unittest
  scripts.test_stt_deployment.DeploymentOrchestrationTests.test_plan_reports_missing_model_as_a_blocker -v`
  — exit 0.
- OBSERVED: initial `make verify PYTHON=.venv/bin/python` stopped at Ruff
  formatting (exit 2) for the newly edited test. Formatted that file and reran
  the full command; final exit 0. Go vet, Ruff check/format, application and
  Compose validation, immutable release validation, Go race tests, 292 script
  tests, 61 STT tests, Go build, Python AST parsing, governance validation and
  STT lock checks all passed.
- NOT RUN: image pull/build/publish, artifact fetch, Compose install/start/stop,
  user validation, cleanup, commit or push.

### M01E status

M01E remains OPEN. Preparation is complete, but the plan is blocked by the
intentionally empty model store. Artifact staging and a later READY plan must
precede a separately approved isolated installation rehearsal. Parallel
inference stress testing is not an acceptance blocker under the approved
M01E-F design. Full user validation and explicit closeout approval remain
pending.

## M01E-F1 — clean model staging preflight — 2026-10-19

**Outcome: BLOCKED before download.** The user authorized the clean model
artifact staging rehearsal only. The mandatory operational-store unchanged
preflight could not be established, so provisioning and all subsequent
acceptance checks were not run. No Docker operation was required or issued.

### Preflight evidence

- OBSERVED: `readlink -f --
  /var/tmp/speech-platform-m01e-fresh-v012/model-store` returned the exact
  approved path. `stat -c '%u:%g %a %n'` on the parent and store reported
  `1000:988 2750` for both. `find .../model-store -mindepth 1 -maxdepth 1
  -print` returned no entries; target store was empty.
- OBSERVED: `df -Pk` on the target reported filesystem `/dev/mapper/ubuntu--vg-ubuntu--lv`,
  83,225,716 KiB available (72% used), well above the manifest's 1,621,665,983
  byte payload. No filesystem reservation was made.
- OBSERVED: `stat` identified the existing operational store at
  `/srv/speech-platform/models`, UID:GID `0:988`, mode `2710`; it is a distinct
  absolute path from the target. Listing it as `master` and under
  `stt-model-reader` could not read directory contents. `sudo -n` reported
  `sudo: a password is required`. Therefore a before/after inventory proving
  that operational-store contents stayed unchanged is NOT ESTABLISHED. No
  operation was performed against that store.
- OBSERVED: `load_release('releases/voiceservice-v0.1.2.yaml',
  REPOSITORY_ROOT)` and `load_artifact_manifest` with the pinned digest
  validated the descriptor/manifest. Release source revision is
  `bbbeb697c1ae840e084e962fac39db0c19ab7728`; model repository is
  `dropbox-dash/faster-whisper-large-v3-turbo`, revision
  `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`, manifest
  `releases/artifacts/stt-large-v3-turbo.yaml`, SHA256
  `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`.
  It specifies five files, 1,621,665,983 bytes total:
  `config.json` 2,263 bytes SHA256
  `b0253ea6c0d3bea6b1e19e91a02acfd3b53f4467362efcb5a3e6b16c9b3a9b7e`;
  `model.bin` 1,617,884,929 bytes SHA256
  `e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da`;
  `preprocessor_config.json` 340 bytes SHA256
  `7ccc62c6f2765af1f3b46c00c9b5894426835a05021c8b9c01eecb6dfb542711`;
  `tokenizer.json` 2,710,337 bytes SHA256
  `297b13372ac43916285644fb9687add3cc62ee2a1adb60da3dc25cc94c1871fd`;
  `vocabulary.json` 1,068,114 bytes SHA256
  `c69260f2ab26d659b7c398f9a2b2b48ed0df16c3b47d7326782fd9cba71690c1`.
- INTERPRETATION: staging uses the existing Python content-addressed
  provisioner and local filesystem operations; the runbook command does not
  invoke Docker. No Docker command was issued during this attempt.

### Execution and acceptance status

- NOT RUN: provisioner/download command, per-file downloaded-content hash
  verification, atomic activation, permission-policy audit, temporary-stage
  audit, intended container-identity read test, repeat/reuse invocation,
  operational-store after-inventory, and post-staging fresh-project plan.
- OBSERVED: no model-store mutation was performed during this attempt. The
  store was empty at preflight and no staging/release directory was created by
  this attempt. Download-versus-reuse is not applicable; no download occurred.
- NOT ESTABLISHED: operational model-store unchanged evidence and new fresh-
  project plan admission state. The earlier preparation plan remains the last
  plan evidence: blocked on the missing model, as recorded above.

The runbook preflight requires a readable operational-store before/after
inventory. Resume this authorized staging rehearsal only after a read-only
means to inventory `/srv/speech-platform/models` is available and confirms its
current state; then repeat the complete preflight before downloading.

### F1 recheck by the authorized rehearsal operator — 2026-10-19

- OBSERVED: from `/home/master/speech-platform`, `id` reported UID 1000,
  primary GID 1000 and supplementary groups including GID 988. The exact
  preflight command batch was:

  ```sh
  stat -c '%u:%g %a %n' /var/tmp/speech-platform-m01e-fresh-v012 /var/tmp/speech-platform-m01e-fresh-v012/model-store
  readlink -f /var/tmp/speech-platform-m01e-fresh-v012/model-store
  find /var/tmp/speech-platform-m01e-fresh-v012/model-store -mindepth 1 -maxdepth 1 -print
  df -B1 /var/tmp/speech-platform-m01e-fresh-v012/model-store
  stat -c '%u:%g %a %n' /srv/speech-platform/models
  find /srv/speech-platform/models -mindepth 1 -maxdepth 1 -printf '%f\\n'
  ```

- OBSERVED: target and parent both reported `1000:988 2750`; `readlink -f`
  returned `/var/tmp/speech-platform-m01e-fresh-v012/model-store`; `find`
  returned no entries. `df -B1` reported 85,221,548,032 bytes available on
  `/dev/mapper/ubuntu--vg-ubuntu--lv` (72% used), enough for the manifest's
  1,621,665,983 bytes plus staging overhead.
- OBSERVED: operational store `stat` reported `0:988 2710`, confirming its
  path is separate. Its directory listing failed with `Permission denied`.
  `sudo -n stat -c '%u:%g %a %n' /srv/speech-platform/models` exited 1 with
  `sudo: a password is required`. Thus operational-store contents and
  unchanged status remain NOT ESTABLISHED; mandatory preflight failed and
  execution stopped before download.
- OBSERVED: `sha256sum releases/artifacts/stt-large-v3-turbo.yaml` returned
  `423411b48c216a5d921b6b97a762dc7341c945dc31de036904c39ff74ce81b96`.
  `load_release('releases/voiceservice-v0.1.2.yaml', REPOSITORY_ROOT)`
  succeeded and reported release source revision
  `bbbeb697c1ae840e084e962fac39db0c19ab7728`, model repository
  `dropbox-dash/faster-whisper-large-v3-turbo`, revision
  `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`, and manifest digest
  `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`.
  This is a local manifest-file hash observation; the release loader also
  validated the descriptor's pinned manifest digest and artifact identity.
- INTERPRETATION: the canonical staging invocation uses the local provisioner
  and HTTPS file downloads, filesystem verification and same-store atomic
  rename. It requires no Docker command or Docker daemon operation. A read-only
  `docker version --format '{{.Server.Version}}'` capability probe exited 0;
  no container, network, image or daemon state was changed.
- NOT RUN: no staging/provision command was issued. Consequently no file was
  downloaded or reused, no digest directory was activated, and no downloaded
  file hash, recursive permission audit or intended container-identity read
  test was performed. No post-stage plan was run because mandatory preflight
  failed; the prior fresh-project plan remains blocked by the missing model.

### F1 resumed clean staging rehearsal — 2026-10-19

**Outcome: PASS for model download, local verification, activation, reuse and
read-only plan. Worker-identity readability and operational-store metadata
comparison are PENDING operator evidence.** The rehearsal remained limited to
the approved fresh model store. No container or network lifecycle operation
was issued.

- OBSERVED: user-provided pre-staging operational-store inventory fingerprint
  is `53de3e2c2717667991dbb0cd1f66d69bf89d5f56da1ee7af95c1edd2c861d31e`.
  Provenance is the operator's privileged, read-only `find -xdev` metadata
  inventory and SHA256 command. It covers metadata, not file contents.
- OBSERVED: repeated preflight from `/home/master/speech-platform` reported
  UID 1000, primary GID 1000, target parent and store `1000:988 2750`, exact
  target resolution `/var/tmp/speech-platform-m01e-fresh-v012/model-store`,
  and empty target. `find` found no symlinks under the rehearsal directory.
  `df -B1` showed 85,220,372,480 bytes available on
  `/dev/mapper/ubuntu--vg-ubuntu--lv`; manifest payload is 1,621,665,983
  bytes. The profile identifies project `speech-platform-m01e-fresh-v012`,
  model owner UID 1000 and reader GID 988.
- OBSERVED: `/srv/speech-platform/models` resolved separately from the target;
  `stat` reported `0:988 2710`. Under the staging identity,
  `os.access(target, W_OK)` was true and `os.access(operational_store, W_OK)`
  was false. No operation attempted to change or write the operational store.
- OBSERVED: SHA256 of `releases/voiceservice-v0.1.2.yaml` was
  `08ea79cecd719738ad8de6bfe5d1eb58ffe5b9775a14b4b91a8ee1c1675e9cf6`;
  SHA256 of `releases/artifacts/stt-large-v3-turbo.yaml` was
  `423411b48c216a5d921b6b97a762dc7341c945dc31de036904c39ff74ce81b96`.
  `load_release` validated the release and manifest identity: release source
  revision `bbbeb697c1ae840e084e962fac39db0c19ab7728`, repository
  `dropbox-dash/faster-whisper-large-v3-turbo`, immutable model revision
  `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`, manifest digest
  `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`, five
  files and 1,621,665,983 bytes total.
- OBSERVED: the provisioner ran under UID 1000 with `stt-model-reader` GID
  988, using `directory_mode=0o2750`, `file_mode=0o640`, expected owner 1000
  and expected group 988. It reported `installed: large-v3-turbo` at the
  manifest-digest directory. The provisioner verifies downloaded file sizes
  and SHA256 values against the pinned manifest before same-store atomic
  activation.
- OBSERVED: `sg stt-model-reader -c 'make model-check MODEL_STORE=...` exited
  0 and reported `verified: large-v3-turbo`. A recursive inventory showed one
  digest directory, manifest and five artifact files; files were `0640`,
  directories `2750`, all descendants `1000:988`, and no symlinks were found.
- OBSERVED: a second `provision_models` invocation used a download callback
  that raises if called. It reported `reused: large-v3-turbo`, proving the
  valid digest release was reused without download.
- OBSERVED: `stt_deployment_profile.py prepare` returned the generic
  `ValueError` rejection twice. Direct `load_and_validate`, environment
  generation and `write_env_file` succeeded. Diagnosis: the CLI's
  `require_private_config_paths` call omits reader GID 988 and rejects the
  intended `0640` group-readable private service files. This was not changed
  in this rehearsal; generated `compose.env` remained private (`0600`).
- OBSERVED: `setpriv --reuid=65532 --regid=65532 --groups=988 ...` failed with
  `setresuid failed: Operation not permitted`. No container was started to
  test access. Therefore actual file reads under UID/GID `65532:65532` with
  supplementary GID 988 are NOT ESTABLISHED by this session. The directory
  and file owner/group/mode policy is observed, but is not a substitute for
  that identity-level read test.
- OBSERVED: the read-only fresh-project `make plan` invocation from the
  runbook exited 0. It rendered project `speech-platform-m01e-fresh-v012`,
  Gateway `127.0.0.1:18084 -> 8080`, and services `gateway,stt,tts`; all three
  immutable images and the model were reported verified, selected actions
  were `install`, GPU free memory was 10,482 MiB against 4,096 MiB admission,
  and `admission=READY`.
- OBSERVED: no `make install`, Docker lifecycle operation, image pull, network
  mutation, permission/ownership change to `/srv/speech-platform/models`,
  cleanup or commit was performed.
- PENDING: post-staging operational-store metadata fingerprint comparison.
  The operator must run the same privileged read-only inventory command and
  provide its SHA256. Preservation passes only if it exactly matches the
  user-provided baseline above. No preservation pass is claimed yet.
- NOT ESTABLISHED: model readability as UID/GID `65532:65532` with supplementary
  GID 988, and operational-store metadata preservation after staging.

The first corrected preflight helper attempt exited with `KeyError` after
calling the manifest loader with an incorrect argument; it did not write
anything. The successful release validation used the provisioner's actual
`load_artifact_manifest(path, expected_sha256)` interface.

## M01E-F2 — controlled fresh installation on the real host — 2026-10-19

**Outcome: PASS for the approved one-install scope.** One canonical all-enabled
`make install` ran for the isolated `speech-platform-m01e-fresh-v012` project.
All three services became healthy/ready and all post-install checks passed.
No cleanup, rollback, retry, commit, push, or M01F work was performed. M01E
remains OPEN pending user validation and explicit closeout.

### Preflight

- OBSERVED, target host: `nvidia-smi --query-gpu=index,uuid,memory.total,memory.used,memory.free --format=csv,noheader`
  and `nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader`
  returned GPU 0 UUID `GPU-8087d1a4-299e-cf92-471b-f96acbdf7d6a`, total
  15,360 MiB, used 4,428 MiB, free 10,482 MiB, and two existing CUDA
  processes at 2,212 MiB each. Immediately before install, the same inventory
  returned the same values. The install plan reported the configured
  4,294,967,296-byte (4,096 MiB) threshold and `admission=READY`.
- OBSERVED: exact-label Docker inventories returned no containers or networks
  for `speech-platform-m01e-fresh-v012`; `ss -ltn 'sport = :18084'` returned
  no listener. The final plan and model check used the explicit fresh paths:

  ```sh
  sg stt-model-reader -c 'make model-check MODEL_STORE=/var/tmp/speech-platform-m01e-fresh-v012/model-store PLATFORM_RELEASE=releases/voiceservice-v0.1.2.yaml PYTHON=.venv/bin/python'
  sg stt-model-reader -c 'make plan SERVICE= ENABLED_SERVICES_CONFIG=private/deployment/m01e-fresh-v012/enabled-services.yaml SERVICES_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/services.yaml GATEWAY_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/gateway.yaml TTS_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/tts.yaml STT_DEPLOYMENT_DIR=private/deployment/m01e-fresh-v012 PROFILE=experimental PLATFORM_RELEASE=releases/voiceservice-v0.1.2.yaml MODEL_STORE=/var/tmp/speech-platform-m01e-fresh-v012/model-store PYTHON=.venv/bin/python'
  ```

- OBSERVED: model check reported `verified: large-v3-turbo` at digest directory
  `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`.
  `make plan` exited 0, rendered and validated the complete Compose config,
  selected exactly `gateway,stt,tts`, reported all three immutable v0.1.2
  images and model verified, project `speech-platform-m01e-fresh-v012`,
  Gateway `127.0.0.1:18084 -> 8080`, and `admission=READY`.
- OBSERVED: the private profile and rendered Compose validation specified
  worker UID/GID `65532:65532`, supplementary artifact reader GID 988 and
  read-only `/models` mount. The staged parent, store, digest directory and
  manifest were `1000:988` with expected `2750`/`0640` policy. A search of
  `private/deployment/m01e-fresh-v012/` found no references to
  `/srv/speech-platform/models` or the existing experimental project.
- OBSERVED: Docker image inspection confirmed all immutable image references,
  image IDs and `linux/amd64` platform matched release v0.1.2:
  Gateway `sha256:cab80ebc04bc78ec608c1f81c69ce1dfc8e048227e4892053c86783833064d30`;
  STT `sha256:31440127a13a1892f07fe480f013f1185c2d978ee981b5ce56fcd4a09a702ad8`;
  TTS `sha256:6ac1e87e1290f657dae613faf45cbcdd83239b4529b0482a4cd2d12b642739d6`.
- OBSERVED preservation baseline immediately before installation:

  | Service | Container ID | StartedAt (UTC) | State / health | Restarts |
  | --- | --- | --- | --- | ---: |
  | Experimental TTS | `cbe5adcb28832d900c883763e1d32fa6453b432dec6de15b2a572eb1ad1130a0` | `2026-10-19T19:58:24.542931694Z` | running; no Docker healthcheck | 0 |
  | Experimental Gateway | `efc4aef7b7ada5422ce6c5e0ce0d44ecc178bf37e0b584f09b10da8858c533c0` | `2026-10-19T19:48:03.614960334Z` | running; no Docker healthcheck | 0 |
  | Experimental STT | `bf7e4255aecf77bbe84a5f1e048849d645514b38f0aa7a2bb9dcea4276cc52f7` | `2026-10-18T23:11:03.948795311Z` | running; healthy | 0 |
  | Baseline STT runtime-smoke | `ff12dafa6bd45de664e58928acf427ebd40ba876983ea2b046bbd495a464d996` | `2026-10-18T17:35:13.123050511Z` | running; healthy | 0 |

- OBSERVED: before installation, the experimental Gateway `/healthz` returned
  HTTP 200; experimental TTS `/healthz` returned HTTP 200. Ollama
  `/api/version` returned HTTP 200 and version `0.33.1`. Dify API, Postgres,
  Redis and Sandbox were running and healthy. Other listed Dify containers
  were running without configured Docker healthchecks.

### One authorized installation

- OBSERVED: exactly one installation invocation was issued; it exited 0:

  ```sh
  sg stt-model-reader -c 'make install SERVICE= ENABLED_SERVICES_CONFIG=private/deployment/m01e-fresh-v012/enabled-services.yaml SERVICES_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/services.yaml GATEWAY_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/gateway.yaml TTS_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/tts.yaml STT_DEPLOYMENT_DIR=private/deployment/m01e-fresh-v012 PROFILE=experimental PLATFORM_RELEASE=releases/voiceservice-v0.1.2.yaml MODEL_STORE=/var/tmp/speech-platform-m01e-fresh-v012/model-store PYTHON=.venv/bin/python'
  ```

- OBSERVED: install output was `INSTALL: gateway healthy and ready`,
  `INSTALL: stt healthy and ready`, and `INSTALL: tts healthy and ready`.
  Compose was invoked with `--no-build --pull never`; no image pull/build was
  needed.

### Post-install validation

- OBSERVED: exactly three containers exist under the fresh project:

  | Service | Container ID | StartedAt (UTC) | State / health | Image identity |
  | --- | --- | --- | --- | --- |
  | Gateway | `012e68af14204da473c4f3f0e131354c8e2978983507fef621e475b945187a15` | `2026-10-19T21:25:34.172003493Z` | running | release Gateway digest above |
  | STT | `6a835c317c622a852f2c7a9760c028dd990862f8cc67acc96fbc49c6be50b303` | `2026-10-19T21:25:35.670503172Z` | running; Docker healthy | release STT digest above |
  | TTS | `33337e3f5754d54b6a87deafcf5357505c129185d34e1966f4b35a7dc8543c9d` | `2026-10-19T21:25:44.205148127Z` | running | release TTS digest above |

  All have restart count 0, expected Compose project/service labels, and exact
  release image references. Gateway `/healthz` returned HTTP 200 at
  `127.0.0.1:18084`. The realized publication is only
  `127.0.0.1:18084 -> 8080/tcp`; `ss` showed the listener bound to loopback.
  STT and TTS have no published ports.
- OBSERVED: the three labeled networks and memberships are exactly:
  `speech-platform-m01e-fresh-v012_gateway_publish` (bridge, Gateway only),
  `speech-platform-m01e-fresh-v012_stt_private` (internal, Gateway and STT),
  and `speech-platform-m01e-fresh-v012_tts_private` (internal, Gateway and
  TTS). Each network carries the expected Compose project and network labels.
- OBSERVED: fresh STT `/healthz` returned HTTP 200 `{"status":"alive"}` and
  `/readyz` returned HTTP 200 `{"status":"ready"}` at configured container
  port 8082. TTS `/healthz` returned HTTP 200 `{"status":"alive"}` at port
  8082. A direct read probe inside STT reported UID/GID `65532:65532`, groups
  `[988, 65532]`, read access to `manifest.yaml` and all five artifact files,
  and no write access. Docker inspection independently showed all four STT
  config/model mounts read-only and `group_add=[988]`.
- OBSERVED: post-install GPU inventory on the same UUID reported total 15,360
  MiB, used 6,498 MiB, free 8,412 MiB. Process usage was 2,212 MiB for each
  existing worker and 2,070 MiB for the new worker. Free memory remained
  above the 4,096 MiB configured admission threshold. INTERPRETATION: this
  point-in-time use is within the approved operational threshold; it is not a
  peak-memory guarantee.
- OBSERVED: all four existing VoiceService container IDs, StartedAt values,
  running states and zero restart counts matched the pre-install baseline;
  both existing STT workers remained healthy. Existing experimental Gateway
  `/healthz` and TTS `/healthz` both returned HTTP 200.
- OBSERVED: after installation Ollama `/api/version` still returned HTTP 200
  and `0.33.1`; Dify API, Postgres, Redis and Sandbox remained running and
  healthy. No observed Ollama or Dify regression.
- NOT ESTABLISHED: future peak GPU usage or behavior under simultaneous
  inference. No transcription or stress workload was part of this install
  rehearsal. Gateway `/readyz` was not used as an acceptance gate.
- OBSERVED limitation: an initial extra direct STT probe targeted port 8081
  and was refused. The private config specifies 8082; the corrected direct
  probes on 8082 returned health and readiness HTTP 200. No service change or
  retry of the installation occurred.
- OBSERVED: no rollback, stop, recreation, cleanup, pruning, operational model
  mutation, firewall change, commit or push was performed.

## Final idempotency validation and acceptance review — 2026-10-19

### Repeated installation

- OBSERVED: before the operation, exact-project Docker inspection recorded:

  | Service | Container ID | StartedAt (UTC) | State / health | Restarts | Image ID | Compose config hash |
  | --- | --- | --- | --- | ---: | --- | --- |
  | Gateway | `012e68af14204da473c4f3f0e131354c8e2978983507fef621e475b945187a15` | `2026-10-19T21:25:34.172003493Z` | running / no Docker healthcheck | 0 | `sha256:cab80ebc04bc78ec608c1f81c69ce1dfc8e048227e4892053c86783833064d30` | `6031ccc4b7167665eea7beb3c8ea029abba4d5999e824a0299c64735bbde64fe` |
  | STT | `6a835c317c622a852f2c7a9760c028dd990862f8cc67acc96fbc49c6be50b303` | `2026-10-19T21:25:35.670503172Z` | running / healthy | 0 | `sha256:31440127a13a1892f07fe480f013f1185c2d978ee981b5ce56fcd4a09a702ad8` | `f59627c30ff2a8c5fad2965376896dea682f1aec9a9c0bb31627d61e8a231109` |
  | TTS | `33337e3f5754d54b6a87deafcf5357505c129185d34e1966f4b35a7dc8543c9d` | `2026-10-19T21:25:44.205148127Z` | running / no Docker healthcheck | 0 | `sha256:6ac1e87e1290f657dae613faf45cbcdd83239b4529b0482a4cd2d12b642739d6` | `5852729ea6264290d3b13e0acaa150ae49ac19c7af063fe3a1fa90a74d57254b` |

- OBSERVED: the explicit read-only `make plan` exited 0, selected exactly
  `gateway,stt,tts`, reported `action=unchanged` for each, and ended
  `admission=READY` (GPU free memory 8,412 MiB; configured threshold 4,096
  MiB).
- OBSERVED: one repeated `make install` using the same explicit fresh-project
  configuration exited 0 and reported `gateway unchanged and healthy`,
  `stt unchanged and healthy`, and `tts unchanged and healthy`.
- OBSERVED: post-install exact-project inspection returned the same container
  IDs, StartedAt timestamps, restart counts, immutable image IDs and Compose
  config hashes listed above. All remained running; STT remained healthy.
  Fresh Gateway `GET /healthz` returned HTTP 200. No retries were issued.
- OBSERVED: existing experimental VoiceService container IDs remained
  `efc4aef7...`, `bf7e4255...`, and `cbe5adcb...`; original STT baseline
  `ff12dafa...` remained running/healthy; Ollama `72d0ee33...` remained up
  and `/api/version` returned HTTP 200. Dify API, PostgreSQL, Redis and
  Sandbox containers remained up, with Docker reporting healthy for those
  four. Existing experimental Gateway `/healthz` at port 18083 and existing
  experimental TTS `/healthz` returned HTTP 200. An initial preservation
  probe used port 18082 and failed to connect; inspection showed the TTS
  container has no published host port. The corrected in-container endpoint
  probe returned HTTP 200. No existing service was operated or changed.
- NOT ESTABLISHED: effective Gateway egress restrictions. The publication
  bridge's disabled masquerading and internal worker networks do not establish
  host firewall behavior, forwarding policy, direct routing, or complete
  egress isolation. Parallel inference stress remains unperformed and is not
  a canonical M01E acceptance criterion.

### Canonical M01E acceptance matrix

| Criterion | Status | Evidence and limit |
| --- | --- | --- |
| Fresh installation from empty project | PASS | M01E-F2 observed isolated all-enabled install after exact project inventory showed no pre-existing containers/networks; install created exactly Gateway, STT and TTS. |
| Selective addition | PASS | Target selective-add evidence and local mocked coverage; pre-existing STT retained when other enabled services were added. |
| Dependency resolution | PASS | Local resolver/order coverage; target release declares no inter-service dependencies. |
| Immutable release verification | PASS | Release-pinned image digests and model manifest verified; F2 image identities matched the immutable release. Exact per-image pull transcript was not retained. |
| Clean model staging and reuse | PASS | F1 download/hash verification, digest activation and second-run reuse without download. |
| Correct non-root artifact access | PASS | Operator reports UID/GID `65532:65532`, supplementary GID 988, all six files readable; read-only mount separately observed. |
| Service health and readiness | PASS | Fresh install and repeat install report services healthy; STT health/readiness endpoints and Gateway/TTS health endpoints returned HTTP 200. Gateway readiness is not required for the health-only foundation. |
| Network topology and published-port policy | PASS with limitation | Gateway loopback publication only; STT/TTS unpublished; private worker networks internal. This does not prove Gateway egress is restricted. |
| Idempotent installation | PASS | This repeated install: all actions unchanged and exact IDs, starts, restart counters and runtime identities preserved. |
| Preservation of existing services | PASS | Existing VoiceService identities/endpoints, original STT, Ollama and observed Dify container states unchanged. Evidence is container/endpoint state, not workload-level Dify functional testing. |

INTERPRETATION: all canonical M01E acceptance requirements are now supported
by recorded evidence for their stated scope. Parallel inference stress and
effective Gateway egress restrictions are remaining risks/limits, not newly
introduced M01E blockers. M01E is **READY FOR USER VALIDATION AND CLOSURE**;
milestone completion itself remains pending explicit user validation and
closeout approval. No cleanup, M01F work, commit or push was performed.

### Requested repository verification and hygiene

- OBSERVED: `make governance-check PYTHON=.venv/bin/python` exited 0;
  structural governance validation passed and 2 governance tests passed.
- OBSERVED: `make verify PYTHON=.venv/bin/python` exited 0. Go vet, Ruff
  lint/format, application config checks, base/CPU/CUDA Compose validation,
  immutable release validation, Go race tests, 291 script tests, 61 STT
  tests, Go build, Python AST parsing, governance checks and STT lock checks
  passed.
- OBSERVED: `git diff --check` exited 0.
- OBSERVED: `git ls-files private` returned no paths. The fresh configuration
  files are under ignored root `private/`; `git check-ignore` confirmed the
  root `/private/` rule. The staged model store is outside the repository at
  `/var/tmp/speech-platform-m01e-fresh-v012/model-store` and remains present.
  No private file contents were emitted for this audit.
- OBSERVED: reviewed the working-tree path inventory. Existing implementation,
  config, ADR and test changes were present before this final validation; they
  were preserved. No commit or push was made. The listed repository changes
  include the intended M01E documentation updates and previously existing
  M01E work.

### Final closeout — 2026-10-19

- OBSERVED: operator reviewed the final acceptance report and explicitly
  approved M01E closure with status PASS on 2026-10-19. Canonical user
  validation and result records were updated to reflect that decision.
- OBSERVED: `make verify PYTHON=.venv/bin/python` exited 0; Go vet/build/race
  tests, Ruff checks, config/Compose/release checks, 292 script tests, 61 STT
  tests, AST parsing, governance checks and lock checks passed.
- OBSERVED: `make governance-check PYTHON=.venv/bin/python` exited 0; seven
  skill structures/references and two governance tests passed.
- OBSERVED: `git diff --check` exited 0.
- OBSERVED: final staged path review excludes root `private/`, ignored private
  configuration, host evidence, model store, credentials and generated files.
  No private configuration, secret, credential, model binary or host-specific
  artifact is included in the commit.
- OBSERVED: no running container, experimental deployment or staged model store
  was modified or removed. No push was performed. M01F remains unstarted.
