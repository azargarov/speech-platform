# Persistent CUDA STT deployment profile — C.6A

Status: **configuration design and offline validation only**. No target host, Docker runtime, GPU, model load or service was exercised by C.6A. Do not treat the example profile as deployable.

## What is prepared

The CUDA Compose overlay is runtime-only: it requires a repository-qualified immutable image reference, `pull_policy: never`, and clears the inherited build with Compose `!reset`. It selects one host GPU using a device reservation, keeps the worker on the existing internal `stt_private` network without a host port, and explicitly disables automatic restart. The worker remains UID/GID 65532, receives only the configured artifact read group, uses a read-only root, and mounts its model release read-only. Compose liveness calls the Python standard-library HTTP client against `/healthz`; `/readyz` remains a separate gate and is never used as container liveness.

`configs/stt-application-cuda.example.yaml` is explicitly CUDA-only, uses float16 with no CPU fallback, and names the approved large-v3-turbo revision and manifest digest. `configs/stt-deployment-cuda.example.yaml` selects container CUDA device 0 and keeps the free-memory estimate as a required unresolved setting. `configs/stt-deployment-profile-cuda.example.yaml` is the deployment-specific template. It carries the approved model and unchanged CUDA lock identity. The 4 CPU, 12 GiB RAM and 128 PID values are C.4 experiment references only. The deployment profile intentionally has unresolved production image/base-image digests and local image ID, source revision, target GPU UUID, artifact group, host release path, `limits_reviewed: false`, and base/image/source provenance verification flags set false; preparation rejects it until an operator supplies and reviews those inputs. C.6A did not establish an immutable base-image digest, build a production image or map a production repository reference to a local image ID, so none is invented. The known image is validation-only.

The existing STT application config remains authoritative for CUDA-only device policy, compute type, model-load timeout, request timeout, process-exit timeout and shutdown-drain timeout. The worker config's `socket_timeout_seconds` is aiohttp's graceful server shutdown bound. The deployment profile only supplies host/container device mapping and Compose resource/health/stop settings. The validator rejects CPU/auto fallback, alias/revision/manifest or CUDA-index mismatch, changed dependency lock, mutable image references, unreviewed limits, impossible timeout relationships, or an artifact that cannot be read under the declared group policy.

## Preparing a reviewed private profile

Copy the example to ignored `private/`, then fill every placeholder using target/operator evidence. Do not add the private profile or generated Compose environment file to Git.

```sh
cp configs/stt-deployment-profile-cuda.example.yaml private/stt-deployment-profile-cuda.yaml
cp configs/stt-application-cuda.example.yaml private/stt-application-cuda.yaml
cp configs/stt-deployment-cuda.example.yaml private/stt-deployment-cuda.yaml
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

`prepare` strictly loads the existing application, worker and deployment schemas; verifies the CUDA lock digest, model alias/revision/manifest and artifact file hashes; checks static group-read/no-world-access modes; validates resource and timeout relationships; then writes a mode-0600 Compose environment file under a private directory. It does not invoke Docker, CUDA or inference. A successful check proves only static file/config consistency. C.6B must repeat artifact verification as UID/GID 65532 with the configured supplementary group inside the actual runtime environment.

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

The C.6B Phase A image `sha256:b25af1309e1e51e8ce72c227028727cb26014fef512b716fbd11cf8f9fb16540` is a **validation image**, with entrypoint `python /opt/validation/probe.py`; it must never be used as the persistent worker. A Docker image ID identifies the local image configuration, while `repository@sha256:…` is a registry manifest reference; they are different identity values even when a tool reports matching digest strings. The profile stores both separately and requires evidence that the immutable repository reference resolves to the recorded local image ID. The production image itself has not been built, so its image ID and registry digest are unresolved.

The CUDA lock SHA-256 remains `68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14`; it pins the already validated faster-whisper/CTranslate2/CUDA/cuDNN package set. The Dockerfile embeds the supplied source revision, base reference and lock identity as inspectable labels, but labels alone are not provenance attestations. A later separately authorized build must preserve the build log/attestation and record: linux/amd64 platform-specific Python base manifest digest; actual lock digest; exact source Git revision and clean source state; Dockerfile/build context identity; built image ID; repository manifest digest if published; and inspection output proving those values and labels agree. Never represent the validation image as the output of this build.

The Docker build has external build-time inputs: retrieval of the pinned base image and the exact Python wheel artifacts referenced by the lock. A build therefore needs approved registry/index access or a separately verified local cache/wheelhouse. `--require-hashes` rejects substituted wheel contents, and the base reference must be digest-pinned; runtime containers do not download dependencies or models. Build-network provenance and the actual installed package inventory must be captured during the separately authorized build validation.

### Future build-validation gate (not authorized or executed by R1)

Before a separately approved build, require a clean committed source revision, an independently verified linux/amd64 digest for `python:3.13.9-slim`, the lock digest above, and an approved destination/retention policy for the built image. Verify that the checkout is exactly the reviewed commit and has no staged, unstaged, or untracked files. The source SHA build argument is only a label/input; it is not proof that arbitrary working-directory contents came from that commit. Build from a Git archive created from the verified commit so the context contains only that commit's tracked tree. A local build-validation command would have this shape; replace every placeholder from approved evidence and do not execute it without separate authorization:

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
