# Persistent CUDA STT deployment profile — C.6A

Status: **regular production profile not ready**. This C.6A profile and Compose policy remain design/offline validated; target image-store evidence is now present and passes the existing offline identity validator, but no regular production profile has been prepared. The separate M01E experimental deployment has since passed its bounded real-host acceptance; that does not constitute production-profile acceptance. See [M01E verification](../milestones/M01E/verification.md).

## Current image-store evidence review

The private target collector record at `private/evidence/image-store-evidence.json` has SHA-256 `45dffe412426bd4a00ceb15c736eda499bba376e1e47ae6f2ae2ba9266d1dafc`. The existing `validate_local_artifact_identity()` accepted it against the retained approved image archive. It binds the reported containerd OCI manifest identity `sha256:7f710bf8fca9307d387a5d61ab84361756efa9c3e18a6d60e07b9c42b60eb45c` to config digest `sha256:3780e43b86717c877d82bb65c9944c8df7d497efd8446263dbd22b5092f1f406`, the archive SHA-256, ten ordered layer descriptors, RootFS diff IDs and the raw manifest. The accompanying A2 build record has SHA-256 `b25f992d44c0e9b0aa4be103080325daf2ccfa586a383a7ad134923cbdaffae7`.

This is offline consistency validation of the supplied private record and archive, not a fresh target inspection or independent signature. The current private candidate now records the operator-confirmed target GPU UUID, model release and owner/group, worker identity, and approved initial experimental resource limits. The supplied host checks report that all seven release files are readable by UID/GID 65532:65532 with supplementary GID 988. Those are operator-provided observations, not a fresh target inspection or proof of container access. Deployment remains blocked: target Engine `29.1.3` is outside the local-image mode compatibility allowlist (`29.7.2-ce` only, with Compose `5.6.0`), and the workstation cannot inspect the target-only model path to satisfy the existing `prepare` artifact/permission verifier. Current GPU mapping, host headroom and shared-service health must be rechecked before creation. No compatibility gate is bypassed here. The Compose overlay already has no STT host port, uses an internal private network, selects one configured host GPU, runs non-root with a read-only root, uses manual restart behavior, and probes `/healthz`; no Compose policy change is justified by this review.

## What is prepared

The CUDA Compose overlay is runtime-only: it requires an explicitly selected image identity mode, `pull_policy: never`, and clears the inherited build with Compose `!reset`. Registry-digest mode requires a repository-qualified immutable digest. Local-image mode uses an explicit typed store-identity contract and has no tag fallback. It selects one host GPU using a device reservation, keeps the worker on the existing internal `stt_private` network without a host port, and explicitly disables automatic restart. The worker remains UID/GID 65532, receives only the configured artifact read group, uses a read-only root, and mounts its model release read-only. Compose liveness calls the Python standard-library HTTP client against `/healthz`; `/readyz` remains a separate gate and is never used as container liveness.

`configs/stt-application-cuda.example.yaml` is explicitly CUDA-only, uses float16 with no CPU fallback, and names the approved large-v3-turbo revision and manifest digest. `configs/stt-deployment-cuda.example.yaml` selects container CUDA device 0 and keeps the free-memory estimate as a required unresolved setting. `configs/stt-deployment-profile-cuda.example.yaml` is the deployment-specific template. It carries the approved model and unchanged CUDA lock identity. The 4 CPU, 12 GiB RAM and 128 PID values are C.4 experiment references only. The deployment profile intentionally has unresolved production image/base-image digests and local image ID, source revision, target GPU UUID, artifact owner UID/read-group GID, host release path, `limits_reviewed: false`, and base/image/source provenance verification flags set false; preparation rejects it until an operator supplies and reviews those inputs. C.6A did not establish an immutable base-image digest, build a production image or map a production repository reference to a local image ID, so none is invented. The known image is validation-only.

The existing STT application config remains authoritative for CUDA-only device policy, compute type, model-load timeout, request timeout, process-exit timeout and shutdown-drain timeout. The worker config's `socket_timeout_seconds` is aiohttp's graceful server shutdown bound. The deployment profile only supplies host/container device mapping and Compose resource/health/stop settings. The validator rejects CPU/auto fallback, alias/revision/manifest or CUDA-index mismatch, changed dependency lock, mutable image references, unreviewed limits, impossible timeout relationships, or an artifact that cannot be read under the declared group policy.

## Preparing a reviewed private profile

The workstation has a private candidate set under `private/deployment/cuda-stt-initial/`. It binds the accepted image/model evidence and uses the CUDA templates. The candidate records the operator-confirmed GPU UUID, model owner UID 0, reader GID 988, worker UID/GID 65532:65532, and operator-approved initial experimental limits. The supplied target-side `setpriv` checks cover all seven release files, but do not replace target `prepare` validation or prove access from the created container. On this workstation, `prepare` currently fails because the target-only release root is not present locally; it must be run on the target after confirming the same inputs there. The target Engine compatibility gate also remains unsupported and must be explicitly addressed before container creation.

