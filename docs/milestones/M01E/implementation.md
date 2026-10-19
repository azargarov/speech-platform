# M01E Phase A implementation record

## M01E-F2 controlled fresh installation — 2026-10-19

Executed one operator-approved canonical `make install` with explicit private
configuration paths for all enabled services and model store
`/var/tmp/speech-platform-m01e-fresh-v012/model-store`. The isolated project
created Gateway, CUDA STT and health-only TTS containers using the immutable
v0.1.2 release. Installation and all defined post-install checks passed; exact
commands, identities, topology, GPU and preservation evidence are in
[verification.md](verification.md). No existing container was changed, and no
cleanup or milestone advancement was performed. M01E remains open pending user
validation and closeout.

## M01E-E controlled multi-service deployment outcome — 2026-10-19

The previously pending M01E-E all-enabled deployment was subsequently completed
under the controlled host procedure. The user reports successful all-enabled
installation, real CUDA inference and a successful repeated install; the
current host inspection independently confirms the running deployment and
container identity. The initial missing immutable Gateway/TTS images, Gateway
publication failure on the old private-only attachment, and TTS config reader
group failure and their fixes remain described in the later sections and
[verification.md](verification.md). The fresh-install rehearsal from an empty
VoiceService project and model staging from an empty artifact cache were not
established by this deployment, because the existing STT service and verified
model were reused. The separate M01E-F1 staging rehearsal is recorded below.
No M01F work was started.

## Design and changes

- Kept artifact ownership and permissions checks in the existing deployment
  profile validator. The operator procedure now runs it as the deployment
  account with the configured model-reader group as primary group, so private
  output remains deployment-user-owned while model verification can traverse
  the existing group-readable release. The procedure performs no permission,
  ownership, or group-membership changes.
- Limited release permission traversal to the explicitly configured manifest
  and artifact subtree. Historical sibling evidence is preserved and does not
  need to be readable or repermissioned for model reuse; the artifact verifier
  still enforces the exact manifest file set and hashes.
- Added `preflight-host`, which reuses the validated profile/configuration,
  reads the selected GPU inventory through `nvidia-smi`, checks its UUID, and
  compares current free VRAM to the configured application admission threshold.
  This is an explicit gate before a future start; application model-load
  admission remains in place as a second check.
- Relaxed the host physical GPU index validator to accept any configured
  non-negative index. The selected device remains exposed as CUDA device 0 in
  the container. No host index, path, port, project name or numeric group ID
  was added as an application constant.
- Documented use of the existing content-addressed model release, the
  independent Compose project/no-port policy, and pre-start project/GPU
  inspection. Historical model files are never passed to the provisioner's
  fetch path by this procedure.
- Added regression coverage that model cache verification leaves bytes, mode
  and modification time unchanged, and that host preflight accepts matching
  identity/headroom while rejecting UUID mismatch and insufficient VRAM.
- Added Make-driven `plan` and `install` commands backed by
  `scripts/stt_deployment.py`. Both bind the profile to the exact CUDA image,
  platform and model in the strict release manifest; verify the existing model
  through `check_models`; render and validate Compose; run GPU preflight; and
  reject project-name/resource identity conflicts. Installation only invokes
  `docker compose up -d --no-build --pull never stt` with the isolated project
  and CUDA overlay. A matching existing project is reusable; unknown or
  mismatched containers block the operation.
- Added deterministic orchestration tests for exact release binding, safe
  reuse, and project name/service/deployment-identity conflicts.

## Exclusions

No access to the target host; no target model verification; no `docker pull`,
Compose render against target values, container creation/start/stop, or service
inspection; no change to Ollama, Dify, existing STT, model files, credentials,
or M00. The target-host model check cited by the user is treated as user-reported
evidence only. M01E is not complete and requires later target validation and
user closeout.

## Phase B — Target configuration and diagnostics

- Improved schema diagnostics to identify missing and unsupported field names
  without echoing configuration values. The deployment CLI names a missing
  private input by its required file role and reports denied artifact
  traversal as a group-context requirement.
- Added deployment profile schema v2 with validated Gateway host/listen ports.
  The host binding is restricted to loopback; schema v1 profiles retain the old
  8080 default. Render validation checks the exact loopback binding and accepts
  Compose's canonical duration rendering (for example, `125s` as `2m5s`).
