# M01E-F fresh-install and model-staging rehearsal

> Historical M01E evidence only: the profile-based deployment installer used
> for this rehearsal has been retired. Its commands below are not supported
> for current installation. Use the [current installation guide](installation.md).

Status: the approved M01E-F2 fresh installation completed and passed on
2026-10-19. The fresh containers/networks and staged model remain in place;
cleanup is not authorized by this record. Exact F2 execution evidence is in
[M01E verification](../milestones/M01E/verification.md). M01E remains open.

## Isolated rehearsal inputs

- Compose project: `speech-platform-m01e-fresh-v012`
- Enabled services: Gateway, STT and TTS
- Gateway publication: `127.0.0.1:18084 -> 8080/tcp`
- Release: `releases/voiceservice-v0.1.2.yaml`
- Model store: `/var/tmp/speech-platform-m01e-fresh-v012/model-store`
- Model reader group: `stt-model-reader` (GID 988)
- Model staging owner: UID 1000, primary GID 988
- CUDA worker: UID/GID `65532:65532`, supplementary GID 988, read-only
  `/models` bind mount

The model store is on `/var/tmp` because the worker cannot traverse the host
home and repository parents to reach a store under `private/`. It is a separate
empty store, owned by `master:stt-model-reader`, mode `2750`; `/var/tmp` is
host-managed temporary storage, so confirm it remains available before a later
staging run. The store parent and store root must both retain GID 988. Do not
change permissions on the existing `/srv/speech-platform/models` store.

All files below are ignored private host configuration, independent from the
experimental project's mutable files:

- `private/deployment/m01e-fresh-v012/enabled-services.yaml`
- `private/deployment/m01e-fresh-v012/services.yaml`
- `private/deployment/m01e-fresh-v012/gateway.yaml`
- `private/deployment/m01e-fresh-v012/tts.yaml`
- `private/deployment/m01e-fresh-v012/profile.yaml`
- `private/deployment/m01e-fresh-v012/stt-application.yaml`
- `private/deployment/m01e-fresh-v012/stt-deployment.yaml`
- `private/deployment/m01e-fresh-v012/stt.yaml`
- `private/deployment/m01e-fresh-v012/compose.env`

The profile and service-selection files are mode `0600`; service config files
are mode `0640`, owned by UID 1000/GID 988; the private directory is mode
`0700`. The generated environment is mode `0600`.

## Model staging procedure (not run)

The v0.1.2 release pins the Hugging Face repository
`dropbox-dash/faster-whisper-large-v3-turbo` at immutable revision
`0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`. Its manifest SHA256 is
`86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6` and
specifies five files totaling 1,621,665,983 bytes. The provisioner validates
the release and manifest first, downloads HTTPS content at that pinned
revision, enforces manifest sizes and per-file SHA256 values, verifies the
complete artifact, and atomically renames the verified staging directory to
the digest-named release directory. A valid existing digest directory is
verified and reused without redownload; corrupt content fails closed.

Before a separately authorized download, verify the store is still empty and
its ownership/modes are exact:

```sh
stat -c '%u:%g %a %n' \
  /var/tmp/speech-platform-m01e-fresh-v012 \
  /var/tmp/speech-platform-m01e-fresh-v012/model-store
find /var/tmp/speech-platform-m01e-fresh-v012/model-store \
  -mindepth 1 -maxdepth 1 -print
```

Expected: both directories `1000:988 2750`, and `find` prints nothing. Then,
only after download approval, run the existing content-addressed provisioner
API under the reader group. This explicit invocation selects the profile's
owner/group and `2750` directory / `0640` file policy; the standalone
`model-fetch` target uses private `0700/0600` defaults and is not suitable for
the worker-readable release:

```sh
sg stt-model-reader -c 'PYTHONPATH=. .venv/bin/python -' <<'PY'
import os
from pathlib import Path
import yaml
from scripts.model_artifacts import download_from_huggingface, provision_models
from scripts.release_manifest import REPOSITORY_ROOT, load_release

profile_path = Path("private/deployment/m01e-fresh-v012/profile.yaml")
profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
store = Path("/var/tmp/speech-platform-m01e-fresh-v012/model-store")
access = profile["artifact_access"]
if profile["project_name"] != "speech-platform-m01e-fresh-v012":
    raise SystemExit("refusing unexpected fresh project identity")
if os.geteuid() != access["artifact_owner_uid"]:
    raise SystemExit("run as the configured model owner")
if os.getegid() != access["supplementary_read_gid"]:
    raise SystemExit("run with stt-model-reader as the primary group")
for path in (store.parent, store):
    info = path.lstat()
    if path.is_symlink() or not path.is_dir():
        raise SystemExit("model store path must be a real directory")
    if (info.st_uid, info.st_gid, info.st_mode & 0o7777) != (
        access["artifact_owner_uid"], access["supplementary_read_gid"], 0o2750
    ):
        raise SystemExit("model store ownership or mode changed")
if any(store.iterdir()):
    raise SystemExit("initial fresh model store is not empty; stop for review")
release = load_release("releases/voiceservice-v0.1.2.yaml", REPOSITORY_ROOT)
models = release["services"]["stt"]["required_model_artifacts"]
if len(models) != 1 or (
    models[0]["revision"], models[0]["manifest_sha256"]
) != (
    profile["model"]["revision"], profile["model"]["manifest_sha256"]
):
    raise SystemExit("release model identity does not match the private profile")
def download(model, relative_path, destination, maximum_bytes):
    download_from_huggingface(model, relative_path, destination, maximum_bytes)
results = provision_models(
    {**release, "services": {"stt": release["services"]["stt"]}},
    store,
    REPOSITORY_ROOT,
    download,
    directory_mode=0o2750,
    file_mode=0o640,
    expected_owner_uid=access["artifact_owner_uid"],
    expected_group_gid=access["supplementary_read_gid"],
)
for result in results:
    print(f"{result.status}: {result.artifact_id} -> {result.directory}")
PY
```

After staging, verify without mutation and regenerate the environment with full
artifact/permission verification before another plan:

```sh
sg stt-model-reader -c 'make model-check MODEL_STORE=/var/tmp/speech-platform-m01e-fresh-v012/model-store PLATFORM_RELEASE=releases/voiceservice-v0.1.2.yaml PYTHON=.venv/bin/python'
sg stt-model-reader -c 'PYTHONPATH=. .venv/bin/python scripts/stt_deployment_profile.py prepare --profile private/deployment/m01e-fresh-v012/profile.yaml --application-config private/deployment/m01e-fresh-v012/stt-application.yaml --deployment-config private/deployment/m01e-fresh-v012/stt-deployment.yaml --worker-config private/deployment/m01e-fresh-v012/stt.yaml --output-env private/deployment/m01e-fresh-v012/compose.env'
```

The CUDA Compose definition supplies `group_add: [988]` and mounts the
profile's digest directory at `/models:ro`; the provisioned artifact files are
not writable by the worker. A later `make plan` must report `READY` before any
separately approved install.

## Read-only fresh-project plan

Run as the model-reader group so all profile checks can inspect the model
release once it exists:

```sh
sg stt-model-reader -c 'make plan SERVICE= ENABLED_SERVICES_CONFIG=private/deployment/m01e-fresh-v012/enabled-services.yaml SERVICES_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/services.yaml GATEWAY_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/gateway.yaml TTS_DEPLOYMENT_CONFIG=private/deployment/m01e-fresh-v012/tts.yaml STT_DEPLOYMENT_DIR=private/deployment/m01e-fresh-v012 PROFILE=experimental PYTHON=.venv/bin/python'
```

The explicit `STT_DEPLOYMENT_DIR` is required because the Makefile's regular
and experimental profiles otherwise select the existing deployment paths.
The actual preparation plan rendered and validated the exact Compose project,
but was blocked by the deliberately absent model artifact. Do not start
containers or pull images until the model is staged and a subsequent plan is
`READY`.