For a new checkout, copy templates without overwriting an existing private candidate, then fill every placeholder using reviewed target evidence. Do not add private files or the generated Compose environment file to Git.

```sh
mkdir -p private/deployment/cuda-stt-initial
chmod 700 private private/deployment private/deployment/cuda-stt-initial
cp -n configs/stt-deployment-profile-cuda.example.yaml private/deployment/cuda-stt-initial/profile.yaml
cp -n configs/stt-application-cuda.example.yaml private/deployment/cuda-stt-initial/application.yaml
cp -n configs/stt-deployment-cuda.example.yaml private/deployment/cuda-stt-initial/deployment.yaml
cp -n configs/stt.yaml private/deployment/cuda-stt-initial/worker.yaml
# Use mode 0600 for every private input; keep containing directories at 0700.
chmod 600 private/deployment/cuda-stt-initial/profile.yaml private/deployment/cuda-stt-initial/application.yaml \
  private/deployment/cuda-stt-initial/deployment.yaml private/deployment/cuda-stt-initial/worker.yaml
# Set the required free-VRAM preflight value in the private deployment config
# only after operator review; configure the actual target artifact release and
# worker config without adding host-specific values to tracked files.
.venv/bin/python scripts/stt_deployment_profile.py prepare \
  --profile private/deployment/cuda-stt-initial/profile.yaml \
  --application-config private/deployment/cuda-stt-initial/application.yaml \
  --deployment-config private/deployment/cuda-stt-initial/deployment.yaml \
  --worker-config private/deployment/cuda-stt-initial/worker.yaml \
  --build-evidence private/image-build-a2-20261018-01/build-result.json \
  --image-archive private/results/c6b-image-transfer-20261018-01/stt-cuda-image.tar \
  --image-store-evidence private/evidence/image-store-evidence.json \
  --output-env private/deployment/cuda-stt-initial/stt-cuda.compose.env
```

`prepare` strictly loads the existing application, worker and deployment schemas; verifies the CUDA lock digest, model alias/revision/manifest and artifact file hashes; checks static owner/group/mode, setgid, traversal, and no-ACL policy; validates resource and timeout relationships; then writes a mode-0600 Compose environment file under a private directory. All four input configurations must be explicit non-example files under the ignored repository `private/` directory, with mode 0600 or stricter; there is no fallback to the tracked examples. In local-image mode, pass the private A2 build-evidence file (`--build-evidence`), the exact approved `docker save` archive (`--image-archive`), and image-store identity evidence (`--image-store-evidence`). The profile pins the build-evidence and image-store-evidence SHA-256 values; its typed artifact identity pins the archive digest, configuration digest and store-specific identity. The complete configuration-set identity includes each input's logical role, resolved source path and content SHA-256, private evidence-file path/content digests in local mode, and both Compose files' paths/content digests, serialized as sorted compact JSON. The archive bytes are verified against the archive SHA-256 declared in the profile rather than rehashed as a second configuration-set input. Only the resulting digest is placed in a Compose label; it does not expose source paths. The generated environment file is not an input, avoiding a self-reference cycle. Review and approve all resource values in the private profile; C.4's experimental limits are not production recommendations. Preparation and Compose rendering do not invoke CUDA or inference. Static success does not prove effective target permissions or mounted-container access; C.6B-R3 must verify artifact access as UID/GID 65532 plus the configured supplementary group in the actual runtime.

The profile also records the Gateway host and container ports. The host binding is restricted to `127.0.0.1` and validated in the rendered Compose output. For an STT-only `up`, the Gateway is not started; this setting keeps the rendered project deterministic if Gateway is later selected.

## Permanent model-reader group policy — prepared, target-unverified

Use one dedicated host model-reader group with a numeric GID recorded in the private deployment profile. Keep the image/worker UID:GID `65532:65532` unchanged and pass only that numeric reader GID as Compose `group_add`; do not rely on group names or assume host account membership is inherited by the container. Configure the release owner UID explicitly. The release root and all model directories must have that owner UID and reader GID, mode `2750` (setgid, owner `rwx`, group `r-x`); regular artifacts and manifest must have that owner/group and mode `0640` (owner `rw`, group `r`, no world access). The validator rejects group write, world permissions, wrong owner/group, non-regular files, symlinks, missing setgid on directories, ACLs on the release or traversed parents, and a release root not named by its canonical manifest SHA-256. The container bind mount remains read-only. This allows the reader group to enumerate/traverse directories and read files, but cannot mutate the immutable release.

Parent directories need only grant the worker identity execute/traversal and must not allow that identity to write; world-writable parents are rejected except a sticky, root-controlled temporary-directory pattern. Do not change the home or repository permissions to satisfy the check. If the approved release is inaccessible through existing parent permissions, use an operator-approved dedicated model store with restrictive parent traversal and a verified copy of the immutable release. The validator rejects POSIX ACLs: this design selects ordinary group/mode policy rather than combining two authorization systems. Container group namespaces/user remapping may change effective numeric identity; the target phase must inspect Docker's effective UID/GID/groups and prove actual reads. Static validation is not runtime proof.

