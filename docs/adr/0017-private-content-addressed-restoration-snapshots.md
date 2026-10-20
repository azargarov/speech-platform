# ADR 0017: Private content-addressed restoration snapshots

- Status: architecture accepted in principle by operator on 2026-10-20;
  capture execution remains separately gated
- Date: 2026-10-20
- Scope: M01F-B3.1 restoration evidence for one Compose project

## Context and current evidence

The B3.1 planner independently checks expected deployment contracts against
Docker observations. STT runtime identity is the Compose service configuration
hash: the collector reads `com.docker.compose.config-hash` from the running
container and independently obtains the expected hash with `docker compose
config --hash stt` over validated inputs. The collector also checks the STT
configuration-set identity independently. The earlier STT identity finding is
resolved; the target's remaining adoption findings are missing restoration
inputs for Gateway, STT and TTS.

The private files currently present are mutable working inputs. Their presence
does not prove that the exact bytes needed for later reconstruction are
retained. Private YAML and `compose.env` are not presumed secret-free. No
approved secret-reference provider or resolver is established in this repo.
The target model store currently lives at
`/var/tmp/speech-platform-m01e-fresh-v012/model-store`; its durable retention
and backup are not established. It remains a blocker for production-quality
rollback assurance and must not be moved or modified by snapshot capture.

## Decision proposed

Use one versioned project snapshot shared by the selected Gateway, STT and TTS
services. Store the canonical manifest by its SHA-256 and each approved file
blob by its own SHA-256:

```text
private/deployment/<deployment>/restoration/
  snapshots/sha256/<manifest-sha256>/manifest.json
  objects/sha256/<file-sha256>
  staging/<capture-id>/                 # incomplete work; never active
```

The active snapshot identity is the manifest digest. A service's configuration
hash and runtime identity remain separate per-service values in the manifest;
neither is compared to, nor substituted with, the project snapshot digest.
All three selected services must refer to the same project snapshot. Snapshot
verification remains read-only. The writer is implemented as a library API
with injected trusted collectors; this decision does not authorize capture of
real deployment state.

### Input classification

Every captured item must have exactly one classification. The file allowlist
is closed; additional files block capture pending ADR review.

| Logical input | Classification | Requirements |
| --- | --- | --- |
| `enabled-services.yaml`, `services.yaml`, `gateway.yaml`, `tts.yaml` | Non-secret configuration | Strict current schema; unknown keys rejected; complete values retained as private blobs. |
| `profile.yaml`, `stt-application.yaml`, `stt-deployment.yaml`, `stt.yaml` | Non-secret configuration | Strict STT profile, application, deployment and worker validators; unknown keys rejected. |
| `compose.env` | Non-secret configuration | Only the persisted environment allowlist below; canonical encoding and typed values required. Any secret or unknown key blocks. |
| `compose.yaml`, `compose.stt-cuda.yaml`, logical `release.yaml` (source `releases/voiceservice-v0.1.2.yaml` for this deployment) | Non-secret configuration | Exact tracked bytes retained; transitive file and artifact references verified. |
| `render-environment.json` | Non-secret configuration | Canonical, complete effective Compose environment; only the rendered environment allowlist below. |
| `rendered-compose.json` | Non-secret configuration | Canonical `docker compose config --format json` output. Private blob only; public records contain its digest. |
| `image-build-evidence.json`, `image-store-evidence.json` | Non-secret configuration | Optional fixed roles only when local-image mode references them; existing strict evidence validators and exact dependency closure required. |
| Gateway, TTS and CUDA STT OCI images | Immutable artifact reference | Pinned registry/repository plus OCI manifest digest and platform; runtime image ID and provenance independently verified. |
| STT model manifest and every model payload | Immutable artifact reference | Model IDs/revisions, manifest digest and complete payload digests; storage location must be retained and independently verifiable. |
| A future required credential | Secret reference | Only a provider and immutable version-reference syntax approved by a separate decision; no provider is currently approved, so any non-empty list blocks. |
| Passwords, tokens, keys, authorization values, private key material, audio, transcripts, logs, mutable references, unknown files/keys | Forbidden sensitive content | Never copied to blobs, manifest, journal or logs. Scan is defense-in-depth; allowlists and strict schemas are authoritative. |

Persisted `compose.env` allowlist (exact, no additions):