## Exact-project cleanup design (not run)

Cleanup requires a separate approval after all checks below are reviewed. Do
not run `compose down`, `docker system prune`, `docker network prune`, volume
pruning, broad name filters, or cleanup against another project. Never remove
an image or model store that is not owned by this rehearsal.

1. Confirm the configured project name in both private `services.yaml` and
   `profile.yaml` is exactly `speech-platform-m01e-fresh-v012`. Confirm the
   expected Gateway port is `18084` and the selected services are exactly
   `gateway`, `stt`, and `tts`.
2. Read-only inventory the exact Compose label and inspect every listed
   container. Every container must have label
   `com.docker.compose.project=speech-platform-m01e-fresh-v012`, one of the
   three allowed service labels, and an expected v0.1.2 digest image. Abort if
   a container has missing/conflicting labels or belongs to another project.
3. Read-only inventory networks with that same Compose project label. Inspect
   each network ID; require the project label and only the expected generated
   names `speech-platform-m01e-fresh-v012_gateway_publish`,
   `speech-platform-m01e-fresh-v012_stt_private`, and
   `speech-platform-m01e-fresh-v012_tts_private`. Confirm attachments contain
   only the identified rehearsal containers and the approved Gateway/worker
   topology. Abort on unexpected or external attachments.
4. Confirm the model-store path resolves exactly to
   `/var/tmp/speech-platform-m01e-fresh-v012/model-store`; confirm its owner,
   group and mode are `1000:988 2750`, its digest child is exactly the
   configured manifest SHA256, all descendants are owned `1000:988`,
   directories are `2750`, files are `0640`, and no symlinks or extra releases
   exist. Run the read-only `make model-check` command above and require PASS.
5. Only after the project, container, network and model-store inventories all
   pass and the user separately approves cleanup: stop only the reviewed exact
   container IDs with their configured grace period; verify each is stopped;
   remove only those exact container IDs; remove only the reviewed exact
   network IDs after Docker confirms they have no attachments; then remove
   only the reviewed digest child and only if the store ownership and
   single-release checks still match. Keep the empty store parent unless its
   ownership is rechecked and its exact removal is separately included in the
   approval. Re-run and reconfirm the complete identity/membership/store gate
   immediately before each destructive category. Abort on any changed
   identity or membership.

Read-only inventory commands for the later cleanup review:

```sh
docker ps -a --no-trunc --filter label=com.docker.compose.project=speech-platform-m01e-fresh-v012
docker network ls --no-trunc --filter label=com.docker.compose.project=speech-platform-m01e-fresh-v012
```

After review and separate approval, substitute only the full IDs recorded by
the reviewed inventories; do not substitute names or broad filters:

```sh
docker stop --time <inspected-stop-time-seconds> <reviewed-container-id> [<reviewed-container-id> ...]
docker inspect --format '{{.Id}} {{.State.Running}} {{index .Config.Labels "com.docker.compose.project"}} {{index .Config.Labels "com.docker.compose.service"}}' <reviewed-container-id> [<reviewed-container-id> ...]
docker rm <reviewed-stopped-container-id> [<reviewed-stopped-container-id> ...]
docker network inspect <reviewed-network-id> [<reviewed-network-id> ...]
docker network rm <reviewed-detached-network-id> [<reviewed-detached-network-id> ...]
test "$(readlink -f /var/tmp/speech-platform-m01e-fresh-v012/model-store)" = "/var/tmp/speech-platform-m01e-fresh-v012/model-store"
stat -c '%u:%g %a %n' /var/tmp/speech-platform-m01e-fresh-v012/model-store
rm -rf --one-file-system -- /var/tmp/speech-platform-m01e-fresh-v012/model-store/86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6
```

The stop time and every container/network ID above must come from that
rehearsal's inspected configuration and the just-confirmed inventory. Before
model removal, repeat the full ownership, mode, digest-child, descendant and
`make model-check` checks; the shown `stat` line alone is not sufficient.

No cleanup command is authorized or executed in this preparation phase.