The previously observed release under `/home/master/...` had owner-only directories and a mode-0600 manifest. Do not loosen the home directory or mutate that release in place. The following is a proposed permission procedure for `llm`: copy the already verified release into a dedicated `/srv` store, create a dedicated group, and apply modes only to the new digest-named copy. It requires a fresh path/disk preflight and separate approval. Stop if the destination or group already exists, the source contains symlinks/special objects, or disk headroom is insufficient. The copy is local and does not download the model.

```sh
set -euo pipefail
MODEL_DIGEST=86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6
SOURCE_RELEASE="/home/master/speech-platform-staging/M02/M02-C/M02-C.4/releases/$MODEL_DIGEST"
STORE_PARENT=/srv/speech-platform
STORE_ROOT=/srv/speech-platform/models
MODEL_RELEASE="$STORE_ROOT/$MODEL_DIGEST"
MODEL_READER_GROUP=stt-model-reader

test -d "$SOURCE_RELEASE"
sudo test ! -e "$STORE_PARENT"
if getent group "$MODEL_READER_GROUP" >/dev/null; then
  echo "model-reader group exists; inspect and review it before proceeding" >&2
  exit 1
fi
if sudo find -P "$SOURCE_RELEASE" ! -type d ! -type f -print -quit | grep -q .; then
  echo "source release contains a symlink or non-regular object" >&2
  exit 1
fi
sudo groupadd --system "$MODEL_READER_GROUP"
MODEL_READER_GID="$(getent group "$MODEL_READER_GROUP" | cut -d: -f3)"
test -n "$MODEL_READER_GID"
sudo install -d -o root -g root -m 0711 "$STORE_PARENT"
sudo install -d -o root -g "$MODEL_READER_GROUP" -m 2710 "$STORE_ROOT"
sudo test ! -e "$MODEL_RELEASE"
sudo install -d -o root -g "$MODEL_READER_GROUP" -m 2750 "$MODEL_RELEASE"
sudo cp -a "$SOURCE_RELEASE/." "$MODEL_RELEASE/"
if sudo find -P "$MODEL_RELEASE" ! -type d ! -type f -print -quit | grep -q .; then
  echo "copied release contains a symlink or non-regular object" >&2
  exit 1
fi
sudo chown -hR "root:$MODEL_READER_GROUP" "$MODEL_RELEASE"
sudo find -P "$MODEL_RELEASE" -type d -exec chmod 2750 {} +
sudo find -P "$MODEL_RELEASE" -type f -exec chmod 0640 {} +
printf 'Reader GID for private profile: %s\n' "$MODEL_READER_GID"
```

This leaves the source release untouched. Set the private profile's `host_release_root` to the destination, `artifact_owner_uid: 0`, and `supplementary_read_gid` to the printed GID, then run the existing `prepare` validator. It checks artifact hashes, ownership, modes, ACL absence and parent traversal. It does not prove effective access under Docker user-namespace settings; actual container access/readiness remains a separate gate.


## Private configuration preparation and review

Copy the tracked templates into `private/`, fill every placeholder only from independently collected target/image/model evidence, and set private files to mode 0600 and containing directories to 0700. Keep versioned, complete configuration sets together so rollback selects the prior profile, application config, deployment config, worker config, and generated env file as a unit. `prepare` rejects example files, external paths, symlinks, missing inputs, broad private permissions, mutable image tags, unresolved identity values, mismatched artifact identity, and unreviewed resource settings. Review the rendered effective Compose output and approve CPU, RAM, PID, free-VRAM admission and timeout values against host headroom and shared-service needs before deployment. The generated configuration-set digest identifies exact source bytes; it is an integrity identifier, not a signature or secret-management system. Keep credentials out of these files and Compose labels.

Rollback is release selection, not in-place mutation: retain at least one previously verified model release under its manifest-digest directory and its exact private configuration set. Select that digest and matching immutable image/config references explicitly. If any prior file, artifact, group access or integrity check fails, rollback must stop closed; do not alter an active release or fall back to an example/mutable tag.

The generated environment file drives the Compose settings. Render and validate before any separately authorized service start:

```sh
set -euo pipefail

docker compose --env-file private/deployment/cuda-stt-initial/stt-cuda.compose.env \
  -f deployments/compose/compose.yaml \
  -f deployments/compose/compose.stt-cuda.yaml \
  --profile cuda config --format json |
  .venv/bin/python scripts/stt_deployment_profile.py check-rendered \
    --profile private/deployment/cuda-stt-initial/profile.yaml \
    --application-config private/deployment/cuda-stt-initial/application.yaml \
    --deployment-config private/deployment/cuda-stt-initial/deployment.yaml \
    --worker-config private/deployment/cuda-stt-initial/worker.yaml \
    --build-evidence private/image-build-a2-20261018-01/build-result.json \
    --image-archive private/results/c6b-image-transfer-20261018-01/stt-cuda-image.tar \
    --image-store-evidence private/evidence/image-store-evidence.json
```

The checker confirms the rendered project and profile labels, immutable image/no-build/no-pull policy, GPU 0 host selection, configured limits, no restart loop, private worker network/no published ports, non-root/read-only mount and `/healthz`-only healthcheck. Compose `config` is a render/validation step; it does not start containers. The environment file and target paths are deployment data and stay private.

