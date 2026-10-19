# M01E — Target host integration

Status: **Experimental CUDA STT deployment acceptance: PASS for the recorded real-host scope. Overall M01E remains OPEN: parallel inference stress testing and full agreed acceptance/user closeout are outstanding. Do not start M01F.**

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

## M01E-C — Service selection and dependency resolution

This bounded implementation slice completes deterministic selection and
read-only plan dispatch only. It does not complete M01E installation acceptance.

- `SERVICE=stt|tts|gateway` selects that enabled service and its dependencies
  from the release descriptor; an empty `SERVICE` selects every service in the
  private enabled-services configuration.
- Unknown/disabled services and missing, disabled or cyclic dependencies fail
  before deployment inspection or mutation. Dependency order is deterministic
  and appears in plan output.
- TTS and Gateway selection is reported as `BLOCKED: NOT IMPLEMENTED` until
  M01E-D. Neither selection may enter the STT installation path.
- The service enablement file is private host configuration. Its tracked
  example is a schema/template only.

M01E-D remains responsible for service-scoped installation for Gateway/TTS and
their dependencies while preserving the validated STT profiles. M01E-E and the
remaining M01E acceptance remain open for staged artifact handling and broader
fresh-install/selective-add/coexistence validation specified in the canonical
roadmap. This breakdown does not reduce roadmap acceptance requirements.

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
- Review the diff and ensure no private/target data or deployment side effects.
