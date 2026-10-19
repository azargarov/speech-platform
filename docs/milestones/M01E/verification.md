# M01E Phase A verification

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