### Initial resource proposal — not approved

The private candidate uses the operator-approved initial experimental limits: 4 CPUs, 12 GiB RAM, 128 PIDs; one active and one queued request; the existing C.4 model-load/request/shutdown timeouts (100-second model-load timeout, 25-second request timeout, 60-second worker socket shutdown timeout, 10-second drain, 2-second child-exit timeout and 125-second Compose stop grace); and a 14,336 MiB pre-load free-VRAM gate. The supplied preflight observed 14,909 MiB free GPU memory and 57 GiB available host RAM at that time; these are observations, not reserved capacity or current readings. The operator-approved limits are marked reviewed in the private candidate, but they do not establish production capacity, exact peak VRAM, concurrency capacity or sustained performance.




## Read-only target preflight commands

Run these on `llm` only after separate authorization for target inspection. They do not create or modify Docker resources. Retain sanitized output privately; do not capture full inspect JSON or environment values.

```sh
set -euo pipefail
hostnamectl --static
uname -m
docker context show
docker version --format 'client={{.Client.Version}} server={{.Server.Version}} api={{.Server.APIVersion}}'
docker compose version
docker info --format 'os={{.OSType}} arch={{.Architecture}} storage={{.Driver}} runtimes={{json .Runtimes}}'
nvidia-smi --query-gpu=index,uuid,name,memory.total,memory.free,utilization.gpu --format=csv,noheader
nproc
free -b
df -B1 /srv
docker ps --all --format '{{.ID}} {{.Names}} {{.State}} {{.Status}}'
curl --fail --silent --show-error --max-time 3 http://127.0.0.1:11434/api/version >/dev/null
docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}} {{.Config.User}} {{json .Config.Entrypoint}}' \
  sha256:7f710bf8fca9307d387a5d61ab84361756efa9c3e18a6d60e07b9c42b60eb45c
```

Compare Engine/Compose with the explicit local-image compatibility allowlist: recorded target Engine 29.1.3 is unsupported, while Compose 5.6.0 matches. The minimum policy change is an explicit addition of Engine `29.1.3` to the centralized allowlist and regression coverage for the exact Engine 29.1.3 / Compose 5.6.0 pair, after a separately authorized create-only compatibility test succeeds. No policy expansion is made here. Compare GPU 0 UUID to a freshly reviewed private profile value and verify the exact image output is the expected manifest identity, linux/amd64, user 65532:65532 and production `python -m` entrypoint. `nvidia-smi` and Docker's runtime list do not prove host-to-container CUDA mapping.

`docker ps` provides current Ollama/Dify state and Docker health where configured. Missing health status means unknown, not healthy. The Ollama version GET is read-only. Do not restart or send inference to either service.

## GPU identity and configuration relationship

The profile distinguishes `host_physical_index` from `container_cuda_index`. Compose exposes only host physical index 0. The application deployment config selects container CUDA index 0 after that one device is exposed. C.6B must compare the host's GPU 0 UUID with `expected_host_uuid`, then verify inside the isolated container that exactly that UUID is visible as CUDA device 0. The index remapping is an expectation to verify, not an assumption. No available-memory reading reserves VRAM.

