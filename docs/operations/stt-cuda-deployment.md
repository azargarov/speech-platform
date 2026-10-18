# Persistent CUDA STT deployment profile — C.6A

Status: **configuration design and offline validation only**. No target host, production container start, GPU, model load or service is validated by this document's static checks. Do not treat the example profile as deployable.

## What is prepared

The CUDA Compose overlay is runtime-only: it requires an explicitly selected image identity mode, `pull_policy: never`, and clears the inherited build with Compose `!reset`. Registry-digest mode requires a repository-qualified immutable digest. Local-image mode uses an explicit typed store-identity contract and has no tag fallback. It selects one host GPU using a device reservation, keeps the worker on the existing internal `stt_private` network without a host port, and explicitly disables automatic restart. The worker remains UID/GID 65532, receives only the configured artifact read group, uses a read-only root, and mounts its model release read-only. Compose liveness calls the Python standard-library HTTP client against `/healthz`; `/readyz` remains a separate gate and is never used as container liveness.

`configs/stt-application-cuda.example.yaml` is explicitly CUDA-only, uses float16 with no CPU fallback, and names the approved large-v3-turbo revision and manifest digest. `configs/stt-deployment-cuda.example.yaml` selects container CUDA device 0 and keeps the free-memory estimate as a required unresolved setting. `configs/stt-deployment-profile-cuda.example.yaml` is the deployment-specific template. It carries the approved model and unchanged CUDA lock identity. The 4 CPU, 12 GiB RAM and 128 PID values are C.4 experiment references only. The deployment profile intentionally has unresolved production image/base-image digests and local image ID, source revision, target GPU UUID, artifact owner UID/read-group GID, host release path, `limits_reviewed: false`, and base/image/source provenance verification flags set false; preparation rejects it until an operator supplies and reviews those inputs. C.6A did not establish an immutable base-image digest, build a production image or map a production repository reference to a local image ID, so none is invented. The known image is validation-only.

The existing STT application config remains authoritative for CUDA-only device policy, compute type, model-load timeout, request timeout, process-exit timeout and shutdown-drain timeout. The worker config's `socket_timeout_seconds` is aiohttp's graceful server shutdown bound. The deployment profile only supplies host/container device mapping and Compose resource/health/stop settings. The validator rejects CPU/auto fallback, alias/revision/manifest or CUDA-index mismatch, changed dependency lock, mutable image references, unreviewed limits, impossible timeout relationships, or an artifact that cannot be read under the declared group policy.

## Preparing a reviewed private profile

Copy the example to ignored `private/`, then fill every placeholder using target/operator evidence. Do not add the private profile or generated Compose environment file to Git.

```sh
mkdir -p private && chmod 700 private
cp configs/stt-deployment-profile-cuda.example.yaml private/stt-deployment-profile-cuda.yaml
cp configs/stt-application-cuda.example.yaml private/stt-application-cuda.yaml
cp configs/stt-deployment-cuda.example.yaml private/stt-deployment-cuda.yaml
cp configs/stt.yaml private/stt-worker.yaml
# Use mode 0600 for every private input; keep containing directories at 0700.
chmod 600 private/stt-deployment-profile-cuda.yaml private/stt-application-cuda.yaml \
  private/stt-deployment-cuda.yaml private/stt-worker.yaml
# Set the required free-VRAM preflight value in the private deployment config
# only after operator review; configure the actual target artifact release and
# worker config without adding host-specific values to tracked files.
.venv/bin/python scripts/stt_deployment_profile.py prepare \
  --profile private/stt-deployment-profile-cuda.yaml \
  --application-config private/stt-application-cuda.yaml \
  --deployment-config private/stt-deployment-cuda.yaml \
  --worker-config private/stt-worker.yaml \
  --output-env private/deployment/stt-cuda.compose.env
```