```text
SPEECH_BIND_IP SPEECH_LISTEN_PORT SPEECH_PORT STT_APPLICATION_CONFIG
STT_APPLICATION_CONFIG_SHA256 STT_ARTIFACT_GID STT_COMPOSE_PROJECT_NAME
STT_CONFIGURATION_SET_SHA256 STT_CPU_LIMIT STT_CUDA_IMAGE STT_CUDA_LOCK_SHA256
STT_DEPLOYMENT_CONFIG STT_DEPLOYMENT_CONFIG_SHA256 STT_DEPLOYMENT_PROFILE_SHA256
STT_HEALTHCHECK_INTERVAL_SECONDS STT_HEALTHCHECK_PROBE_TIMEOUT_SECONDS
STT_HEALTHCHECK_RETRIES STT_HEALTHCHECK_START_PERIOD_SECONDS
STT_HEALTHCHECK_TIMEOUT_SECONDS STT_HOST_GPU_DEVICE_ID STT_IMAGE_ID
STT_IMAGE_IDENTITY_MODE STT_LISTEN_PORT STT_MEMORY_LIMIT_BYTES STT_MODEL_HOST_ROOT
STT_MODEL_MANIFEST_SHA256 STT_MODEL_REVISION STT_PIDS_LIMIT STT_PLATFORM
STT_SOURCE_REVISION STT_STOP_GRACE_PERIOD_SECONDS STT_WORKER_CONFIG
STT_WORKER_CONFIG_SHA256
```

The effective rendered environment is the persisted allowlist plus exactly:

```text
SERVICE_PROJECT_NAME SERVICE_CONFIG_READER_GID GATEWAY_IMAGE TTS_IMAGE
GATEWAY_CONFIG TTS_CONFIG GATEWAY_CONFIG_SHA256 TTS_CONFIG_SHA256
GATEWAY_MEMORY GATEWAY_CPUS GATEWAY_PIDS TTS_MEMORY TTS_CPUS TTS_PIDS
GATEWAY_DEPLOYMENT_IDENTITY_SHA256 TTS_DEPLOYMENT_IDENTITY_SHA256
```

Paths are absolute, normalized and role-checked; image and model references are
immutable; digest, revision, numeric, memory, project and loopback-address
values are validated. The allowlists describe the current deployment
contract, not permission to persist arbitrary environment values.

### Restoration completeness and host bindings

The full snapshot file set is the allowlist above. Compose transitively uses
the base Compose file and CUDA overlay, `compose.env`, enabled-service and
service-profile inputs, Gateway/TTS config paths, STT profile/application/
deployment/worker paths, release pins and the model host root. The captured
effective environment and canonical rendered Compose prove the substitutions
and resolved service definitions. Capture must execute the existing strict
loaders for service, Gateway, TTS, STT profile, STT application and STT
deployment configuration. It must verify rendered service identities against
the independently observed container project/service labels and Compose hashes.

Host-specific paths are retained exactly in private configuration blobs and
rendered Compose. They are not placed in public journal metadata. A restore on
the same host must bind those exact paths and prove they resolve to the
captured bytes/artifacts. A different path mapping changes the runtime
contract and cannot be represented as exact restoration; it requires a new
deployment plan. Any missing transitive file or binding blocks eligibility.
The model manifest and complete model payload set are immutable references,
not copied by snapshot capture. Since the current model root is under
`/var/tmp`, an operator must establish an approved durable retention and backup
boundary before a retained snapshot can claim restoration completeness.

The STT configuration-set identity can also include local image build and
image-store evidence files when the validated STT profile selects local-image
identity mode. If either path is present in validated inputs, its logical role,
exact bytes and digest become required members of that snapshot's dependency
closure; the writer must not silently omit it or treat a path string as a
retained artifact. The manifest's file-role schema therefore needs an
explicit conditional extension for these two known roles, with strict
allowlisting and no arbitrary filenames. They are not part of the current
registry-digest target's fixed file set.

### Manifest schema version 3

The canonical UTF-8 JSON manifest has exactly these keys:

```text
schema_version, project_name, source_revision, source_git_blob_ids,
selected_services, optional_file_roles, files,
artifacts_by_service, secret_versions_by_service,
rendered_compose_sha256, compose_service_hashes,
configuration_sha256_by_service, runtime_identity_sha256_by_service,
host_bindings_sha256, docker_engine_version, compose_version
```