- Prepared the five files under ignored `private/deployment/stt-cuda/` with
  mode 0600. The profile binds the exact v0.1.2 CUDA release digest and model
  manifest, observed GPU index/UUID, reader GID 988, new Compose project and
  loopback port 18082. Application, worker and deployment values reuse the
  existing private candidate configs. No model permissions or membership
  were changed.
- `make plan SERVICE=stt` was attempted and failed at model path traversal
  under the current `master` account. The v0.1.2 image is also absent locally
  and observed GPU free memory is below the configured 14 GiB admission
  threshold. No pull, install, container start or operational project change
  was made.

## Phase A continuation — read-only plan and coexistence candidate

- Changed Compose interpolation to use the validated environment in memory
  and `/dev/null` as the explicit env-file source. `plan` no longer writes
  `compose.env`, creates directories, or invokes Compose/Docker mutation
  commands; its Make invocation disables Python bytecode writes. It reports
  release/image/model/project/bindings/conflicts and GPU
  free memory/threshold, with `READY` or `BLOCKED` and blocker reasons.
- Kept strict profile, release digest, image platform/provenance, model hash
  and model access validation before a plan can report `READY`. GPU headroom
  below the threshold is a reported blocker rather than an uncaught
  admission exception.
- `install` repeats strict validation and GPU checks independently. It probes
  GPU identity and free memory again after all read-only validation and
  immediately before Compose `up`; no generated env file is written. The
  protected operational project name is rejected before container inspection
  or mutation.
- Created ignored private profile/config copies under
  `private/deployment/stt-cuda-experimental/`: a distinct Compose project,
  loopback profile port 18083, worker port 8082, the same immutable v0.1.2
  image/model identities, configured GPU UUID/index, and supplementary reader
  GID 988. The user subsequently approved 4,294,967,296 bytes (4096 MiB) for
  this experimental profile only; the operational profile remains unchanged.
- Recorded the approved 4,096 MiB gate for the experimental profile only,
  based on the prior sampled device-wide increase of about 2,216 MiB plus
  about 1,880 MiB margin. Exact peak and per-worker attribution remain
  unavailable; the regular profile retains its 14 GiB gate.
- Documented the bounded ten-step coexistence test procedure. No test request,
  container operation, or shared-service check was executed.

## Phase A continuation — Make profile selection

- Added `PROFILE`, defaulting to `regular`, for the Make `plan` and `install`
  targets. `regular` maps to `private/deployment/stt-cuda/`; `experimental`
  maps to `private/deployment/stt-cuda-experimental/`. Each selection supplies
  its own profile, application, deployment and worker config plus its own
  compose.env path. Make rejects other profile names during parsing, before
  invoking the deployment CLI.
- Added regression tests for the default and explicit regular mapping,
  experimental planning and installation mapping, and unknown-profile
  rejection. The existing orchestration tests cover read-only planning and
  project isolation.
- Updated the deployment runbook with the selector and profile paths. No
  private profile or config file was changed for this selector work.

## M01E correction — configuration access and readiness

- Added a metadata-only preflight for the three mounted STT configuration
  files. It checks directory search and file read bits for container UID/GID
  65532:65532 plus the configured supplementary reader GID before install can
  reach Compose `up`; diagnostics name the failing access class without
  reading or printing config contents.
- Added bounded post-start readiness polling of the selected Compose project.
  Success now requires one running container with Docker health `healthy`;
  exited, dead, unhealthy, missing/ambiguous and timeout states fail the
  installation with a nonzero CLI result. The bound derives from the validated
  health start period/retry schedule and is capped at 900 seconds.
- Preserved the experimental project, its 4 GiB admission threshold, non-root
  runtime and read-only Compose mounts. No baseline, model permission, Ollama,
  Dify or container lifecycle change was made.
- The observed experimental config path currently has owner-only `0700`
  ancestor directories and `0600` files, so GID 988 cannot traverse/read them.
  Applying group ownership was attempted but the workspace filesystem denied
  `chgrp`; noninteractive sudo requires a password. Permissions therefore
  remain unchanged and the new preflight will block install until an authorized
  operator applies the minimal group access. See the retry command in the
  verification record.

## M01E correction — individual config bind mounts

