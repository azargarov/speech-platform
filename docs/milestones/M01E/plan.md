# M01E — Target host integration

Status: **COMPLETE — PASS. User validation and explicit closeout approval recorded 2026-10-19.** M01F update/rollback and M01G broader target lifecycle validation remain later milestones. Parallel inference stress remains assigned to later runtime/lifecycle validation; Gateway egress isolation was not established. Inference routing is not implemented.

## Scope

Prepare deployment code and operator instructions for the manually inspected
Ubuntu host while preserving the current operational STT project, Ollama, Dify,
and the historical model release. Phase A ends before target access or install.

## Phase B — Target configuration preparation

The user authorized read-only inspection of the current `llm` host, preparation
of the five ignored private configuration files under
`private/deployment/stt-cuda/`, schema and rendered-Compose validation, and
`make plan SERVICE=stt`. This phase does not authorize installation, service
startup, image pulls, model permission or group membership changes, or changes
to the operational STT, Ollama or Dify projects. Acceptance requires a
successful plan; otherwise record exact preconditions and stop.

Responsibilities:

- `scripts/stt_deployment_profile.py` validates immutable image/config/model
  identity, group-based artifact access, project isolation and the selected
  host GPU. Its host preflight checks that GPU's configured UUID and free VRAM.
- The deployment profile and Compose overlay own host-specific paths, group
  IDs, GPU selection, project name and resource thresholds as private,
  validated configuration. CUDA Compose publishes no host port and mounts the
  artifact read-only.
- The runbook supplies the read-only execution context for a deployment user
  that cannot enumerate the model store as its normal account, then orders
  artifact validation and GPU preflight before a future separately authorized
  startup.
- Make `plan` and `install` invoke a common fail-closed orchestrator. Both
  validate the private profile, require the image and model identities to
  match the immutable CUDA release manifest, verify the cached model using
  `scripts.provision_models` logic, render and validate the isolated Compose
  project, and check GPU identity/headroom. `install` may only run `compose up`
  for that project with pulls and builds disabled; mismatched project resources
  are a hard conflict.

## Acceptance criteria

1. Verified content-addressed releases can be checked and reused without
   writing their files or metadata; missing/corrupt releases fail closed and
   fetch remains an explicit separate action.
2. A configured reader group can provide read/traverse access without changing
   historical ownership/modes. A caller lacking access is instructed to use
   the deployment account with that group context, not broaden permissions.
3. GPU preflight requires a unique configured host GPU, matching UUID and
   free VRAM at or above the validated CUDA deployment threshold.
4. New CUDA deployment uses a profile-selected Compose project, separate
   private config paths, no host-published worker port, and the existing
   read-only artifact bind mount. It does not target the existing operational
   project or shared services.
5. Tests cover read-only artifact verification and GPU preflight pass/fail
   conditions, including the free-memory boundary and identity mismatch.
6. Local verification is recorded. Phase A performed no target operation. Phase
   B permits read-only target inspection and `make plan`, but no installation,
   container start, image pull, model permission or group membership change,
   milestone advancement or closeout.
7. Make `plan` and `install` are available from private validated configuration;
   `plan` has no deployment side effects, and `install` is isolated,
   digest-pinned, idempotent for a matching project and refuses identity/name
   conflicts.
8. Experimental target acceptance records plan READY, install PASS, readiness,
   one real transcription, shared/original STT health, resource observation,
   and repeated-install idempotency. This is a bounded experimental deployment
   acceptance, not full M01E completion.
9. Parallel inference stress testing and any other agreed coexistence scope
   must be completed and reviewed before full M01E acceptance. User validation
   and explicit closeout approval remain required.

## M01E-F — Isolated fresh-install and model-staging rehearsal preparation

Approved rehearsal identity: Compose project
`speech-platform-m01e-fresh-v012`, Gateway loopback port `18084`, enabled
services `gateway`, `stt`, and `tts`, immutable release v0.1.2, and a separate
initially empty model store. Prepare ignored private Gateway/TTS/STT configs,
CUDA STT profile and generated environment independent from the experimental
project. Validate that rendered Compose uses only the fresh project, new
loopback port, private network names and separate read-only model mount.

Prepare the existing content-addressed model provisioner with an explicit
empty-store check and deployment-compatible owner/group and modes. The pinned
model identity must come from the release and its manifest; no download is in
scope. Record read-only GPU consumers and distinguish measured use from
unmeasured peak/worst-case needs. Prepare a cleanup sequence that requires
review of exact project/container/network/model-store identity before any
later destructive operation. Do not launch a third CUDA worker without
separate approval. Parallel inference stress is not an M01E blocker.

Responsibilities and boundaries: private configs supply deployment-specific
identity, paths, port and reader group; Compose retains Gateway/STT/TTS
separation and read-only worker model access; the existing model provisioner
owns hash verification, staging and atomic digest-directory activation. No
API contract or service responsibility changes. A narrow planner error-path
correction is allowed so an absent model appears as a normal blocked plan.

Acceptance for this preparation slice is the ignored config set, rendered
read-only plan, exact not-run staging/cleanup procedures, actual GPU
observations, focused tests and `make verify`. Model download, Compose
installation, container/network lifecycle, cleanup, milestone closeout and
commit remain outside this authorization.