`schema_version` is integer `3`; `source_revision` is the explicitly approved
full Git commit identity for the tracked Compose base, CUDA overlay and
release descriptor. `source_git_blob_ids` maps exactly those three logical
roles to their committed Git object IDs. The capture adapter verifies the
commit, clean index and worktree, tree blob IDs, current bytes and captured
bytes before and after collection; these identities are retained in the
canonical manifest. Selected services are the sorted complete set
`gateway`, `stt`, `tts`. `optional_file_roles` is a sorted subset of the
two known local build/image-store evidence roles, exactly when required by
validated STT profile dependencies. `files` has exactly the fixed allowlisted
logical filenames plus only profile-required `image-build-evidence.json`
and/or `image-store-evidence.json` roles, each mapping to
`{sha256, size_bytes, classification}` where
classification is `non_secret_configuration`. Artifact, Compose, configuration
and runtime identity maps have exactly those three service keys. Artifact
references must be immutable and match the pinned release and verified model
inventory. Secret reference lists must be empty until an approved resolver
exists; if one is later approved, it must define provider, immutable version,
scope and restore-time resolution without exposing the value to this store.
Manifest metadata includes no filesystem paths or secret values. Service
configuration hashes, runtime identities, rendered Compose digest and host
binding digest are distinct identities.

`compose.env` uses sorted keys, one JSON-quoted value per line, UTF-8 and a
final newline. The two JSON evidence files and manifest use deterministic
compact canonical JSON. Every object is named by lowercase SHA-256 of its
exact bytes. The snapshot directory name is the SHA-256 of exact manifest
bytes.

### Capture protocol (implemented writer; real capture separately gated)

1. Validate project identity, approved file/environment allowlists, every
   strict config schema, artifact references, private storage ancestry and
   permissions. Reject unknown dependencies, secrets, symlinks and unsupported
   filesystems before staging.
2. Acquire the shared B2 `ProjectLock`; do not initialize B1 installed state.
3. Under the lock, re-read project/config identities and fresh Docker evidence:
   project/service labels, container IDs, immutable image IDs/references,
   Compose hashes, mounts, security identity and actual readiness. Recompute
   expected hashes independently. External Docker clients can bypass this
   lock, so repeat the observation after capture and abort if it changed.
4. Create owner-only staging with exclusive creation. Do not modify live
   Compose/configuration files. Open source files without following symlinks;
   record inode/device/size and digest, copy only allowlisted bytes, and
   recheck source identity and digest after copying. A change aborts capture.
5. Verify all staged blob digests, file sizes, strict schemas, immutable image
   provenance, model manifest and every model artifact. No pulls or downloads
   are part of this operation.
6. Render Compose from the captured inputs and compare canonical output,
   service set, service hashes, paths and identities to the independently
   observed runtime. Any discrepancy blocks activation.
7. Publish verified immutable blobs first, then publish the completed
   manifest last with atomic no-replace semantics. Fsync file contents and
   containing directories before reporting success. A manifest is the sole
   activation record; an incomplete stage is never eligible.
8. Preserve all prior snapshots. Never automatically delete abandoned staging
   or perform garbage collection. Diagnose abandoned staging and remove it
   only through an explicitly approved maintenance action.

`scripts.restore_snapshot.capture_snapshot` implements this protocol as a
narrow writer API. The caller supplies a closed role-to-path map and approved
repository/private source roots; the writer refuses paths outside those roots. Its trusted
adapters must provide strict validation from captured bytes (project/service
selection, per-service image IDs/platforms and configuration/runtime hashes,
artifact refs, empty secret refs, and the exact optional evidence roles), a
Compose render from those captured bytes, fresh runtime observations, and
artifact verification using existing release/image/model helpers. Runtime
observations must identify the exact project and service labels, container and
image IDs/references, platform, Compose/configuration/runtime hashes, health,
readiness and a complete expected-contract match. The writer compares these
identities and hashes itself before publication. It does not invoke Docker or
validators through an implicit global command runner.

The writer and B1 `StateStore` now share `scripts/durable_files.py` for private
directory creation and durable file publication. The writer uses only
no-replace publication; B1 retains its existing replace behavior for its
current pointer. Neither caller instantiates `StateStore` for snapshots. The
writer does not initialize B1 state, create deployment operation records, or
perform lifecycle actions. Abandoned staging is retained for operator
diagnosis; staging is not automatically cleaned up.