- Compose mounts each of the three config source files individually at its
  `/config/...` path with `:ro`. The Compose base service runs as
  `65532:65532`; the CUDA overlay adds the configured artifact-reader GID as a
  supplementary group. The model source remains a directory bind mount.
- The config preflight now rejects symlinks in source path components, checks
  for existing directories and a regular source file, and checks file read
  bits against UID/GID `65532:65532` plus the configured reader GID. It does
  not test container traversal through host-side parents that are not mounted.
  The private-config validator allows `0640` only for the three mounted files
  when the owning GID is the configured reader GID; group-write, world access,
  broad profile permissions and broad parent permissions remain rejected.
- Regression coverage reproduces a `0700` source parent with a `0640` file
  readable through a supplementary group, rejects symlink and unreadable
  sources, and verifies invalid access fails before any Docker command.

## M01E correction — readiness after successful startup

- Replaced readiness polling through `docker compose ps` with Docker Engine
  discovery filtered by the exact Compose project and `stt` service labels.
  Readiness requires exactly one match, rechecks both labels from `docker
  inspect`, and verifies `Config.Image` equals the previously validated
  immutable image reference.
- The poll accepts only `running` plus Docker health `healthy`. It fails on
  exited/dead/removing state, unhealthy health, ambiguous discovery, identity
  mismatch, or the existing bounded deadline. Starting containers continue to
  be polled. Readiness performs no Compose configuration parsing, so the
  `/dev/null` interpolation environment is not involved after startup.
- CLI reporting for `CalledProcessError` now identifies the operation and
  exit code while omitting command arguments, environment values and stderr.
  Blocker collection uses the same sanitized diagnostic.
- The correction does not change immutable image provenance, model validation,
  GPU admission, or startup command scope.

## M01E-D — Service-scoped multi-service deployment

### Design and boundaries

- Kept `scripts.service_selection.resolve_services` as the sole owner of the
  dependency graph. The deployment command consumes its dependency-first order
  and does not encode a second graph.
- Kept release image/model identities in the validated release descriptor.
  `scripts.stt_deployment` validates selected service configuration and images,
  stages missing immutable images/model artifacts, inspects only the configured
  Compose project, and applies only selected missing or changed components.
- Added a strict private multi-service profile for the shared project name,
  config-reader GID, loopback Gateway port, Gateway/TTS resource limits and
  bounded readiness probes. Gateway and TTS config files are separate private
  inputs and bind-mounted read-only. The tracked profile is a template.
- Added identity labels for Gateway/TTS from each selected image, config bytes,
  resource settings, project reader group and the tracked Compose definition.
  A healthy service with matching immutable image, identity labels, runtime
  resources, mounts, networks and port bindings is skipped.
- Compose commands name one service at a time, use the configured project,
  `--no-deps`, `--no-build` and `--pull never`. Declared dependencies still get
  processed because the resolver returns them explicitly. There is no
  `down`, prune, rollback or general update operation.
- Gateway health is checked through its configured loopback port; health-only
  TTS is checked at its internal `/healthz` endpoint using the existing worker
  image; STT retains Docker health, the GPU UUID/free-memory admission gate,
  strict configuration identity, and artifact group-access validation.
  Gateway stays on both internal worker networks; STT and TTS stay on their
  separate internal networks with no published worker ports.

### Artifact staging and safety

- The release descriptor remains authoritative for exact image digests and
  platforms. Missing selected images are pulled by that digest and platform,
  then checked for the exact repo digest, platform, service role, runtime
  variant, source revision and nonroot identity before any container operation.
- A missing selected STT model uses the existing content-addressed provisioner
  and the release manifest. New artifacts are staged with `2750` directories
  and `0640` files only when the process owner, primary reader group and
  existing model-store parent match the private profile. Existing files are
  verified without rewrite; corrupt existing releases are never replaced.
- Staging and all validation happen before Compose `up`. A failed selection,
  config, image, model, GPU, project-identity, loopback-port or network check
  stops before container changes. Project inspection and Compose lifecycle
  commands filter/use only the configured project, preserving the operational
  STT baseline, Ollama and Dify.
- This implementation does not add STT routing to Gateway, TTS inference,
  image publication, update/rollback commands, or target-host deployment.