`prepare` strictly loads the existing application, worker and deployment schemas; verifies the CUDA lock digest, model alias/revision/manifest and artifact file hashes; checks static owner/group/mode, setgid, traversal, and no-ACL policy; validates resource and timeout relationships; then writes a mode-0600 Compose environment file under a private directory. All four input configurations must be explicit non-example files under the ignored repository `private/` directory, with mode 0600 or stricter; there is no fallback to the tracked examples. In local-image mode, pass the private A2 build-evidence file (`--build-evidence`), the exact approved `docker save` archive (`--image-archive`), and image-store identity evidence (`--image-store-evidence`). The profile pins the build-evidence and image-store-evidence SHA-256 values; its typed artifact identity pins the archive digest, configuration digest and store-specific identity. The complete configuration-set identity includes each input's logical role, resolved source path and content SHA-256, private evidence-file path/content digests in local mode, and both Compose files' paths/content digests, serialized as sorted compact JSON. The archive bytes are verified against the archive SHA-256 declared in the profile rather than rehashed as a second configuration-set input. Only the resulting digest is placed in a Compose label; it does not expose source paths. The generated environment file is not an input, avoiding a self-reference cycle. Review and approve all resource values in the private profile; C.4's experimental limits are not production recommendations. Preparation and Compose rendering do not invoke CUDA or inference. Static success does not prove effective target permissions or mounted-container access; C.6B-R3 must verify artifact access as UID/GID 65532 plus the configured supplementary group in the actual runtime.

## Permanent model-reader group policy — prepared, target-unverified

Use one dedicated host model-reader group with a numeric GID recorded in the private deployment profile. Keep the image/worker UID:GID `65532:65532` unchanged and pass only that numeric reader GID as Compose `group_add`; do not rely on group names or assume host account membership is inherited by the container. Configure the release owner UID explicitly. The release root and all model directories must have that owner UID and reader GID, mode `2750` (setgid, owner `rwx`, group `r-x`); regular artifacts and manifest must have that owner/group and mode `0640` (owner `rw`, group `r`, no world access). The validator rejects group write, world permissions, wrong owner/group, non-regular files, symlinks, missing setgid on directories, ACLs on the release or traversed parents, and a release root not named by its canonical manifest SHA-256. The container bind mount remains read-only. This allows the reader group to enumerate/traverse directories and read files, but cannot mutate the immutable release.

Parent directories need only grant the worker identity execute/traversal and must not allow that identity to write; world-writable parents are rejected except a sticky, root-controlled temporary-directory pattern. Do not change the home or repository permissions to satisfy the check. If the approved release is inaccessible through existing parent permissions, use an operator-approved dedicated model store with restrictive parent traversal and a verified copy of the immutable release. The validator rejects POSIX ACLs: this design selects ordinary group/mode policy rather than combining two authorization systems. Container group namespaces/user remapping may change effective numeric identity; the target phase must inspect Docker's effective UID/GID/groups and prove actual reads. Static validation is not runtime proof.

## Private configuration preparation and review

Copy the tracked templates into `private/`, fill every placeholder only from independently collected target/image/model evidence, and set private files to mode 0600 and containing directories to 0700. Keep versioned, complete configuration sets together so rollback selects the prior profile, application config, deployment config, worker config, and generated env file as a unit. `prepare` rejects example files, external paths, symlinks, missing inputs, broad private permissions, mutable image tags, unresolved identity values, mismatched artifact identity, and unreviewed resource settings. Review the rendered effective Compose output and approve CPU, RAM, PID, free-VRAM admission and timeout values against host headroom and shared-service needs before deployment. The generated configuration-set digest identifies exact source bytes; it is an integrity identifier, not a signature or secret-management system. Keep credentials out of these files and Compose labels.

Rollback is release selection, not in-place mutation: retain at least one previously verified model release under its manifest-digest directory and its exact private configuration set. Select that digest and matching immutable image/config references explicitly. If any prior file, artifact, group access or integrity check fails, rollback must stop closed; do not alter an active release or fall back to an example/mutable tag.

The generated environment file drives the Compose settings. Render and validate before any separately authorized service start:

```sh
docker compose --env-file private/deployment/stt-cuda.compose.env \
  -f deployments/compose/compose.yaml \
  -f deployments/compose/compose.stt-cuda.yaml \
  --profile cuda config --format json |
  .venv/bin/python scripts/stt_deployment_profile.py check-rendered \
    --profile private/stt-deployment-profile-cuda.yaml \
    --application-config private/stt-application-cuda.yaml \
    --deployment-config private/stt-deployment-cuda.yaml \
    --worker-config private/stt-worker.yaml
```