CPU/RAM/PID settings and all application timeouts are explicit. The validator requires the worker shutdown bound to cover the maximum request timeout. Compose stop grace must cover the slower of model-load timeout plus child-exit timeout, or worker shutdown bound plus admission drain plus child-exit timeout, with the configured termination margin. Model-load and request timeouts come from the validated application schema; they are not duplicated in Compose variables. `healthcheck.start_period` must cover the configured model-load timeout. Initial restart behavior is `no`; after fault or `cleanup_unconfirmed`, recovery is operator-controlled and follows the existing [fault/recovery procedure](stt-cuda-http-integration.md#stt-worker-fault-and-recovery-procedure).

## Image and artifact identity

The existing `worker-stt-cuda.Dockerfile` is the production worker definition. It requires a digest-pinned `python:3.13.9-slim` base reference, the unchanged hash-locked CUDA dependency set, and an immutable source revision as build inputs. It installs dependencies with `--require-hashes`, copies only the STT and shared worker source (tests are excluded by `.dockerignore`), records source revision, base reference, image role and lock digest as labels, and launches `services.stt.main` through `python -m`. It runs as UID/GID 65532. Its `LD_LIBRARY_PATH` includes the installed cuBLAS, CUDA NVRTC and cuDNN package library directories; this is a static package-layout declaration, not evidence that the production image was built or that its runtime loader resolves each library. It contains no model, audio, credentials or private configuration and has no runtime model-download step. Compose supplies the existing worker/config arguments and uses Python's standard-library HTTP client for `/healthz`; `/readyz` remains separate. The C.4 CUDA inference reports did not record the exact loader environment, so equivalence with the C.4 image is not established.

The C.6B Phase A image `sha256:b25af1309e1e51e8ce72c227028727cb26014fef512b716fbd11cf8f9fb16540` is a **validation image**, with entrypoint `python /opt/validation/probe.py`; it must never be used as the persistent worker. Docker image ID, raw OCI configuration digest, OCI manifest digest, repository digest, RootFS diff ID and `docker save` archive SHA-256 are different identity types. A Docker `.Id` must be related to the OCI descriptors using evidence from the actual image store; the deployment profile no longer assumes it universally equals the config digest. The production A2 image's workstation config digest is `sha256:3780e43b86717c877d82bb65c9944c8df7d497efd8446263dbd22b5092f1f406`; the approved archive SHA-256 is `cdb4d88c51c4b8ebcdceed3f119b622b29f046a2786fd39b4c478cd73fa06dfd`. In the supplied target observation, Docker reported the OCI manifest identity `sha256:7f710bf8fca9307d387a5d61ab84361756efa9c3e18a6d60e07b9c42b60eb45c`, whose manifest referenced configuration digest `3780…`; raw config bytes matched that config digest. This is a finding for the reported Engine 29.1.3/containerd 2.2.1 image-store record only, not a universal mapping rule. The target identity contract still requires reviewed store evidence and exact raw manifest/config/layer relationships. The workstation create-only compatibility test remains limited to Engine `29.7.2-ce` and Compose `5.6.0`; target Engine 29.1.3 is not in the allowlist. No target deployment or runtime readiness is established.

The CUDA lock SHA-256 remains `68ba66ac4a14ee59ddabd25ce0b5efd25e6e387cb9c1f430b0c4946767d62b14`; it pins the already validated faster-whisper/CTranslate2/CUDA/cuDNN package set. The Dockerfile embeds source revision, base reference and lock identity as inspectable labels, but labels alone are not provenance attestations. For either mode, private validated configuration binds source revision, base manifest digest, lock digest, platform, image identity, model revision/manifest and configuration-set digest. Local mode additionally binds the exact private build-evidence and image-store-evidence file bytes by SHA-256 and checks the approved archive digest. These hashes establish file identity, not the truth of evidence claims or an independent signature. The operator trust boundary is the reviewed private profile and evidence: an authorized operator must verify their provenance and approve them before preparation or deployment. The profile is authoritative for the expected image-store identity; evidence and labels cannot redefine it. A read-only `verify-image` path first validates the private provenance/artifact inputs, then compares Docker inspection of the exact configured identity, platform, non-root user, production `python -m` entrypoint and provenance labels. This checks consistency; it does not turn labels into independent proof.

For local-image mode, select the discriminator and artifact identity kind explicitly in the private profile, remove registry-only `image` and `image_reference_verified` fields, and supply the expected store-reported `image_id`, build-evidence digest, archive digest, and image-store-evidence digest. `docker_config_digest` is valid only where the observed store reports that config identity; `containerd_oci_manifest` requires a unique target image record and raw manifest evidence whose digest and config/layer descriptors match the approved identity. Layer-content verification is represented in the pinned image-store evidence; the offline validator does not fetch blobs from a remote or target containerd store. Evidence collection and approval are operator trust-boundary steps, not independent signature verification. There is no mutable-tag fallback. Before preparing/rendering or any separately approved creation, supply all inputs explicitly:

The one-time operator collector for target containerd association and content-store observations is documented in [stt-image-store-evidence.md](stt-image-store-evidence.md). It is diagnostic-only, uses explicit socket, namespace and Docker context values, and does not change the deployment contract or compatibility policy. Do not run it without separate target-execution authorization.

```sh
.venv/bin/python scripts/stt_deployment_profile.py verify-image \
  --profile private/deployment/cuda-stt-initial/profile.yaml \
  --application-config private/deployment/cuda-stt-initial/application.yaml \
  --deployment-config private/deployment/cuda-stt-initial/deployment.yaml \
  --worker-config private/deployment/cuda-stt-initial/worker.yaml \
  --build-evidence private/image-build-a2-20261018-01/build-result.json \
  --image-archive private/results/c6b-image-transfer-20261018-01/stt-cuda-image.tar \
  --image-store-evidence private/evidence/image-store-evidence.json
```

The check is read-only: it runs Docker Engine/Compose version queries and `docker image inspect` for the exact configured ID; it never pulls or builds. Local mode is currently accepted only for Engine `29.7.2-ce` and Compose `5.6.0`. Registry mode remains governed by the existing repository-qualified immutable digest and verified image-ID relationship.

After a separately authorized Compose create operation, but before any start authorization, inspect the full ID returned by Compose and run the read-only check (with the same private config and evidence arguments shown above):

```sh
.venv/bin/python scripts/stt_deployment_profile.py verify-container \
  --profile private/deployment/cuda-stt-initial/profile.yaml \
  --application-config private/deployment/cuda-stt-initial/application.yaml \
  --deployment-config private/deployment/cuda-stt-initial/deployment.yaml \
  --worker-config private/deployment/cuda-stt-initial/worker.yaml \
  --build-evidence private/image-build-a2-20261018-01/build-result.json \
  --image-archive private/results/c6b-image-transfer-20261018-01/stt-cuda-image.tar \
  --image-store-evidence private/evidence/image-store-evidence.json \
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

For a separately authorized deployment, use the same reviewed env file and Compose file pair for every command. Resolve the project name from the validated profile/env file and record the exact container ID before lifecycle actions. Local-image mode requires a create/inspect gate before start; do not use `compose up` because it combines creation and startup and would bypass the operator-enforced image-ID check. These commands are blocked until the target Engine compatibility policy, model access, private configuration and resource review are resolved. They were not run as part of this preparation:

Set `STT_STOP_GRACE_PERIOD_SECONDS` in the operator shell from the reviewed deployment profile value; do not substitute an unreviewed literal.

```sh
docker compose --env-file private/deployment/cuda-stt-initial/stt-cuda.compose.env \
  -f deployments/compose/compose.yaml \
  -f deployments/compose/compose.stt-cuda.yaml \
  --profile cuda create --no-build --pull never stt

mapfile -t STT_CONTAINER_IDS < <(docker compose --env-file private/deployment/cuda-stt-initial/stt-cuda.compose.env \
  -f deployments/compose/compose.yaml \
  -f deployments/compose/compose.stt-cuda.yaml \
  --profile cuda ps --all --quiet stt)
test "${#STT_CONTAINER_IDS[@]}" -eq 1
STT_CONTAINER_ID="${STT_CONTAINER_IDS[0]}"

# Validate this exact created container before authorizing start.
.venv/bin/python scripts/stt_deployment_profile.py verify-container \
  --profile private/deployment/cuda-stt-initial/profile.yaml \
  --application-config private/deployment/cuda-stt-initial/application.yaml \
  --deployment-config private/deployment/cuda-stt-initial/deployment.yaml \
  --worker-config private/deployment/cuda-stt-initial/worker.yaml \
  --build-evidence private/image-build-a2-20261018-01/build-result.json \
  --image-archive private/results/c6b-image-transfer-20261018-01/stt-cuda-image.tar \
  --image-store-evidence private/evidence/image-store-evidence.json \
  --container-id "$STT_CONTAINER_ID"

# Run only after verify-container succeeds.
docker start "$STT_CONTAINER_ID"
docker inspect --format '{{.State.Health.Status}}' "$STT_CONTAINER_ID"
test "$(docker inspect --format '{{.State.Health.Status}}' "$STT_CONTAINER_ID")" = healthy

# Readiness is a separate gate from Docker /healthz liveness.
docker compose --env-file private/deployment/cuda-stt-initial/stt-cuda.compose.env \
  -f deployments/compose/compose.yaml \
  -f deployments/compose/compose.stt-cuda.yaml \
  --profile cuda exec -T stt python -c \
  'import os, urllib.request; url="http://127.0.0.1:" + os.environ["STT_LISTEN_PORT"] + "/readyz"; print(urllib.request.urlopen(url, timeout=float(os.environ["STT_HEALTHCHECK_PROBE_TIMEOUT_SECONDS"])).read().decode())'

# Example one-request private HTTP check. Verify the approved audio checksum
# first. The bytes are piped to a client process inside stt, so no host port or
# additional service is required. The client prints metadata only, never text.
sha256sum -c private/results/audio-before.sha256
cat private/audio/russian.m4a | docker compose \
  --env-file private/deployment/cuda-stt-initial/stt-cuda.compose.env \
  -f deployments/compose/compose.yaml \
  -f deployments/compose/compose.stt-cuda.yaml \
  --profile cuda exec -T stt python -c '
import json, math, os, sys, urllib.error, urllib.request, uuid
from services.stt.config import load_application_config
config = load_application_config("/config/stt-application.yaml")
limit = config.admission.max_upload_bytes
audio = sys.stdin.buffer.read(limit + 1)
if not audio or len(audio) > limit:
    raise SystemExit("approved audio is empty or exceeds configured upload limit")
boundary = "speech-platform-" + uuid.uuid4().hex
marker = boundary.encode("ascii")
body = (b"--" + marker + b"\r\n" +
        b"Content-Disposition: form-data; name=\"audio\"; filename=\"russian.m4a\"\r\n" +
        b"Content-Type: audio/mp4\r\n\r\n" + audio + b"\r\n--" + marker + b"\r\n" +
        b"Content-Disposition: form-data; name=\"language\"\r\n\r\nauto\r\n--" + marker + b"\r\n" +
        b"Content-Disposition: form-data; name=\"timestamps\"\r\n\r\ntrue\r\n--" + marker + b"--\r\n")
url = "http://127.0.0.1:" + os.environ["STT_LISTEN_PORT"] + "/internal/v1/transcriptions"
request = urllib.request.Request(
    url, data=body,
    headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
             "X-Request-Timeout-Ms": str(int(config.admission.request_timeout_seconds * 1000))})