`scripts.snapshot_capture_adapter` is the production boundary for this host.
It fixes the private deployment input map, validates the enabled dependency set
and release identity before capture, and supplies callbacks backed by the
existing baseline collector, service probes, registry-image verification and
complete local model checker. Captured base and CUDA Compose bytes are staged
in a private temporary directory and rendered with the existing Compose
project directory so relative references retain their meaning. Captured
private YAML remains in memory; the adapter does not create temporary copies
of those files. Group-writable tracked inputs are permitted only after
`scripts.tracked_source_integrity` validates the exact pinned commit and blobs,
clean Git content, trusted ownership of every path ancestor, ACL state,
single-link regular files, and NSS membership for each writable group.
`scripts.restore_snapshot` repeats this proof before reading and after staging;
it compares `ctime`, inode, bytes and Git blob identity. Private deployment
configuration permission validation is unchanged.

The production entry point is implemented but real capture has not been
authorized or invoked. Tracked inputs are bound to an explicit approved Git
commit and their current `0664` modes are accepted only while ownership,
ancestor, ACL, link and NSS membership evidence remains valid. The current
`/var/tmp` model-store binding remains a separate rollback durability blocker.

### Filesystem and retention contract

Storage remains below the root-private `private/deployment/<deployment>`
boundary. The deployment root, restoration root, staging, snapshots, objects
and digest directories are owned by the service operator and mode `0700`;
regular manifests/blobs are mode `0600`. Reject symlink components, symlink
files, special files, wrong owners/modes and hard links (`st_nlink != 1`).
Use no-follow opens and verify inode identity after open. Publication uses
exclusive temporary files, file fsync, atomic no-replace publication and
directory fsync; an existing digest is accepted only after byte verification.
Verify every manifest and blob digest before every planning/restoration use.
Only local filesystems with the durability semantics supported by B1 may be
used; this must be checked by the writer. Backups must preserve owner, mode,
content and directory durability and remain within an approved private backup
boundary. Retention is append-only for this milestone; no snapshot or blob
garbage collection is allowed.

## Model-store durability boundary

Proposed future layout, separate from the original operational STT store:

```text
/srv/speech-platform/models/stt/faster-whisper-large-v3-turbo/
  sha256/<model-manifest-sha256>/...
```

The model identity, not a deployment or milestone, names the stable root. The
digest directory contains the pinned `manifest.yaml` and exactly its
manifest-listed `artifact/` files. A separately hashed retention metadata
record carries schema version, model ID/family/repository/revision, artifact
manifest digest, platform release version and deployment milestone; the
upstream artifact manifest remains byte-identical. The host path remains an
explicit validated configuration value such as `STT_MODEL_HOST_ROOT`;
application logic does not hardcode it.

The proposed artifact tree is root-owned: `root:stt-model-reader` directories
mode `2750` and files mode `0640`, with no group write. The existing
`/srv/speech-platform` parent is root-owned mode `0711`; the
`/srv/speech-platform/models` directory also exists, root-owned, GID 988,
mode `2710`. Its descendants could not be inspected without privileged access,
so parent and nested path trust remain unqualified. The model root must not
merge with or replace `/var/tmp/speech-platform-m01e-fresh-v012/model-store`.
Storage parent qualification/preparation, artifact copying and changing the
running container's bind mount are distinct operations. Each requires
separate review and authorization; bind migration requires an approved
deployment change and container recreation. Snapshot capture does none of
them.

A retained model copy can satisfy rollback artifact availability only after it
contains the release-pinned manifest and every manifest-listed payload file,
each verified against its exact digest and size. Copy only the five files in
the pinned artifact manifest into a private same-filesystem staging directory.
Set the payload tree to root ownership, directory mode `2750` and file mode
`0640`, verify exact file set, size and digest, run the existing complete
artifact verifier against the staged release structure, and verify read
access as UID 65532 with supplementary GID 988. Publish the digest-named
directory with Linux `renameat2(RENAME_NOREPLACE)`, then fsync the staging and
destination parents; never overwrite an existing digest. Preserve every prior
verified directory. Back up the retention record, `manifest.yaml`, payloads
and ownership/mode metadata; restore verification repeats the complete checks
before use. This establishes retained artifact availability, not that the
active container uses the retained path. That requires an approved bind
migration and fresh runtime observation.