The checker confirms the rendered project and profile labels, immutable image/no-build/no-pull policy, GPU 0 host selection, configured limits, no restart loop, private worker network/no published ports, non-root/read-only mount and `/healthz`-only healthcheck. Compose `config` is a render/validation step; it does not start containers. The environment file and target paths are deployment data and stay private.

## GPU identity and configuration relationship

The profile distinguishes `host_physical_index` from `container_cuda_index`. Compose exposes only host physical index 0. The application deployment config selects container CUDA index 0 after that one device is exposed. C.6B must compare the host's GPU 0 UUID with `expected_host_uuid`, then verify inside the isolated container that exactly that UUID is visible as CUDA device 0. The index remapping is an expectation to verify, not an assumption. No available-memory reading reserves VRAM.

CPU/RAM/PID settings and all application timeouts are explicit. The validator requires the worker shutdown bound to cover the maximum request timeout. Compose stop grace must cover the slower of model-load timeout plus child-exit timeout, or worker shutdown bound plus admission drain plus child-exit timeout, with the configured termination margin. Model-load and request timeouts come from the validated application schema; they are not duplicated in Compose variables. `healthcheck.start_period` must cover the configured model-load timeout. Initial restart behavior is `no`; after fault or `cleanup_unconfirmed`, recovery is operator-controlled and follows the existing [fault/recovery procedure](stt-cuda-http-integration.md#stt-worker-fault-and-recovery-procedure).

## Image and artifact identity

The existing `worker-stt-cuda.Dockerfile` is the production worker definition. It requires a digest-pinned `python:3.13.9-slim` base reference, the unchanged hash-locked CUDA dependency set, and an immutable source revision as build inputs. It installs dependencies with `--require-hashes`, copies only the STT and shared worker source (tests are excluded by `.dockerignore`), records source revision, base reference, image role and lock digest as labels, and launches `services.stt.main` through `python -m`. It runs as UID/GID 65532. Its `LD_LIBRARY_PATH` includes the installed cuBLAS, CUDA NVRTC and cuDNN package library directories; this is a static package-layout declaration, not evidence that the production image was built or that its runtime loader resolves each library. It contains no model, audio, credentials or private configuration and has no runtime model-download step. Compose supplies the existing worker/config arguments and uses Python's standard-library HTTP client for `/healthz`; `/readyz` remains separate. The C.4 CUDA inference reports did not record the exact loader environment, so equivalence with the C.4 image is not established.

The C.6B Phase A image `sha256:b25af1309e1e51e8ce72c227028727cb26014fef512b716fbd11cf8f9fb16540` is a **validation image**, with entrypoint `python /opt/validation/probe.py`; it must never be used as the persistent worker. Docker image ID, raw OCI configuration digest, OCI manifest digest, repository digest, RootFS diff ID and `docker save` archive SHA-256 are different identity types. A Docker `.Id` must be related to the OCI descriptors using evidence from the actual image store; the deployment profile no longer assumes it universally equals the config digest. The production A2 image's workstation config digest is `sha256:3780e43b86717c877d82bb65c9944c8df7d497efd8446263dbd22b5092f1f406`; the approved archive SHA-256 is `cdb4d88c51c4b8ebcdceed3f119b622b29f046a2786fd39b4c478cd73fa06dfd`. In the supplied target observation, Docker reported the OCI manifest identity `sha256:7f710bf8fca9307d387a5d61ab84361756efa9c3e18a6d60e07b9c42b60eb45c`, whose manifest referenced configuration digest `3780…`; raw config bytes matched that config digest. This is a finding for the reported Engine 29.1.3/containerd 2.2.1 image-store record only, not a universal mapping rule. The target identity contract still requires reviewed store evidence and exact raw manifest/config/layer relationships. The workstation create-only compatibility test remains limited to Engine `29.7.2-ce` and Compose `5.6.0`; target Engine 29.1.3 is not in the allowlist. No target deployment or runtime readiness is established.

The CUDA lock SHA-256 remains `68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14`; it pins the already validated faster-whisper/CTranslate2/CUDA/cuDNN package set. The Dockerfile embeds source revision, base reference and lock identity as inspectable labels, but labels alone are not provenance attestations. For either mode, private validated configuration binds source revision, base manifest digest, lock digest, platform, image identity, model revision/manifest and configuration-set digest. Local mode additionally binds the exact private build-evidence and image-store-evidence file bytes by SHA-256 and checks the approved archive digest. These hashes establish file identity, not the truth of evidence claims or an independent signature. The operator trust boundary is the reviewed private profile and evidence: an authorized operator must verify their provenance and approve them before preparation or deployment. The profile is authoritative for the expected image-store identity; evidence and labels cannot redefine it. A read-only `verify-image` path first validates the private provenance/artifact inputs, then compares Docker inspection of the exact configured identity, platform, non-root user, production `python -m` entrypoint and provenance labels. This checks consistency; it does not turn labels into independent proof.

For local-image mode, select the discriminator and artifact identity kind explicitly in the private profile, remove registry-only `image` and `image_reference_verified` fields, and supply the expected store-reported `image_id`, build-evidence digest, archive digest, and image-store-evidence digest. `docker_config_digest` is valid only where the observed store reports that config identity; `containerd_oci_manifest` requires a unique target image record and raw manifest evidence whose digest and config/layer descriptors match the approved identity. Layer-content verification is represented in the pinned image-store evidence; the offline validator does not fetch blobs from a remote or target containerd store. Evidence collection and approval are operator trust-boundary steps, not independent signature verification. There is no mutable-tag fallback. Before preparing/rendering or any separately approved creation, supply all inputs explicitly:

```sh
.venv/bin/python scripts/stt_deployment_profile.py verify-image \
  --profile private/stt-deployment-profile-cuda.yaml \
  --application-config private/stt-application-cuda.yaml \
  --deployment-config private/stt-deployment-cuda.yaml \
  --worker-config private/stt-worker.yaml \
  --build-evidence private/image-build-a2-20261018-01/build-result.json \
  --image-archive private/image-build-a2-20261018-01/production-image.tar \
  --image-store-evidence private/image-build-a2-20261018-01/image-store-evidence.json
```

The check is read-only: it runs Docker Engine/Compose version queries and `docker image inspect` for the exact configured ID; it never pulls or builds. Local mode is currently accepted only for Engine `29.7.2-ce` and Compose `5.6.0`. Registry mode remains governed by the existing repository-qualified immutable digest and verified image-ID relationship.

After a separately authorized Compose create operation, but before any start authorization, inspect the full ID returned by Compose and run the read-only check (with the same private config and evidence arguments shown above):

```sh
.venv/bin/python scripts/stt_deployment_profile.py verify-container \
  --profile private/stt-deployment-profile-cuda.yaml \
  --application-config private/stt-application-cuda.yaml \
  --deployment-config private/stt-deployment-cuda.yaml \
  --worker-config private/stt-worker.yaml \
  --build-evidence private/image-build-a2-20261018-01/build-result.json \
  --image-archive private/image-build-a2-20261018-01/production-image.tar \
  --image-store-evidence private/image-build-a2-20261018-01/image-store-evidence.json \
  --container-id '<full-container-id>'
```

It performs read-only `docker container inspect`, verifies the returned `.Id` equals the supplied full container ID, requires the container to remain stopped in `created` state, and compares `.Image` to the profile's expected store identity. A missing/replaced container, returned-ID mismatch, image mismatch or unexpected state fails closed. Container creation and startup are separate gates; this command does not create, start or remove resources. This ordering is enforced by the operator procedure, not atomically by Docker: an independently issued `start` command or another orchestration path can bypass the check. Withhold start authorization until verification succeeds; this is not an atomic create-and-start guarantee.

If transferring the local image to another daemon is separately approved, retain the exact approved archive and its SHA-256, then collect evidence from that daemon's exact image-store record. The identity evidence must cryptographically bind the selected manifest bytes to its manifest digest, config descriptor and ordered layer descriptors; the raw configuration digest must match the manifest and approved archive config; RootFS diff IDs and archive layer contents must match the approved archive; and the image-record association must be unique. The private reviewed profile pins the evidence-file digest and expected daemon-reported identity. Do not infer the store identity from labels or from selected parsed fields. The archive hash proves transfer-byte integrity but not build provenance. Keep prior approved image and model/configuration releases for rollback; never prune unrelated resources or use a tag as authority.

The Docker build has external build-time inputs: retrieval of the pinned base image and the exact Python wheel artifacts referenced by the lock. A build therefore needs approved registry/index access or a separately verified local cache/wheelhouse. `--require-hashes` rejects substituted wheel contents, and the base reference must be digest-pinned; runtime containers do not download dependencies or models. Build-network provenance and the actual installed package inventory must be captured during the separately authorized build validation.

### Reproducible build procedure and A2 record

The A2 build followed the recorded clean-source/archive procedure once, using the accepted commit, verified base manifest and CUDA lock; its output image was inspected and not run. For any future rebuild, require separate approval, a clean committed source revision, an independently verified linux/amd64 digest for `python:3.13.9-slim`, the lock digest above, and an approved destination/retention policy. Verify that the checkout is exactly the reviewed commit and has no staged, unstaged, or untracked files. The source SHA build argument is only a label/input; it is not proof that arbitrary working-directory contents came from that commit. Build from a Git archive created from the verified commit so the context contains only that commit's tracked tree. The following is a command shape, not authorization to rebuild; replace every placeholder from approved evidence:

```sh
set -euo pipefail
EXPECTED_SOURCE_REVISION='<reviewed-full-commit-sha>'
SOURCE_REVISION="$(git rev-parse --verify HEAD)"
test "$SOURCE_REVISION" = "$EXPECTED_SOURCE_REVISION"
test -z "$(git status --porcelain --untracked-files=all)"

git archive --format=tar "$SOURCE_REVISION" |
docker buildx build --platform linux/amd64 --load \
  --build-arg STT_CUDA_BASE_IMAGE='python:3.13.9-slim@sha256:<verified-platform-digest>' \
  --build-arg STT_SOURCE_REVISION="$SOURCE_REVISION" \
  --build-arg STT_CUDA_LOCK_SHA256='68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14' \
  --file deployments/compose/worker-stt-cuda.Dockerfile \
  --tag '<operator-approved-local-name>' -
```

The clean-checkout gate catches accidental local edits and untracked inputs; the archive context ties the Dockerfile and source bytes to `SOURCE_REVISION` and excludes ignored/private and untracked files by construction. Do not replace the archive context with `.` while keeping the same build argument.

Then inspect only that exact image ID: confirm `linux/amd64`, UID/GID 65532, production module entrypoint, the four provenance labels, installed package versions/hashes against the lock, and availability of the Python standard-library healthcheck. Record the local image ID separately from any registry manifest digest. `--load` alone does not produce a repository-qualified immutable digest; if deployment policy continues to require `repository@sha256:…`, the registry destination and any push authorization must be approved separately. No inference/model load is part of image validation.

C.6A did not resolve the immutable platform-specific base digest or build/pull/substitute any image. The example profile remains fail-closed until the base digest and platform evidence, source revision, built image ID/reference mapping, dependency inventory, host GPU UUID, artifact permissions and resource review are supplied. The target Phase A model release remains inaccessible to the configured non-root worker without an approved permanent permission arrangement; R1 does not change host permissions. If any provenance input cannot be independently established, stop rather than inventing it or reusing the validation image.

The host model release is an immutable versioned directory mounted at `/models:ro`; the profile and app/deployment configs must agree on the artifact directory and manifest location. Model files and manifest must be owned by a dedicated read group, directories group-readable/traversable, regular files group-readable, and no files/directories world-accessible. No runtime `chmod` or privileged container is allowed. Static mode checks cannot establish target ACLs, mount semantics or effective container access; C.6B must run the existing artifact verifier as the actual worker identity before starting persistent inference.

## Startup, monitoring and rollback procedure to validate in C.6B/C.6C

1. Preserve the current approved release identity (image digest, profile/config hashes, model revision and manifest hash) as rollback release A. Stage the candidate release B beside it; never overwrite A.
2. Before start, validate config schemas, model manifest and file hashes, image/platform identity, image lock/provenance, effective permissions, generated environment file permissions, and the rendered Compose config. Stop on any mismatch.
3. Use a dedicated explicit Compose project and the `cuda` profile to start only service `stt`. Do not run whole-stack `down`, pruning, GPU reset, or commands targeting Ollama/Dify. Do not publish STT ports.
4. Resolve and record the exact STT container ID from that Compose project. Docker health `healthy` proves only `/healthz` liveness. Separately query `/readyz` inside the exact worker/container network and require HTTP 200 plus expected model identity before permitting requests. A `cleanup_unconfirmed` 503 blocks replacement and requires operator escalation.
5. For bounded shutdown, target only the recorded container ID or exact Compose project/service after confirming its container ID. Use the configured stop grace, inspect the same ID and verify the inference child exit from supervisor/application evidence. Container removal alone does not prove GPU context release.
6. Roll back by restoring the complete previously verified release A (immutable image reference, app/deployment/worker config, model release and generated environment) from its preserved versioned files. Re-run all pre-start validation and rendered Compose checks, then start only the exact STT service. Do not rely on a mutable tag or automatic rollback.
7. Preserve sanitized startup/shutdown evidence outside Git and verify Ollama and Dify health before and after. If exact container/child exit, model access, GPU identity, readiness or shared-service health cannot be confirmed, stop and escalate without retrying.

For a future separately authorized C.6B/C.6C execution, use the same reviewed env file and Compose file pair for every command. Resolve the project name from the validated profile/env file and record the exact container ID before lifecycle actions. The following command shapes are operator procedures only; they were not run in C.6A:

Set `STT_STOP_GRACE_PERIOD_SECONDS` in the operator shell from the reviewed deployment profile value; do not substitute an unreviewed literal.

```sh
docker compose --env-file private/deployment/stt-cuda.compose.env \
  -f deployments/compose/compose.yaml \
  -f deployments/compose/compose.stt-cuda.yaml \
  --profile cuda up --detach --no-build --pull never stt

docker compose --env-file private/deployment/stt-cuda.compose.env \
  -f deployments/compose/compose.yaml \
  -f deployments/compose/compose.stt-cuda.yaml \
  --profile cuda ps --all --quiet stt

# Save the returned full ID, inspect that exact ID, then stop/remove only it.
docker inspect "$STT_CONTAINER_ID"
docker stop --time "$STT_STOP_GRACE_PERIOD_SECONDS" "$STT_CONTAINER_ID"
docker inspect --format '{{.State.Running}}' "$STT_CONTAINER_ID"
docker rm "$STT_CONTAINER_ID"
```

Rollback uses the preserved prior version of the profile, generated env file, app/deployment/worker configs, image digest and model release as one release set. Re-run `prepare` and rendered-Compose validation against that prior set before recreating only the `stt` service in the same explicitly named project. Do not use `compose down`, broad container cleanup, mutable tags, process-wide kills, or Docker/GPU resets. If stop, child exit, or exact resource identity cannot be confirmed, preserve evidence and escalate instead of trying a second cleanup target.

The command sequence above is an operator procedure proposal, not authorization to start or stop anything. C.6B covers startup/readiness/bounded shutdown; C.6C separately covers one private-path request and a rollback rehearsal.

## Deferred to C.6B and C.6C

**C.6B build/runtime evidence:** immutable base provenance and approved build inputs; production image identity (distinct local image ID and repository digest); dependency inventory matching the lock; actual mounted file access and verifier result; host UUID to container CUDA-device mapping; GPU visibility; model load; `/healthz`/`/readyz` transitions; enforced CPU/RAM/PID limits; exact child/container shutdown; operator health checks; and no changes to Ollama/Dify. The current R1 work supplies only the offline production image specification and rejection checks; it establishes none of this runtime evidence.

**C.6C runtime evidence:** one approved request through the private persistent worker path; response validation and sanitized logs; exact release rollback and re-readiness; project resource inventory; and postflight shared-service health.

Neither phase establishes concurrency capacity, sustained performance, exact peak VRAM, real CUDA OOM recovery or active GPU workload coexistence unless separately authorized and measured. Overall M02 remains incomplete.