## M01E-C — Service selection and dependency resolution

This implementation slice completed deterministic selection and read-only plan
dispatch. Local implementation acceptance is PASS; it did not complete M01E
installation acceptance.

- `SERVICE=stt|tts|gateway` selects that enabled service and its dependencies
  from the release descriptor; an empty `SERVICE` selects every service in the
  private enabled-services configuration.
- Unknown/disabled services and missing, disabled or cyclic dependencies fail
  before deployment inspection or mutation. Dependency order is deterministic
  and appears in plan output.
- The resolver is the sole source of service dependencies. M01E-D consumes its
  deterministic dependency-first result for planning and installation.
- The service enablement file is private host configuration. Its tracked
  example is a schema/template only.

## M01E-D — Service-scoped multi-service deployment

Local implementation scope: install selected services or the private
enabled-service set using the release dependency graph; preserve unchanged
healthy components; add only selected missing/changed services to the dedicated
Compose project; and report dependency order and intended actions. The tracked
service profile is a template; project name, reader group, ports, resource
limits, private config paths and enabled services remain host data.

- The supported runtimes remain the release's Gateway foundation, health-only
  TTS and the already validated CUDA STT worker. No public STT routing or TTS
  inference is included.
- Selected images are checked against immutable release digests, platform and
  service provenance. Missing selected images may be pulled by exact digest.
  Missing STT models may be staged by the content-addressed provisioner using
  the profile's owner and reader group; corrupt existing releases fail without
  replacement.
- Each selected missing/changed service is applied individually with Compose
  dependency handling disabled. Dependencies are still applied because the
  resolver lists them explicitly. Unselected services and other project names
  are excluded from lifecycle commands. Healthy services with matching image
  and configuration identity are skipped.
- Gateway exposure remains loopback-only. STT and TTS remain on separate
  internal networks without host ports. Gateway/TTS health endpoints and STT
  Docker health are checked after selected changes.
- Local mocked acceptance covers fresh service installs, dependency closure,
  all-enabled selection, selective addition, healthy reuse, artifact staging
  and verification failures, readiness failures/timeouts, project scoping and
  M01E-C STT regressions. Controlled target acceptance is recorded in the
  final section of [verification.md](verification.md).

M01E-D local implementation and mocked acceptance is **PASS**. M01E-E
controlled all-enabled installation and current network/health acceptance are
**PASS for the observed scope**. M01E remains **IN PROGRESS / OPEN** pending
isolated fresh-install and clean-target artifact-staging rehearsals, parallel
inference stress, full user validation and explicit closeout. This breakdown
does not reduce the canonical acceptance requirements.

## Phase A continuation acceptance

- `make plan SERVICE=stt` does not write `compose.env`, create directories,
  invoke Docker lifecycle operations, pull images/download models, or change
  GPU state or installation records. It renders Compose from in-memory
  validated environment values.
- Planning reports the immutable release/image, model identity and location,
  Compose project/bindings/conflicts, current free VRAM, configured threshold,
  `READY`/`BLOCKED`, and blocker reasons. Low VRAM is a normal `BLOCKED` result.
- Installation repeats strict release/image/model/host validation and makes a
  fresh GPU identity/headroom observation immediately before Compose `up`.
  Any failed prerequisite prevents startup.
- A separate ignored experimental profile uses an isolated project/config
  directory, loopback profile port, verified image/model identities, configured
  GPU UUID/device index and model-reader supplementary GID. It preserves the
  existing 14 GiB threshold pending approval.
- Experimental deployment acceptance and its limits are recorded in the
  verification record. Parallel inference stress testing was not performed.
  No full M01E PASS or closeout is implied.

## Risks and limits

Free VRAM is a point-in-time observation and is not a reservation. The STT
application repeats its configured pre-load gate. Local tests cannot establish
the target account's sudo/group behavior, target filesystem integrity,
Compose/Engine compatibility, container GPU mapping or runtime coexistence.

## Validation commands

- `PYTHONPATH=. python3 -m unittest scripts.test_model_artifacts scripts.test_stt_deployment_profile -v`
- `make verify PYTHON=.venv/bin/python`
- Phase A: `make plan` was deferred until target configuration was prepared;
  `make install` was not run.
- Phase B: read-only target inspection, schema/render validation, and
  `make plan SERVICE=stt` using private target configuration.
- Experimental `make install` is now covered by user-reported target evidence
  in [verification.md](verification.md). Do not infer authorization for a new
  installation or lifecycle operation from that historical acceptance.
- M01E-D local implementation validation: focused service-deployment tests,
  `make governance-check PYTHON=.venv/bin/python`, `make verify
  PYTHON=.venv/bin/python`, and `git diff --check`; target installation remains
  unrun.
- M01E-E TTS recovery validation: confirm host config ownership/mode and
  container groups; reject unreadable config before Docker lifecycle commands;
  enforce the configured reader group in rendered Compose; distinguish exit
  state from genuine runtime drift; run focused regressions, `make compose-check
  PYTHON=.venv/bin/python`, `make verify PYTHON=.venv/bin/python`, and
  `git diff --check`; finish with the authorized read-only all-enabled plan.
- Review the diff and ensure no private/target data or deployment side effects.