### Proposed host preparation procedure (not executed)

The stable root is
`/srv/speech-platform/models/stt/faster-whisper-large-v3-turbo/sha256/`;
the leaf name is the pinned model-manifest SHA-256. The host path stays in
validated deployment configuration (`STT_MODEL_HOST_ROOT`). Model identity
and revision, platform release version (`v0.1.2`), and deployment milestone
(`M01F-B3.1`) belong in a versioned retention metadata record and later state
metadata, not in directory names or application constants.

The existing `/srv/speech-platform/models` parent is root-owned, GID 988,
mode `2710`; its child entries were not inspectable without privileged access.
An operator must first inspect the complete ancestry and descendants as root.
If each desired component is absent, create `stt`,
`faster-whisper-large-v3-turbo`, and `sha256` separately as
`root:stt-model-reader` mode `2750`. Existing entries require review and must
not be silently chmodded or replaced. These commands describe future
preparation only and were not run:

```sh
sudo namei -l /srv/speech-platform/models/stt/faster-whisper-large-v3-turbo/sha256
sudo mkdir -- /srv/speech-platform/models/stt
sudo chown root:988 /srv/speech-platform/models/stt
sudo chmod 2750 /srv/speech-platform/models/stt
sudo mkdir -- /srv/speech-platform/models/stt/faster-whisper-large-v3-turbo
sudo chown root:988 /srv/speech-platform/models/stt/faster-whisper-large-v3-turbo
sudo chmod 2750 /srv/speech-platform/models/stt/faster-whisper-large-v3-turbo
sudo mkdir -- /srv/speech-platform/models/stt/faster-whisper-large-v3-turbo/sha256
sudo chown root:988 /srv/speech-platform/models/stt/faster-whisper-large-v3-turbo/sha256
sudo chmod 2750 /srv/speech-platform/models/stt/faster-whisper-large-v3-turbo/sha256
```

Because `mkdir` intentionally fails if a component already exists, stop and
inspect rather than changing an existing path. Copy only these pinned
manifest-listed payload files: `config.json`, `model.bin`,
`preprocessor_config.json`, `tokenizer.json`, and `vocabulary.json`, plus the
byte-identical `manifest.yaml`. Their expected sizes and SHA-256 values are
in `releases/artifacts/stt-large-v3-turbo.yaml`. Stage the digest directory
under a private mode `0700` temporary directory on the same filesystem; make
its `artifact/` directory mode `2750`, install each listed file as
`root:stt-model-reader` mode `0640`, then run `check_models` against the
staging store and check the exact file set, sizes and hashes. Verify read
access as UID 65532 with supplementary GID 988. Generate a canonical
`retention.json` inside the staged digest directory with exact fields `schema_version`, `model_id`,
`model_family`, `model_repository`, `model_revision`,
`artifact_manifest_sha256`, `artifact_format`, `platform_release_version`,
`deployment_milestone`, and `platform`; hash it and bind its digest into later
snapshot and state metadata. Publish the complete digest directory, including
the retention record, with an audited
`renameat2(RENAME_NOREPLACE)` operation and fsync both affected parent
directories. A duplicate digest is accepted only after complete verification.

Retain every verified model revision until an approved retention review
allows removal. Backups must include each digest directory, its retention
record, exact ownership and modes, and must be encrypted and private. A
restored copy is verified again from the backup path before use. The existing
`/var/tmp` artifact tree and active container bind remain untouched throughout
this procedure. Storage preparation, copying, and a later bind/configuration
migration require separate operator approvals.

## Consequences and open operator decisions

Planning remains blocked for Gateway, STT and TTS until a complete retained
snapshot and its artifacts are available. Before real capture, the operator
must approve: (1) the private snapshot and backup boundary, (2) durable model
artifact retention outside the temporary `/var/tmp` location (the proposed
`/srv/speech-platform/models/stt/faster-whisper-large-v3-turbo/...` layout
requires host qualification),
and (3) whether a secret resolver is needed and its immutable version-reference
format. Current schemas have no secret fields, so capture requires an empty
secret-reference map. The writer reuses B1 durability primitives and the
shared B2 lock. Neither the approved architecture nor writer implementation
authorizes real snapshot creation, adoption, installed-state writes, Docker
lifecycle operations or model migration.

## Alternatives considered