try:
    with urllib.request.urlopen(request, timeout=config.admission.request_timeout_seconds + 5) as response:
        result = json.loads(response.read())
except urllib.error.HTTPError as error:
    print(json.dumps({"status": error.code, "result": "http_error"}))
    raise SystemExit(1) from None
segments = result.get("segments")
if response.status != 200 or result.get("language") != "ru" or not isinstance(segments, list) or not segments:
    raise SystemExit("HTTP response did not meet the smoke-test contract")
maximum = config.audio_limits.max_duration_seconds
if any(not math.isfinite(s["start"]) or not math.isfinite(s["end"]) or s["start"] < 0 or s["end"] < s["start"] or s["end"] > maximum for s in segments):
    raise SystemExit("segment timestamps are outside configured bounds")
print(json.dumps({"status": response.status, "language": result["language"], "segment_count": len(segments), "timestamps_valid": True}))'

# Roll back only the exact STT container created above; preserve the image,
# model and other Compose projects. After stop, verify the exact container is
# exited and review the sanitized supervisor shutdown evidence. Remove it only
# after child shutdown is confirmed; container exit alone does not prove that.
docker stop --time "$STT_STOP_GRACE_PERIOD_SECONDS" "$STT_CONTAINER_ID"
docker inspect --format '{{.State.Running}} {{.State.ExitCode}}' "$STT_CONTAINER_ID"
test "$(docker inspect --format '{{.State.Running}}' "$STT_CONTAINER_ID")" = false
# Operator gate: confirm the preserved supervisor report says child termination
# was confirmed before proceeding with exact-container removal.
docker rm "$STT_CONTAINER_ID"
```

Rollback uses the preserved prior version of the profile, generated env file, app/deployment/worker configs, image digest and model release as one release set. Re-run `prepare` and rendered-Compose validation against that prior set before recreating only the `stt` service in the same explicitly named project. Do not use `compose down`, broad container cleanup, mutable tags, process-wide kills, or Docker/GPU resets. If stop, child exit, or exact resource identity cannot be confirmed, preserve evidence and escalate instead of trying a second cleanup target.

The command sequence above is an operator procedure proposal, not authorization to start or stop anything. C.6B covers startup/readiness/bounded shutdown; C.6C separately covers one private-path request and a rollback rehearsal.

## Deferred to C.6B and C.6C

**C.6B build/runtime evidence:** immutable base provenance and approved build inputs; production image identity (distinct local image ID and repository digest); dependency inventory matching the lock; actual mounted file access and verifier result; host UUID to container CUDA-device mapping; GPU visibility; model load; `/healthz`/`/readyz` transitions; enforced CPU/RAM/PID limits; exact child/container shutdown; operator health checks; and no changes to Ollama/Dify. The current R1 work supplies only the offline production image specification and rejection checks; it establishes none of this runtime evidence.

**C.6C runtime evidence:** one approved request through the private persistent worker path; response validation and sanitized logs; exact release rollback and re-readiness; project resource inventory; and postflight shared-service health.

Neither phase establishes concurrency capacity, sustained performance, exact peak VRAM, real CUDA OOM recovery or active GPU workload coexistence unless separately authorized and measured. Overall M02 remains incomplete.

## M01E existing artifact and concurrent-start integration

The existing digest-named release can be reused in place. Verification opens
the manifest and model files for reading, checks their hashes and inspects
ownership/modes; it does not create, download, rename, chmod, chown, or remove
anything in the release. Keep `host_release_root` pointed at that exact
digest-named directory and retain the configured reader group. The container
mount is read-only. Do not run `model-fetch` for this release: if the checked
release is valid, `prepare` and `preflight-host` both verify and reuse it.

The normal deployment account may be unable to traverse/enumerate the model
store parent. Run validation and private environment generation as that same
account with the configured model-reader group as its primary group. Resolve
the group name from the numeric GID in the private profile; do not copy a GID
into tracked application code. Example after setting these shell variables
from the private profile and local account:

```sh
DEPLOYMENT_USER="$(id -un)"
MODEL_READER_GROUP="$(getent group "$MODEL_READER_GID" | cut -d: -f1)"
test -n "$MODEL_READER_GROUP"
sudo -u "$DEPLOYMENT_USER" -g "$MODEL_READER_GROUP" -- \
  .venv/bin/python scripts/stt_deployment_profile.py prepare \
  --profile private/deployment/cuda-stt-initial/profile.yaml \
  --application-config private/deployment/cuda-stt-initial/application.yaml \
  --deployment-config private/deployment/cuda-stt-initial/deployment.yaml \
  --worker-config private/deployment/cuda-stt-initial/worker.yaml \
  --build-evidence private/image-build-a2-20261018-01/build-result.json \
  --image-archive private/results/c6b-image-transfer-20261018-01/stt-cuda-image.tar \
  --image-store-evidence private/evidence/image-store-evidence.json \
  --output-env private/deployment/cuda-stt-initial/stt-cuda.compose.env