### Compatibility and acceptance

The existing `SERVICE=stt` selection and experimental/regular profile
validation remain available. It now shares the private service profile and
project identity with selectively installed Gateway/TTS components. Existing
operators must prepare that new profile and matching Gateway/TTS private config
files before using the expanded Make interface.

Focused mocked tests cover Gateway-only and TTS-only fresh installs, dependency
closure, all-enabled selection, selective addition, changed-service isolation,
healthy reuse, image/model staging and verification errors, readiness failure
and timeout, project scoping, invalid selections and STT regression behavior.
No target plan/install, image pull, model download, or container lifecycle
command was run for M01E-D.

## M01E-E — Gateway readiness and publication verification

- The immutable v0.1.2 Gateway image is a Distroless image with `/gateway` as
  its only executable entrypoint and no image healthcheck. Its existing
  `/healthz` endpoint is the available liveness check; `/readyz` intentionally
  remains 503 until inference routing exists. Compose cannot run an HTTP
  healthcheck inside this image without changing the image.
- Gateway readiness remains an orchestrator-side standard-library HTTP request
  to the configured host loopback port. The check now first requires Docker's
  realized `NetworkSettings.Ports` mapping and reports missing publication,
  unhealthy state, and timeout/missing image healthcheck separately.
- Docker Engine 29.1.3 inspection showed requested loopback `PortBindings`
  while actual `NetworkSettings.Ports` was null. The container was attached
  only to the two internal worker bridges. Add a dedicated `gateway_publish`
  bridge for Gateway while leaving STT and TTS on their internal networks; its
  bridge IP masquerading is disabled. See proposed [ADR 0013](../../adr/0013-gateway-port-publication.md).
- Regression tests cover an absent actual publication, unhealthy state,
  timeout with no image healthcheck, and successful HTTP readiness without a
  Docker healthcheck. No running containers were changed and no release image
  was rebuilt or published.

## M01E-E — TTS configuration access and failure diagnostics

- Root cause: the real-host TTS file was owned by `1000:988` with mode `0640`;
  the pinned release image ran as `65532:65532`, and rendered Compose supplied
  no supplementary groups. The configured reader group therefore had no
  effect in the container. The direct file bind mount does not require its host
  parent directories to be traversable by UID 65532.
- TTS now receives `SERVICE_CONFIG_READER_GID`, matching the existing Gateway
  config reader policy. The shared and deployment-specific Compose validators
  require the configured group, while private config validation continues to
  reject world-readable files and the runtime stays nonroot.
- Gateway and TTS config byte hashes now have service-specific labels. Existing
  legacy whole-Compose identity labels cannot by themselves trigger unrelated
  service replacement; new config labels and exact runtime inspection retain
  per-service drift checks.
- The existing preflight verifies file access for UID 65532 plus configured
  groups before Docker inspection or container creation. Its failure now names
  the affected service. Runtime readiness reports an exited state and exit
  code before evaluating configuration drift; running containers retain strict
  image, deployment identity, mount, group, network, port and resource checks.
- Regression coverage exercises TTS reader-group access and denial without the
  group, private-parent bind semantics, required Compose group, wrong runtime
  mount replacement, exited-container diagnostics, and live runtime drift.

## Phase B experimental deployment acceptance record

- The original permission failure was caused by the container identity
  (65532:65532 plus GID 988) being unable to read the individually mounted
  private config files. The three config files were made group-readable by
  the configured model-reader group while private parent directories remained
  restricted; the file-mount preflight now checks the actual file permissions
  without requiring the container to traverse unmounted host parents.
- The initial readiness check used `docker compose ps` with an incomplete
  Compose interpolation environment and failed during Compose configuration
  parsing. Readiness polling now discovers the exact project/service through
  Docker Engine labels, verifies the immutable configured image, and waits for
  one running, healthy container within a bounded deadline.
- User-reported target validation confirms the experimental profile now plans
  READY and installs successfully, reaches readiness, transcribes a real
  request, and remains healthy alongside the original STT. Repeated install
  preserved container identity, creation/start timestamps and image identity;
  detailed values and evidence provenance are in [verification.md](verification.md).
- This record documents the accepted experimental deployment scope. Parallel
  inference stress testing was not performed, so full M01E acceptance and
  closeout remain open.