- Treat mutable private deployment inputs as retained restoration: rejected;
  they do not prove historical bytes or transitive dependencies remain.
- Store secrets in content-addressed blobs: rejected; content addressing does
  not make secret material safe to retain.
- Store a `secret_free` assertion only: rejected; the writer must enforce
  closed file/environment allowlists and strict schemas.
- Remap host paths during restoration: rejected for exact baseline restoration;
  changed paths alter the runtime contract and need a new plan.
- Initialize B1 state or use a second persistence implementation to capture:
  rejected; the future writer must reuse B1 durable publication primitives
  without initializing deployment state.
- Add an STT diagnostic endpoint for runtime identity: rejected; the observed
  Docker Compose hash plus independently rendered expected hash already
  supplies the required evidence.

## Final M01F-B3.1 capture mapping — 2026-10-20

The operator verified the release-pinned `large-v3-turbo` digest in the
existing `/srv/speech-platform/models` store and reported successful read
access as UID `65532` with supplementary GID `988`. Capture reuses this store
directly: the manifest digest directory is an immediate child of the supplied
store root. No new model hierarchy, artifact copy, relocation, or live bind
change is part of this capture. The currently running STT container remains
bound to the same digest under `/var/tmp`; the collector checks that live
binding, while the snapshot adapter's retained artifact check validates the
existing `/srv` store.

This establishes retained artifact integrity and worker readability for the
operator-verified store. It does not claim the active bind points to that store
or establish a completed restore drill. The snapshot's model reference is the
release-pinned model ID and manifest digest; the existing artifact manifest
contains the model revision and per-file sizes and hashes. No additional
retention metadata file is required by the current capture schema.

For the first capture, `private/deployment/m01e-fresh-v012/restoration/` and
its `staging/`, `objects/sha256/`, and `snapshots/sha256/` descendants are
created by the existing private storage helpers as part of the approved
capture. All directories are private mode `0700`, files `0600`; the manifest
is activated last. This task does not require a NAS or external-backup
destination. Backup and independent restore qualification remain outside this
capture-readiness scope and must not be inferred from a successful local
snapshot.

## Storage qualification and retention preflight — 2026-10-20

### Observed storage boundary

- **OBSERVED** — `/srv`, `/srv/speech-platform`, `/srv/speech-platform/models`,
  `/srv/speech-platform/deployment-state` and its `locks` child resolve to the
  root ext4 filesystem (`/dev/mapper/ubuntu--vg-ubuntu--lv`, device 64512).
  `/var/tmp` and the active model tree resolve to that same filesystem. At
  inspection, it had 83,578,949,632 bytes available (about 77.9 GiB). This is
  point-in-time capacity; a second model copy on this filesystem does not
  establish independent durability or backup.
- **OBSERVED** — `/srv` is `root:root` mode `0755`;
  `/srv/speech-platform` is `root:root` mode `0711`; and
  `/srv/speech-platform/models` is `root:988` mode `2710`, setgid. Traversal
  stopped at `models/stt` with permission denied. Thus descendants, ACLs,
  links, mount boundaries, available capacity under `models`, and the exact
  missing descendants could not be established. `getfacl` is not installed.
  Direct ACL xattr reads on accessible ancestors returned no access/default
  ACL xattrs, but do not qualify inaccessible descendants or other ACL
  implementations.
- **OBSERVED** — `/srv/speech-platform/deployment-state` and `locks` are
  `master:master` mode `0700` on that ext4 device. The state root contains only
  `locks`; it contains the target project lock and two B2 test lock files.
  The target lock is `master:stt-model-reader`, mode `0600`, one link. It was
  inspected without acquisition or modification. No target installed-state
  directory, uncertainty marker, or project state record exists. Existing
  lock files are protected and must not be removed or repurposed.
- **OBSERVED** —
  `private/deployment/m01e-fresh-v012/restoration` is absent. No snapshot
  storage or snapshot was created. The active model source under `/var/tmp`
  was left unchanged.
- **NOT ESTABLISHED** — Privileged inspection was attempted, but `sudo -v`
  required the operator password and returned “a password is required.” No
  privileged command was run. `getfacl` is unavailable and the current user
  cannot inspect `models` descendants. Complete ancestry, descendants, ACL
  and mount-boundary qualification needs an operator-supervised privileged
  session.

### Model retention procedure for later approval (not executed)