```

This preserves the deployment user's ownership of private output and grants
the process only the model-reader group's existing read/traverse access. It
does not alter release ownership, modes, or group membership. If the group
cannot be selected for the deployment account, stop and have the host
administrator resolve access without changing the historical artifact.

Immediately before any separately authorized CUDA start, repeat the same
group-context validation with the `preflight-host` subcommand and the same
profile/config/evidence arguments. It reads `nvidia-smi`, checks the configured
physical GPU UUID and verifies current free VRAM meets
`minimum_free_gpu_bytes_before_load`. A low or mismatched result blocks
startup. The application repeats the free-memory admission check before model
loading; neither observation reserves VRAM, so rerun preflight immediately
before startup and stop if another workload changes the headroom. This check
is read-only and does not start a container.

The deployment profile's Compose project name must be unique on the host.
Before startup, inspect `docker compose ls` and the rendered Compose project;
stop if the new project name is already active. The CUDA overlay publishes no
host ports, mounts its own private configuration files and the existing model
release read-only, and selects only the configured GPU. Do not use the current
operational STT project's name or its host paths. Ollama, Dify and the current
STT project remain outside this deployment's Compose commands.

### Make deployment interface

`make plan SERVICE=stt` and `make install SERVICE=stt` select the `regular`
profile by default. Set `PROFILE=experimental` to select the separate
`private/deployment/stt-cuda-experimental/` profile and its three configs;
`PROFILE=regular` selects `private/deployment/stt-cuda/`. Unknown profile names
are rejected by Make before the deployment command runs. Each selection also
uses its own `compose.env` path. `PLATFORM_RELEASE` selects the tracked release
manifest. The profile's GHCR digest, platform, model revision and manifest
digest must match that release exactly; local image-ID mode is not accepted by
these Make targets.

Run `make plan` as the deployment account with the configured model-reader
group as its primary group. It validates the release and model bytes, performs
the read-only GPU preflight, renders Compose and checks the chosen project
namespace, and verifies the locally available image against the configured
GHCR digest, image ID, platform and provenance labels. The exact digest image
must already be present locally; `plan` does not pull images, write
`compose.env`, create directories, change Docker/GPU state, or alter
installation records. Compose interpolation uses validated values in the child
process environment and `/dev/null` as its env-file source. Admission shortfalls
are printed as `BLOCKED` with free memory, configured threshold and reasons.
`make install` independently repeats strict validation and image/model/project
checks, then re-reads GPU identity and free VRAM immediately before the only
mutating command: `docker compose up -d --no-build
--pull never stt` scoped to the configured project and CUDA overlay. It does
not issue `down`, `rm`, prune, build, or commands against other Compose
projects. Existing containers in the chosen project are reusable only when
they are the `stt` service with the exact immutable image and matching
deployment identity labels; a different service or identity blocks install.
The install can create or replace resources belonging to its own configured
project, so review `make plan` output and the selected project name before a
separately authorized installation.

### M01E experimental coexistence candidate

The private candidate under ignored
`private/deployment/stt-cuda-experimental/` uses project
`speech-platform-stt-cuda-m01e-exp-v012`, loopback Gateway profile binding
`127.0.0.1:18083` to container port 8080, and worker port 8082. It uses the
same pinned v0.1.2 CUDA image and digest-addressed read-only model release,
selects GPU index 0 by the configured UUID, and adds model-reader GID 988 as a
supplementary group. Profile and service configs are separate private copies;
the STT worker port is not published.

Threshold evidence: the recorded C.4 three-request sample observed a
device-wide maximum of 2,795,962,368 bytes (about 2,667 MiB). Before that run,
14,909 MiB was free on a 15,360 MiB GPU, or about 451 MiB used. The sampled
increase was about 2,216 MiB. The current user-reported baseline is about
2,216 MiB used and 12,694 MiB free. A candidate 4,096 MiB admission gate would
allow the observed approximate 2,216 MiB worker increase plus about 1,880 MiB
additional headroom. This margin is proposed, not measured reserve capacity.
The old sample was device-wide, sampled once per second and not process
attributed; it is not an exact peak. Two-worker use and behavior under active
Ollama/Dify load are unmeasured. The user approved the 4,096 MiB threshold for
the experimental profile only. The regular profile retains its 14,336 MiB
threshold, which blocks admission at the observed 12,694 MiB free level. The
experimental threshold admitted the read-only plan at that observation; it
does not establish runtime coexistence or reserve future GPU headroom.

#### Later controlled coexistence test — approval required

1. Capture baseline STT health and GPU memory.
2. Confirm the experimental Compose project and port are isolated.
3. Verify the experimental admission threshold and record the approved value.
4. Start the new CUDA STT container only after explicit approval.
5. Wait for readiness.
6. Execute one bounded transcription request.
7. Capture GPU memory use and relevant sanitized logs.
8. Confirm the original STT remains healthy.
9. Verify Ollama and Dify remain unaffected.
10. Stop the experimental deployment only when explicitly authorized, then
    confirm the original baseline remains healthy.

This ten-step procedure was documented during M01E Phase A. The user later
reported successful experimental install/readiness, one real transcription,
continued health of original and experimental STT, and repeated-install
idempotency; those bounded results are recorded in [M01E verification](../milestones/M01E/verification.md).
Parallel inference stress testing was not performed, so concurrent inference
capacity and sustained headroom remain unverified and overall M01E remains
open. No current container lifecycle operation is implied by this historical
acceptance record.