## M01E-C — service selection and dependency resolution

- Added `scripts/service_selection.py`, a dependency-first resolver that uses
  the release descriptor's existing `dependencies` fields as its only graph.
  It validates the private enabled set, rejects unknown/disabled/missing
  dependencies and cycles, and sorts roots/dependencies for stable output.
- Added a strict version-1 enabled-services configuration schema and tracked
  example. The local ignored `private/deployment/enabled-services.yaml` enables
  STT only, matching the currently supported deployment path on this host.
- Make passes `SERVICE` and the private enablement path to the deployment CLI.
  The CLI prints the resolved set before STT preflight. Unsupported selected
  services return `BLOCKED: NOT IMPLEMENTED` before STT configuration checks or
  Docker inspection, so there is no fallback to STT.
- Preserved existing STT release/image/model/GPU/security checks and the
  regular/experimental profile mapping. Added resolver, dispatch, negative,
  deterministic-order and read-only regression coverage.
- No Gateway/TTS installation, artifact staging, target operation, container
  operation or M01F work was performed. This slice does not advance or close
  M01E.

## M01E-F — isolated rehearsal preparation — 2026-10-19

Prepared the approved fresh project `speech-platform-m01e-fresh-v012` with
loopback Gateway port `18084`, all three services enabled, and independent
ignored private Gateway, TTS, STT, CUDA application/deployment, deployment
profile and generated environment files. The profile retains the immutable
v0.1.2 image/model identities and uses a dedicated empty model store at
`/var/tmp/speech-platform-m01e-fresh-v012/model-store`, owned `1000:988` with
setgid mode `2750`. The profile points to the manifest-digest child. STT
worker access remains UID/GID `65532:65532`, supplementary GID 988 and a
read-only model mount.

The `/var/tmp` store path is necessary because the worker cannot traverse the
host home/repository path required for a model store under `private/`. It is a
separate host path from `/srv/speech-platform/models`; the existing store was
not changed. It remains host-managed temporary storage and must be confirmed
present before any later staging.

Added [the M01E-F rehearsal procedure](../../operations/m01e-fresh-install-rehearsal.md)
with the exact read-only plan, the existing provisioner API invocation for a
later approved download, the Hugging Face revision/manifest identity, owner,
reader group and file modes, and a gated exact-project cleanup design. No
artifact was fetched; the model store remains empty. No container or network
was started, stopped, or changed.

The actual empty-store plan exposed an uncaught `ModelProvisionError` that
produced a traceback instead of a normal blocked plan. Updated the plan path to
report that error as a blocker and added regression coverage. This changes
plan diagnostics only; it does not change install behavior or model staging.

## M01E-F1 resumed staging — 2026-10-19

Executed the previously approved staging procedure after the operator supplied
the read-only metadata fingerprint baseline for `/srv/speech-platform/models`.
Repeated preflight confirmed the rehearsal target remained empty with the
expected `1000:988` ownership and `2750` modes, enough disk space, no symlinks,
and a distinct operational-store path that was not writable by the staging
identity. The existing provisioner downloaded and verified the pinned
large-v3-turbo artifact, then activated its digest-named release directory
with `1000:988` ownership and `2750`/`0640` modes. `make model-check` and a
second provisioner invocation with a download-refusing callback passed. The
fresh-project read-only plan is READY.

The CLI `prepare` command rejected the expected group-readable private config
files because its path check omitted the reader GID. Direct profile validation
and environment generation succeeded, so no implementation change was made
during the rehearsal. An unprivileged attempt to assume worker UID 65532 was
denied by the host; the identity-level read probe and operational-store
post-inventory remain pending operator evidence. No containers, networks,
operational-store metadata, Ollama, Dify or existing STT deployments were
changed. Detailed commands and evidence are in [verification.md](verification.md).

## Final validation reconciliation — 2026-10-19

The operator supplied the F1 worker probe result (UID/GID `65532:65532`,
supplementary GID 988, six readable artifact files) and matching operational
store metadata fingerprint. Final F2 idempotency validation captured exact
container/runtime identities before a READY read-only plan, then performed one
repeated install; all three services were unchanged and retained their
identities. See the final verification section for command results and the
acceptance matrix. No deployment cleanup or M01F work was performed.