The verified release is v0.1.2; model ID `large-v3-turbo`, revision
`0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`, and manifest SHA-256
`86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`. Its
five payloads and the manifest are the release-pinned set below. The existing
source is `/var/tmp/speech-platform-m01e-fresh-v012/model-store/<digest>`;
it currently remains `master:stt-model-reader`, directories `2750`, files
`0640`. Retention must copy, never move, hard-link or modify, this tree.

Before preparation, inspect every component and descendant as root, ACLs,
symlinks, hard links, mount points, capacity and existing digest contents.
Only missing trusted parent directories may be created; an unexpected
existing component stops the procedure. The exact missing descendants under
`models` are **NOT ESTABLISHED**. Candidate parents are `stt`,
`faster-whisper-large-v3-turbo`, and `sha256`.

After separate approval for storage preparation and model copy, use this
bounded sequence. Run each `mkdir` only after privileged inspection confirms
that the named component is absent; stop if it exists. These commands are
review material and were not run:

```sh
sudo namei -l /srv/speech-platform/models/stt/faster-whisper-large-v3-turbo/sha256
sudo findmnt -T /srv/speech-platform/models
sudo df -P -B1 /srv/speech-platform/models
sudo mkdir -- /srv/speech-platform/models/stt
sudo chown root:988 /srv/speech-platform/models/stt
sudo chmod 2750 /srv/speech-platform/models/stt
sudo mkdir -- /srv/speech-platform/models/stt/faster-whisper-large-v3-turbo
sudo chown root:988 /srv/speech-platform/models/stt/faster-whisper-large-v3-turbo
sudo chmod 2750 /srv/speech-platform/models/stt/faster-whisper-large-v3-turbo
sudo mkdir -- /srv/speech-platform/models/stt/faster-whisper-large-v3-turbo/sha256
sudo chown root:988 /srv/speech-platform/models/stt/faster-whisper-large-v3-turbo/sha256
sudo chmod 2750 /srv/speech-platform/models/stt/faster-whisper-large-v3-turbo/sha256
```

Then use an operator-reviewed root-run one-shot helper with fixed inputs and
these checks. Do not use `cp -a`, symlinked sources, wildcard expansion or a
mutable source list.

1. Load the v0.1.2 release with `scripts.release_manifest.load_release` and
   use the validated manifest. Require exactly `config.json`, `model.bin`,
   `preprocessor_config.json`, `tokenizer.json` and `vocabulary.json`, with
   sizes and hashes matching `releases/artifacts/stt-large-v3-turbo.yaml`.
   Confirm the source directory digest matches the pinned manifest. No network
   access is needed.
2. Require the source directory and files to be regular, non-symlink,
   single-link objects. Open without following symlinks, verify all source
   hashes and sizes before copying, and reject unexpected entries.
3. Create a private stage under the existing `sha256` parent with exclusive
   creation and mode `0700`; this keeps staging on the destination filesystem.
   Create `artifact/` as `root:988` mode `2750`. Copy only the five listed
   payloads and byte-identical `manifest.yaml`, using exclusive output
   creation. Set each file to `root:988` mode `0640`. Add canonical
   `retention.json` with schema version, stable model ID/family/repository,
   model revision, artifact-manifest digest, artifact format, platform release
   version `v0.1.2`, deployment milestone `M01F-B3.1`, and platform. Keep the
   upstream manifest unchanged.
4. Verify the exact stage tree, owner, group, modes, link counts, sizes,
   manifest digest and payload hashes. Run the complete existing model checker
   against the staged store using the validated v0.1.2 release and
   `scripts.model_artifacts.check_models`. Verify read access as UID `65532`
   with supplementary GID `988` using an operator-approved `setpriv` or
   equivalent invocation, and verify that identity cannot write the tree.
5. Fsync each staged file and directory. Publish the staged digest directory
   as `<sha256>/<manifest-digest>` with Linux
   `renameat2(RENAME_NOREPLACE)`. Fail if the destination exists; never replace
   or merge. Fsync the `sha256` parent. If that digest already exists, verify
   it in place and stop without changing it. Re-run the complete checker and
   exact tree, metadata, modes and hash checks on the published path. Retain
   every prior digest. Do not automatically clean abandoned staging; retain it
   for supervised inspection.

The existing `scripts/provision_models.py fetch` is unsuitable because it
downloads and creates a store with different ownership/mode defaults. Its
`check` action is read-only and can check a published store when given its
parent `sha256` path. A retained copy proves artifact availability only; it
does not change the live Compose mount.

### Restoration mapping and runtime binding

Docker currently reports this read-only STT bind source at `/models`:

```text
/var/tmp/speech-platform-m01e-fresh-v012/model-store/86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6
```

The candidate retained source is:

```text
/srv/speech-platform/models/stt/faster-whisper-large-v3-turbo/sha256/86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6
```

These paths differ. Copy verification does not prove Docker uses the retained
path; the active container remains reported as bound to `/var/tmp`. Any future
restoration must validate retained digest and UID/GID access, target path
identity, mount boundary, permissions, complete model digest and the captured
and rendered Compose contract. Changing the source path changes rendered
service identity. Configuration changes, container recreation or bind
migration require separate deployment review and authorization, followed by
fresh Docker mount, runtime identity, health, readiness, image and model
verification.

### Snapshot, B1/B2 state and backup boundary

`/srv/speech-platform/deployment-state` is the existing B1/B2 state and shared
lock root (`master:master` `0700`), not the snapshot root. Its lock directory
and existing files remain protected. Project-private snapshots belong under
`private/deployment/m01e-fresh-v012/restoration/`, currently absent. After
separate capture authorization, create only the missing project restoration
root and `staging`, `objects/sha256`, and `snapshots/sha256` children using the
existing B1 private-storage primitives: operator ownership, directories
`0700`, files `0600`, no symlink/special/hard-linked objects, supported local
filesystem, no-replace immutable publication, and file/directory fsync.
Publish objects first and the fully verified manifest last. Do not initialize
a B1 installed generation or operation record. Retain prior snapshots and
objects; no automatic cleanup or garbage collection.

Concrete backup destination proposal (not selected or qualified):
`/mnt/secure-backups/speech-platform/voiceservice/m01e-fresh-v012/` on an
operator-provided encrypted filesystem proven to use a different device from
`/dev/mapper/ubuntu--vg-ubuntu--lv`. Do not create the path or assume it is
mounted. Selection requires capacity, encryption-at-rest evidence, independent
key custody, named access principals, recovery access, retention duration and
a restore-test location. Back up every snapshot manifest and referenced blob,
complete retained model digest trees and manifests, retention metadata, and
the public release/artifact identity metadata needed to verify them. Exclude
raw secrets, logs, lock files, mutable B1 pointers, operation journals,
staging and unverified artifacts. Copy only a fully activated immutable
snapshot (or coordinate under the shared project lock); model backup reads
only a verified immutable digest. Preserve ownership, group, modes, identities
and content. Publish each backup generation immutably, fsync it and retain
prior generations. Independently restore into a private scratch location and
run `verify_retained_snapshot`, the complete model checker, and recorded
file/metadata checks before declaring recoverability. A successful encrypted
copy alone is not restore-integrity evidence.

### Current readiness and operator actions

- **OBSERVED** — A new read-only collection reports exactly
  `gateway:restore_inputs_missing`, `stt:restore_inputs_missing`, and
  `tts:restore_inputs_missing`. All services are running, Docker healthy and
  readiness `READY`; runtime drift is empty; image and complete model checks
  pass. STT runtime identity equals its observed Compose hash. No project
  installed generation or uncertainty marker exists.
- **OBSERVED** — Source and private configuration checks are READY. Snapshot
  storage, durable model retention and backup are NOT READY. No snapshot,
  model copy, state record, filesystem change or Docker operation occurred.
- **INTERPRETATION** — Current free capacity permits another model-sized copy
  at the time observed, but the inaccessible `/srv/speech-platform/models`
  subtree is not qualified. A backup on the same device would not meet the
  proposed independent boundary.
- **NOT ESTABLISHED** — Privileged path/ACL/mount inspection, exact missing
  model directories, approved encrypted off-filesystem backup mount, snapshot
  backup policy, real snapshot retention and an independent restore drill.

Separate operator review is required before privileged storage inspection,
creating confirmed-missing model parents, model copy/publication, snapshot
storage preparation, selecting/qualifying the encrypted backup destination,
or real snapshot capture. These are separate actions. This preflight does not
authorize G0 adoption, installed-state initialization, model bind migration
or milestone closeout.
