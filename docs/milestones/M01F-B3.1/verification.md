# M01F-B3.1 verification

Status: **IMPLEMENTATION CHECKS PASS; REAL-HOST PLAN BLOCKED; OPERATOR
ACCEPTANCE PENDING.**

The follow-up collection below supersedes the first real-host blocker list.

Environment: repository worktree, local `.venv`, Docker Engine 29.1.3, and the
existing Compose-managed project. No other deployment was targeted.

## Verification evidence

- **OBSERVED** — `.venv/bin/python -m unittest scripts.test_baseline_adoption
  -v`: 20 passed. Coverage includes an eligible real-host-shaped fixture,
  absent and contradictory observations, config drift, unavailable restore
  inputs, Docker inspection failure, stale readiness, uncertainty markers,
  existing installed generation, and security identity drift.
- **OBSERVED** — Final `make verify PYTHON=.venv/bin/python`: exit 0; all 359
  script tests and 61 service tests passed. Go vet/race tests, Ruff,
  configuration/Compose/release checks, Go build and governance validation
  also passed. Compose commands rendered/validated configuration only; no
  containers were started or changed.
- **OBSERVED** — `make governance-check PYTHON=.venv/bin/python`: exit 0;
  structural governance checks and two governance tests passed.
- **OBSERVED** — `git diff --check`: exit 0 with no whitespace errors.

## Read-only real-host collection — 2026-10-20

- **OBSERVED** — Added the separate evidence collector
  `scripts/collect_baseline_adoption.py`. Expected runtime values are validated
  from the private configuration and rendered Compose. Observations are
  gathered separately from exact-project Docker container/image/network
  inspection, Docker labels/configuration, and HTTP or in-container readiness
  probes. The collector performed no lifecycle operation, snapshot creation,
  state write or lock acquisition.
- **OBSERVED** — Actual plan for `speech-platform-m01e-fresh-v012`: **BLOCKED**.
  Candidate G0: `g0-8d0d40709cd4def1`. Plan fingerprint:
  `f897238404c0750e7d079c24eb92ff601ba2ab0f1935ed62373a127a5e5cac93`.
  Release: v0.1.2; descriptor SHA-256
  `08ea79cecd719738ad8de6bfe5d1eb58ffe5b9775a14b4b91a8ee1c1675e9cf6`.
- **OBSERVED** — Every selected service was running, healthy and ready at
  collection time. Gateway and TTS use actual HTTP health probes because
  those images have no Docker healthcheck; STT reported Docker health
  `healthy` and its readiness endpoint returned success. Docker inspection
  showed UID/GID `65532:65532`, read-only roots, dropped capabilities,
  `no-new-privileges`, and supplementary `group_add` GID 988 for all three.
  These are Docker-configured identities; effective process supplementary
  groups for Gateway/TTS were not independently queried.
- **OBSERVED** — Exact immutable image references, container/image IDs,
  configuration and runtime identity hashes, Compose config hashes and health:

  | Service | Immutable image reference | Container / image ID | Config SHA / runtime identity SHA | Compose config hash | Health |
  | --- | --- | --- | --- | --- | --- |
  | Gateway | `ghcr.io/azargarov/voiceservice-gateway@sha256:cab80ebc04bc78ec608c1f81c69ce1dfc8e048227e4892053c86783833064d30` | `012e68af14204da473c4f3f0e131354c8e2978983507fef621e475b945187a15` / `sha256:cab80ebc04bc78ec608c1f81c69ce1dfc8e048227e4892053c86783833064d30` | `66cafb9d52b0bd6ac89651fd8b22316ad07852aedae92f0e5d18a7c7860ec181` / `5aa15b9ccaa51ffe18062fad7b66021dfad9bc961583f1aa164ffd147261a1b4` | `6031ccc4b7167665eea7beb3c8ea029abba4d5999e824a0299c64735bbde64fe` | running / READY |
  | STT | `ghcr.io/azargarov/voiceservice-stt-cuda@sha256:31440127a13a1892f07fe480f013f1185c2d978ee981b5ce56fcd4a09a702ad8` | `6a835c317c622a852f2c7a9760c028dd990862f8cc67acc96fbc49c6be50b303` / `sha256:31440127a13a1892f07fe480f013f1185c2d978ee981b5ce56fcd4a09a702ad8` | `87066bb617f1b6a85baa1b8f3ced401cae3a0c570b85b591a05555fed65ab4c4` / **unobserved** | `f59627c30ff2a8c5fad2965376896dea682f1aec9a9c0bb31627d61e8a231109` | running / healthy / READY |
  | TTS | `ghcr.io/azargarov/voiceservice-tts-health-only@sha256:6ac1e87e1290f657dae613fafcf5357505c129185d34e1966f4b35a7dc8543c9d6` | `33337e3f5754d54b6a87deafcf5357505c129185d34e1966f4b35a7dc8543c9d` / `sha256:6ac1e87e1290f657dae613fafcf5357505c129185d34e1966f4b35a7dc8543c9d6` | `3a15d1d1c8ff61280bf59f26d67a15bd53d1356f4a6f3fce8b90ce7bdbee1261` / `3c4fa5ebdd4d0a3e4f62f75f48f68ceff400f92b75b4393bd6049664a1fae791` | `5852729ea6264290d3b13e0acaa150ae49ac19c7af063fe3a1fa90a74d57254b` | running / READY |
- **OBSERVED** — Image references matched the pinned v0.1.2 release digests.
  The complete large-v3-turbo manifest and all five artifact files passed
  `check_models`; manifest SHA-256 is
  `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`.
  No runtime drift was reported by the collector.
- **OBSERVED** — Project-specific B1 installed state is absent
  (`installed_generation_id=null`); no project B2 uncertainty marker is
  present. The shared deployment-state root exists for lock files, but the
  project state directory does not; this is not treated as inconsistent
  installed state.
- **OBSERVED** — Restoration-input status is
  `MISSING_OR_INCOMPLETE`. The supplied private deployment set contains
  mutable/current service configuration but no immutable retained snapshots,
  approved runtime-definition references or restoration inventory. No
  snapshots were written during planning.
- **OBSERVED** — Complete planner blockers:
  `gateway:restore_inputs_missing`, `stt:restore_inputs_missing`,
  `stt:runtime_verification_failed`, and `tts:restore_inputs_missing`.
  STT currently has a Docker Compose config hash but no observed
  `runtime_identity_sha256` matching the planner's required restoration
  identity. The missing evidence was not substituted with an expected value.
- **INTERPRETATION** — The deployment's live image, model, rendered runtime,
  and health/readiness evidence are consistent with the existing v0.1.2
  deployment. It is not eligible for baseline adoption until exact immutable
  restoration inputs are available and the STT runtime identity is observed.
- **OBSERVED** — Focused tests after collector and planner changes:
  `.venv/bin/python -m unittest scripts.test_baseline_adoption -v` — 16 passed.
- **OBSERVED** — `make verify PYTHON=.venv/bin/python` — exit 0; 355 Python
  script tests and 61 service tests passed, along with Go vet/race tests,
  Ruff, config/Compose/release validation, build and static governance checks.
  The initial attempt stopped at Ruff for unused imports and formatting; those
  issues were corrected before the passing run.
- **OBSERVED** — `make governance-check PYTHON=.venv/bin/python` — exit 0;
  structural checks and two governance tests passed.
- **OBSERVED** — `git diff --check` — exit 0.
- **NOT ESTABLISHED** — User acceptance of B3.1 remains pending. This evidence
  does not authorize adoption, B3.2, state initialization, or milestone
  closeout.

## Follow-up identity and restoration validation — 2026-10-20

- **OBSERVED** — Root cause: the STT Compose service does not emit
  `com.speech-platform.deployment-identity-sha256`, and its supported HTTP
  diagnostics expose health/readiness only. The running container does expose
  Docker's `com.docker.compose.config-hash`. The collector now independently
  derives the expected STT service hash with `docker compose config --hash
  stt` over validated private inputs and the checked-in Compose files; the
  runtime value remains the one read from Docker inspection. The existing
  STT `configuration-set-sha256` continues to be validated separately. No
  expected value is copied into observed evidence.
- **INTERPRETATION** — The required STT identity is not truly absent from the
  running service: a supported runtime identity exists in Docker metadata.
  The compatibility limitation was the collector's assumption that STT used
  the custom label emitted by Gateway and TTS. No service endpoint or Compose
  label change is required. Docker Compose's hash covers its normalized
  service configuration; configuration-set, image, model and security
  checks remain independent requirements.
- **OBSERVED** — The current read-only plan for
  `speech-platform-m01e-fresh-v012` is **BLOCKED** with exactly:
  `gateway:restore_inputs_missing`, `stt:restore_inputs_missing`, and
  `tts:restore_inputs_missing`. Candidate G0 is
  `g0-18fa8c1b016849b8`; plan fingerprint is
  `6188dea5dcb228c84cf149dd1b4c2d998a5b592408e750fabf08e017639625d5`.
  Release is v0.1.2, descriptor digest
  `08ea79cecd719738ad8de6bfe5d1eb58ffe5b9775a14b4b91a8ee1c1675e9cf6`.
  Restoration inputs are `MISSING_OR_INCOMPLETE`; no retained snapshot
  inventory is present. All services were running, healthy and READY, and
  `observed_runtime_drift` was empty. STT runtime identity and observed Compose
  config hash both equal
  `f59627c30ff2a8c5fad2965376896dea682f1aec9a9c0bb31627d61e8a231109`.
  Its independently checked configuration-set digest is
  `87066bb617f1b6a85baa1b8f3ced401cae3a0c570b85b591a05555fed65ab4c4`.
- **OBSERVED** — The release-pinned large-v3-turbo model manifest and all five
  artifact files verified; manifest digest is
  `86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`.
  Project-specific installed state remains absent and no uncertainty marker
  was reported. No state, lock, snapshot or Docker resource was written.
- **OBSERVED** — Added a read-only snapshot verifier and proposed
  [ADR 0017](../../adr/0017-private-content-addressed-restoration-snapshots.md).
  It requires content-addressed manifests and blobs, exact role sets,
  immutable release artifact references, matching secret-version references,
  and strict owner/mode/type/content checks. Only temporary test fixtures were
  created; real snapshots were not created.
- **OBSERVED** — Focused suite:
  `.venv/bin/python -m unittest scripts.test_baseline_adoption -v` — 28
  passed. Coverage includes missing, matching and mismatched STT identity,
  incomplete/valid retained snapshot content, expected/observed configuration
  mismatch, Docker inspection failures, stale readiness, uncertainty markers,
  and existing installed generation.
- **OBSERVED** — `make verify PYTHON=.venv/bin/python` — exit 0; 367 script
  tests and 61 service tests passed, with Go vet/race tests, Ruff,
  configuration/Compose/release checks, Go build, governance validation and
  STT lock checks.
- **OBSERVED** — `make governance-check PYTHON=.venv/bin/python` — exit 0;
  governance validator and two governance tests passed. `git diff --check` —
  exit 0.
- **INTERPRETATION** — The remaining host blocker is restoration retention,
  not STT runtime evidence. The live mutable configuration set does not prove
  that exact configuration and immutable runtime inputs are preserved for
  recovery.
- **NOT ESTABLISHED** — The proposed snapshot schema and lifecycle have not
  been accepted by the operator, and no real snapshot has been captured or
  independently restored. Adoption eligibility therefore remains blocked.

## Final restoration snapshot architecture review — 2026-10-20

The following evidence supersedes earlier STT identity descriptions above.
The STT row in the initial collection table is historical; the follow-up
collection observed and matched both the runtime Compose service hash and
expected hash.

- **OBSERVED** — `scripts/restore_snapshot.py` verifies schema-v2 project
  snapshots read-only. Synthetic tests require exact file and environment
  allowlists, strict owner/mode/type/link checks, canonical content and
  manifest digests, immutable artifact references, host-binding digest
  consistency, and rejection of secret-looking keys/content and unapproved
  secret reference schemes. Focused command
  `.venv/bin/python -m unittest scripts.test_baseline_adoption -v`: 33 passed.
- **OBSERVED** — `make verify PYTHON=.venv/bin/python`: exit 0; 372 script
  tests and 61 service tests passed. Go vet/race tests, Ruff, config/Compose/
  release checks, Go build, governance validation and STT lock checks passed.
  Compose invocations rendered/validated config; no lifecycle command ran.
- **OBSERVED** — `make governance-check PYTHON=.venv/bin/python`: exit 0;
  structural governance checks and two governance tests passed.
- **OBSERVED** — `git diff --check`: exit 0.
- **OBSERVED** — A fresh read-only collection of
  `speech-platform-m01e-fresh-v012` remains **BLOCKED** with exactly
  `gateway:restore_inputs_missing`, `stt:restore_inputs_missing`, and
  `tts:restore_inputs_missing`. Candidate G0:
  `g0-309f87d35faba9e4`; plan fingerprint:
  `6b68a191a228481312dbcea991c85dd0d256edec21ccf6749cdb20a42ca6ec41`.
  Release v0.1.2 descriptor SHA-256 remains
  `08ea79cecd719738ad8de6bfe5d1eb58ffe5b9775a14b4b91a8ee1c1675e9cf6`.
  The fingerprint is collection-specific because readiness evidence includes
  observation time and changes between otherwise equivalent reads.
- **OBSERVED** — Gateway, STT and TTS were all running, Docker healthy and
  readiness `READY`; no runtime drift was reported. STT observed runtime
  identity and Compose hash both matched
  `f59627c30ff2a8c5fad2965376896dea682f1aec9a9c0bb31627d61e8a231109`.
  Project B1 state remains absent and no uncertainty marker was present.
- **OBSERVED** — No real snapshot, B1 state, operation record, lock or
  uncertainty-marker change was made. No Docker lifecycle operation, image
  pull or model download was performed.
- **INTERPRETATION** — The snapshot design now requires exact retained
  configuration and artifact dependencies, with original host paths preserved
  and proved from rendered Compose. Eligibility remains blocked until a
  complete immutable snapshot exists and the current `/var/tmp` model-store
  retention/backup boundary is approved.
- **NOT ESTABLISHED (at this earlier review point)** — Operator approval of
  ADR 0017, the private backup boundary, durable model retention, and any
  secret-provider reference format remained pending. The writer was not yet
  implemented at that point; the following verification section supersedes
  that status.

## Snapshot writer implementation verification — 2026-10-20

- **OBSERVED** — Focused command
  `.venv/bin/python -m unittest scripts.test_restore_snapshot -v`: 21 passed.
  The temporary-fixture suite covers complete and optional evidence roles,
  missing/unknown/secret inputs, incomplete dependency closure, config and
  runtime races, source-root/symlink/hard-link refusal, interruption before
  and after blob publication and before manifest activation, duplicate and
  corrupt/missing objects, lock contention, stale runtime evidence, exact
  rendered Compose identity, verifier interoperability and no operational
  model-store/Docker writer path.
- **OBSERVED** — The first `make verify PYTHON=.venv/bin/python` run found
  three B1 installed-pointer tests failing after the shared publisher
  refactor: the replace path attempted to unlink the temporary filename after
  `os.replace` had already consumed it. The common helper was corrected so
  replacement and no-replace publication each remove their temporary link
  correctly.
- **OBSERVED** — Rerun `make verify PYTHON=.venv/bin/python`: exit 0; 393
  script tests and 61 service tests passed. Go vet/race tests, Ruff,
  configuration/Compose/release checks, Go build, governance validation and
  STT lock checks passed.
- **OBSERVED** — `make governance-check PYTHON=.venv/bin/python`: exit 0;
  structural checks and two governance tests passed. `git diff --check`: exit
  0.
- **OBSERVED** — Snapshot capture was invoked only with temporary private
  directories, fake observations and injected validators/renderers/artifact
  verifiers. No production deployment config, B1 state, real lock root,
  operational model store or Docker resource was changed. No real snapshot
  was captured.
- **INTERPRETATION** — The writer guarantees manifest-last activation over
  fully staged and digest-verified inputs. A failed capture can leave
  owner-only staging, verified orphan blobs or an empty digest directory;
  none is eligible without a complete verifiable manifest. Staging is retained
  for operator diagnosis and is not automatically cleaned up.
- **NOT ESTABLISHED** — No production adapter invocation has yet been
  qualified against the target host. Before real capture, qualify the approved
  private snapshot/backup boundary and supported local filesystem, verify
  owner/modes/ACL and fsync/no-replace behavior, provide the adapter wiring
  existing strict config, Compose/Docker, release/image and model checks to the
  capture API, and establish durable model retention outside
  `/var/tmp/speech-platform-m01e-fresh-v012/model-store`. Storage preparation,
  model artifact copying and container bind migration each require separate
  authorization; no migration is part of B3.1.
- **OBSERVED** — The B1 filesystem helper reports `ext4` for the current
  repository `private` tree and `/srv/speech-platform`. The latter parent is
  root-owned mode `0711`; no snapshot or model-artifact child was created or
  permission-adjusted. The proposed child ownership, reader-group policy and
  backup behavior still need host qualification.
- **NOT ESTABLISHED** — Operator review of the writer implementation and
  approval to perform a real snapshot capture remain pending. B3.1 adoption
  remains blocked by absent retained restoration inputs.

## Production adapter and B1 pointer regression review — 2026-10-20

- **OBSERVED** — Added `scripts.snapshot_capture_adapter` with a fixed source
  map for `private/deployment/m01e-fresh-v012`, the v0.1.2 release descriptor,
  and both tracked Compose files. Preflight validates source types, links,
  ownership/modes, config-reader group, complete enabled service selection,
  and release identity. Production callbacks reuse the existing read-only
  collector, Compose renderer, service readiness probes, registry image
  verification and complete local model artifact checker. Captured Compose
  bytes are rendered from private temporary copies with the original Compose
  project directory; private YAML is not copied to the temporary directory.
- **OBSERVED** — The adapter defaults to the existing snapshot writer, which
  obtains the shared project lock, refuses unresolved uncertainty markers,
  revalidates configuration and runtime, and activates a manifest only after
  all checks pass. No real adapter capture was invoked.
- **OBSERVED** — `scripts.restore_snapshot._source_bytes` now includes mode,
  owner, group and link count in source-race identities. The writer accepts
  group-readable mode `0640` only for service YAML inputs that use the approved
  private-file rule; the production adapter checks that such files use the
  configured reader group. Group-writable tracked sources remain rejected.
- **OBSERVED** — Added three B1 installed-pointer replacement regressions:
  failure before replacement, failure at `os.replace`, and directory-fsync
  failure after replacement. The first two preserve the prior pointer and
  clean the temporary file. The latter reports an error with the replacement
  pointer visible for inspection, preserving uncertainty after publication.
  Immutable state and snapshot records continue to use no-replace; only the
  mutable installed pointer uses atomic replacement. File fsync precedes
  publication and directory fsync follows it.
- **OBSERVED** — Focused command
  `.venv/bin/python -m unittest scripts.test_restore_snapshot
  scripts.test_snapshot_capture_adapter scripts.test_deployment_state -v`:
  56 tests passed. Synthetic coverage includes valid three-service snapshots,
  missing inputs, source/runtime drift, unavailable artifact verification,
  secret and environment rejection, incomplete dependency closure, lock
  contention, uncertainty markers, source-independent verification and the
  three pointer replacement error windows.
- **OBSERVED** — `make verify PYTHON=.venv/bin/python` completed successfully:
  Ruff, format checks, configuration/Compose/release checks, Go tests/build,
  405 script tests, 61 service tests, governance validation and STT lock
  checks passed. `make governance-check PYTHON=.venv/bin/python` passed;
  `git diff --check` passed.
- **OBSERVED** — Read-only adapter preflight against the configured source
  map returns `SnapshotCaptureError: deployment input permissions are unsafe`.
  Tracked Compose and release inputs are mode `0664`; the adapter rejects
  group-writable tracked inputs, and no chmod or content change was made.
- **INTERPRETATION** — These tracked source permissions are an additional
  capture gate; they do not alter the prior host adoption finding that
  immutable restoration inputs are absent. The active model mount remains
  `/var/tmp/speech-platform-m01e-fresh-v012/model-store`; no durable retained
  model copy is active or established.
- **NOT ESTABLISHED** — Production callback execution against real Docker
  observations and model artifacts; approval/qualification of tracked-source
  permission handling; the private snapshot backup boundary; and durable model
  retention under `/srv/speech-platform/`. Storage preparation, model copying,
  and container bind migration remain separate authorization steps.

## Final host qualification — 2026-10-20

- **OBSERVED** — Tracked runtime inputs are clean relative to the approved
  repository tree. `deployments/compose/compose.yaml` has Git mode `100644`,
  blob `bea30b94a1aa796c8b7a6c3a9ee3df995b11f005`; the CUDA overlay has Git
  mode `100644`, blob `61d6ee5c9405eb707f5d599a615f8faa5c094e38`; and
  `releases/voiceservice-v0.1.2.yaml` has Git mode `100644`, blob
  `2659c0f534920fbb4745e6aeb0bee3055e747f50`. `git hash-object` matched each
  blob and `git status` showed no changes to those paths. All three working
  files are regular files owned by UID/GID 1000, mode `0664`, link count 1.
  Their Compose parent is mode `0755`; the release parent is mode `0775`,
  owner UID/GID 1000. NSS currently maps GID 1000 and reader GID 988 only to
  the trusted operator account. ACL inspection tooling is unavailable in this
  environment; empty xattr lists were observed, which do not establish the
  absence of every possible ACL implementation.
- **INTERPRETATION** — The observed group-write bits do not currently grant a
  distinct principal write access according to NSS, and Git content is exact.
  The adapter's blanket group-write rejection remains a blocker until a
  narrowly scoped source-integrity policy is implemented. Recommended policy:
  pin the deployment source revision separately from the release's image
  provenance revision; require exact committed Git blob identities for the
  allowlisted Compose and release files, no staged or unstaged changes to
  those paths, trusted UID and parent ownership, no links/special files or
  untrusted ACLs, stable pre/post source identities, and hashes of the exact
  captured bytes used for Compose rendering. Recheck trusted group membership
  at qualification. This policy must not bless arbitrary group-writable
  inputs or private configuration. No permission changes were made.
- **OBSERVED** — Read-only collector for
  `speech-platform-m01e-fresh-v012` returned **BLOCKED** with exactly
  `gateway:restore_inputs_missing`, `stt:restore_inputs_missing`, and
  `tts:restore_inputs_missing`. Candidate G0 was
  `g0-a1a96c3286e922f9`; plan fingerprint was
  `6c35cbd3dbd828d7a4ddd474e46510bd8569935c452b00edf716badf1a75b91c`.
  Release v0.1.2 descriptor SHA-256 was
  `08ea79cecd719738ad8de6bfe5d1eb58ffe5b9775a14b4b91a8ee1c1675e9cf6`.
  Restoration inventory and immutable snapshot were absent. Project state
  was absent, installed generation was null, unresolved operations were
  empty, and no uncertainty marker was present. No adoption or state writes
  were performed.
- **OBSERVED** — Gateway, STT and TTS each reported running, healthy and
  `READY`; no runtime drift was reported. Their container IDs, image IDs,
  immutable release image digests, Compose hashes, configuration hashes,
  runtime identities, mounts, networks, ports, UID/GID and configured
  supplementary GID 988 were collected from Docker observations. The STT
  runtime identity matched its independently rendered Compose hash.
  Release image platform/provenance checks passed. The complete pinned
  large-v3-turbo manifest and all artifact files verified; the retained model
  occupies 1,621,666,880 bytes under the current `/var/tmp` model root.
- **OBSERVED** — `/srv/speech-platform` is root-owned mode `0711`; the existing
  deployment-state and lock directories are owner-owned mode `0700`. The
  project lock file is owner 1000, group 988, mode `0600`, link count 1; this
  inspection did not acquire it. No project installed-state directory,
  uncertainty marker, restoration inventory, restoration snapshot root or
  proposed persistent model-artifact root was found. Approximately 78 GiB was
  available on the filesystem containing both `/srv` and `/var/tmp` at
  inspection time.
- **INTERPRETATION** — For future model retention, prepare an isolated
  content-addressed root such as
  `/srv/speech-platform/models/stt/faster-whisper-large-v3-turbo/sha256/`
  root-owned with reader group 988, directories mode `2750`, files mode
  `0640`, with no links or mutable aliases. Copy only into
  a new staging location, verify every file's size and SHA-256 against the
  pinned manifest, run the existing local artifact verifier against the
  retained path, then publish the digest-named directory without replacement
  and fsync it. Preserve all prior verified versions and back up both model
  content and manifests. Storage preparation, copying and changing the
  running STT bind mount are separate operator-authorized actions. Until a
  separately reviewed deployment changes and re-inspects the mount, active
  STT still uses `/var/tmp`; a retained copy does not establish otherwise.
- **INTERPRETATION** — Future snapshots should remain under an owner-private
  mode `0700` project root, with private manifests/blobs mode `0600`, immutable
  content-addressed identities, and retained prior versions. A backup boundary
  should include the complete snapshot object and manifest trees plus the
  separately retained model artifacts and their manifests, preserving
  ownership/modes and never including raw secrets, lock files or mutable
  runtime state. No backup destination or restore drill is qualified yet.
  Before use, verify every snapshot blob and manifest with the read-only
  snapshot verifier, then verify each retained model against its release
  manifest from the backup's restored path. An offline encrypted private
  destination, capacity, access controls, and recovery procedure require
  operator selection and qualification. Backup capture can be performed
  without container operations.
- **OBSERVED** — `make verify PYTHON=.venv/bin/python` completed successfully:
  Go vet/race tests, Ruff, config and Compose validation, release validation,
  Python script tests, 61 service tests, Go build, governance validation and
  STT lock checks all passed. `make governance-check PYTHON=.venv/bin/python`
  and `git diff --check` were run after this record was added; see final
  verification result for their outcomes.
- **NOT ESTABLISHED** — No real snapshot, backup, persistent model root,
  retained model copy, or G0 state was created. Real snapshot capture remains
  unauthorized and blocked pending restoration-input capture authorization,
  source-integrity policy implementation, durable model-storage qualification,
  and an approved backup boundary. This evidence does not authorize adoption,
  permission changes, storage preparation, model copying or migration, or
  milestone closeout.

## Capture precondition resolution — 2026-10-20

- **OBSERVED** — Added `scripts.tracked_source_integrity` for exactly the
  Compose base, CUDA overlay and v0.1.2 release descriptor. It requires the
  explicit approved Git commit `6e99eaf4516afd0fa54e8a1fe6c7576b03bc529b`,
  clean staged and unstaged content, exact committed blob IDs and bytes,
  trusted ownership across path ancestors, ACL evidence, single-link regular
  files and trusted NSS group membership for every group-writable file or
  directory. It rechecks the source proof around capture; the writer compares
  `ctime`, inode and bytes. Private deployment permission checks remain
  unchanged. Snapshot manifest schema v3 records the approved source commit
  and exact three Git blob IDs.
- **OBSERVED** — The production preflight found a strict schema mismatch in
  the existing `enabled-services.yaml`: it includes `schema_version: 1`.
  The validator now accepts exactly that version and the required enabled
  service list, while rejecting unknown keys. Read-only source integrity and
  private configuration checks both passed for the target. The v0.1.2 release
  and complete `gateway`, `stt`, `tts` service selection were accepted.
- **OBSERVED** — Focused command
  `.venv/bin/python -m unittest scripts.test_tracked_source_integrity
  scripts.test_restore_snapshot scripts.test_baseline_adoption
  scripts.test_snapshot_capture_adapter -v`: 72 tests passed. New synthetic
  Git fixtures cover modified staged/unstaged content, incorrect group
  membership, source mutation during evidence collection, unsafe paths and
  hard links, malformed commit references, and exact captured-byte/blob
  identity. Snapshot tests verify that source provenance is included in and
  accepted from synthetic schema-v3 manifests.
- **OBSERVED** — Latest read-only collector again reported **BLOCKED** with
  exactly `gateway:restore_inputs_missing`, `stt:restore_inputs_missing`, and
  `tts:restore_inputs_missing`. Candidate G0 was
  `g0-c30f70080163f7e1`; plan fingerprint was
  `db111bd35b931a4e1ed24b83d854db827dddbd19e494bf1257a7028f5a467f14`.
  Release v0.1.2 descriptor digest remained
  `08ea79cecd719738ad8de6bfe5d1eb58ffe5b9775a14b4b91a8ee1c1675e9cf6`.
  The project installed state and uncertainty marker were absent; no
  installed state was created.
- **OBSERVED** — At collection, all three services were running, healthy and
  READY, image/platform/provenance and complete STT model verification passed,
  and runtime drift was empty. STT observed runtime identity matched its
  Compose hash. The current model remains on `/var/tmp`; no retained copy was
  created. Source integrity readiness and private configuration readiness
  were READY; runtime identity and health were READY.
- **OBSERVED** — Snapshot storage root is absent. The containing filesystem
  had about 78 GiB available and is ext4, but no snapshot storage, snapshot or
  backup was created. `/srv/speech-platform/models` exists as root-owned,
  GID 988, mode `2710`; descendants were uninspectable without privileged
  access (`sudo -n` was unavailable because a password is required). Durable
  model retention and backup readiness are therefore NOT READY. The proposed
  stable layout is
  `/srv/speech-platform/models/stt/faster-whisper-large-v3-turbo/sha256/`;
  exact preparation, pinned file verification, root ownership, reader access,
  no-replace publication, retention and backup requirements are in ADR 0017.
- **INTERPRETATION** — Tracked-file mode `0664` is acceptable to this narrowly
  scoped collector only while the pinned source and full ownership/ACL/NSS
  trust proof passes. This does not make the deployment restorable. The plan
  remains blocked solely by missing immutable restoration inputs for the
  three services; model durability and backup qualification remain separate
  capture/rollback readiness prerequisites. No G0 adoption, snapshot capture,
  Docker mutation, model copy, permission change or cleanup occurred.
- **NOT ESTABLISHED** — Privileged inspection and preparation of the model
  storage path, verified retained model publication and read test as UID
  65532/GID 988, backup destination/security/capacity and restore drill,
  immutable restoration snapshot capture, and operator authorization for
  real capture remain pending.
- **OBSERVED** — The first final `make verify PYTHON=.venv/bin/python` attempt
  stopped at Ruff format checking after the final adapter edit. The file was
  formatted, then the same command completed with exit 0. Go vet/race tests,
  Ruff and formatting, config/Compose/release checks, full script and service
  test discovery (61 service tests), Go build, governance validation and STT
  lock checks passed. The focused snapshot/source suites reported 72 tests
  passed.
- **OBSERVED** — `make governance-check PYTHON=.venv/bin/python` completed
  with exit 0, including the governance validator and two governance tests.
  `git diff --check` completed with exit 0 after the source, ADR and milestone
  record changes.

## Storage qualification and model retention preflight — 2026-10-20

- **OBSERVED** — Read-only ancestry checks show `/srv`, `/srv/speech-platform`,
  `/srv/speech-platform/models`, deployment-state, `locks`, `/var/tmp`, and the
  active model tree on ext4 device `/dev/mapper/ubuntu--vg-ubuntu--lv` (device
  64512). Free space was 83,578,949,632 bytes. `/srv` is `root:root` `0755`,
  `/srv/speech-platform` is `root:root` `0711`, and `models` is `root:988`
  `2710`. Traversal cannot inspect `models/stt` unprivileged. `getfacl` is not
  installed. Accessible ancestor ACL xattr probes returned no access/default
  ACL xattrs; descendant ACL state is **NOT ESTABLISHED**.
- **OBSERVED** — `/srv/speech-platform/deployment-state` and `locks` are
  `master:master` `0700`; only lock files were found, including the existing
  target lock and two B2 test lock files. The target lock is one-link mode
  `0600`, `master:stt-model-reader`. No lock was acquired or changed. Project
  installed state and uncertainty marker are absent. The private restoration
  root is absent.
- **OBSERVED** — The current model source is
  `/var/tmp/speech-platform-m01e-fresh-v012/model-store/86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`.
  Its `manifest.yaml` and five files have the expected owner/group (`1000:988`),
  directories mode `2750`, files `0640`, and one link per file. The complete
  model manifest and per-file expected sizes and hashes are recorded in ADR
  0017. The source remains unchanged.
- **OBSERVED** — An interactive sudo validation required the operator
  password and returned “a password is required.” No privileged inspection or
  filesystem operation was executed. The exact missing descendants under
  `/srv/speech-platform/models` therefore remain unknown; the candidate
  components are `stt`, `faster-whisper-large-v3-turbo`, and `sha256`.
- **OBSERVED** — Fresh read-only collector output remains BLOCKED with exactly
  `gateway:restore_inputs_missing`, `stt:restore_inputs_missing`, and
  `tts:restore_inputs_missing`. Gateway, STT and TTS were running, healthy,
  and READY; runtime drift was empty; images and all model files verified.
  STT runtime identity matched its observed Compose hash. Restoration input
  status is `MISSING_OR_INCOMPLETE`; installed state is absent and no
  uncertainty marker is present.
- **INTERPRETATION** — Snapshot storage, durable model retention and backup
  readiness remain NOT READY. The proposed stable model path is
  `/srv/speech-platform/models/stt/faster-whisper-large-v3-turbo/sha256/<manifest-digest>/`.
  ADR 0017 now specifies the read-only findings, later-approval procedure for
  missing parents and immutable model publication, exact runtime-to-retained
  path mapping, private snapshot storage conditions, and a proposed encrypted
  backup location at `/mnt/secure-backups/speech-platform/voiceservice/m01e-fresh-v012/`.
  This destination is not selected, mounted or qualified.
- **NOT ESTABLISHED** — Full privileged ancestry/ACL/mount inspection, exact
  missing directories, trusted persistent model root, staged and published
  model copy, UID `65532`/GID `988` read test on the retained path, encrypted
  off-filesystem backup controls/capacity, and independent backup restore
  verification. No snapshot, backup, model copy, state record, permission
  change or Docker operation was performed.
- **OBSERVED** — Focused synthetic command
  `.venv/bin/python -m unittest scripts.test_restore_snapshot
  scripts.test_snapshot_capture_adapter scripts.test_deployment_state
  scripts.test_tracked_source_integrity -v`: 65 tests passed. This included
  snapshot failure windows, verifier behavior, B1 pointer replacement
  regressions, source-integrity failures and adapter evidence separation.
- **OBSERVED** — `make verify PYTHON=.venv/bin/python` completed with exit 0.
  Ruff and format checks, configuration/Compose/release checks, Go vet/race
  tests, all discovered Python script tests, 61 service tests, Go build,
  governance validation and STT lock checks passed. Compose invocations only
  rendered or validated configuration; no lifecycle command ran.
- **OBSERVED** — `make governance-check PYTHON=.venv/bin/python` completed
  with exit 0; structural governance checks and two governance tests passed.
  `git diff --check` completed with exit 0.

## Operator-supervised storage inspector — 2026-10-20

- **OBSERVED** — Added `scripts/inspect_storage_preflight.py` with a fixed
  allowlist for `/srv/speech-platform`, its `models` and `deployment-state`
  directories, and `/var/tmp/speech-platform-m01e-fresh-v012/model-store`.
  It reads metadata, `/proc/self/mountinfo`, ACL xattrs and the pinned STT
  manifest/payloads only. It does not invoke external commands or contain
  filesystem mutation calls. Parent symlinks/inaccessible ancestors stop
  traversal; model-tree traversal is capped at 5,000 entries/depth 12;
  deployment-state and speech-platform roots are listed one level only.
  Configuration file contents are never read.
- **OBSERVED** — Focused synthetic suite
  `.venv/bin/python -m unittest scripts.test_inspect_storage_preflight -v`:
  8 passed, covering mount and capacity reporting, deployment-state depth
  limits, manifest/payload reporting, safe failures, symlink/hard-link
  detection, fixed target roles, parent-symlink traversal refusal, and
  unchanged fixture files.
- **OBSERVED** — The inspector was run unprivileged using
  `.venv/bin/python -m scripts.inspect_storage_preflight` with output filtered
  to a summary. The pinned model manifest and all five payloads verified. The
  `/srv/speech-platform` and `models` listings were partial under current
  permissions; no host contents were changed. This was not privileged
  qualification.
- **Operator command (not executed elevated)** — From the repository root,
  after reviewing the script:

  ```sh
  cd /home/master/speech-platform && sudo .venv/bin/python -m scripts.inspect_storage_preflight --pretty
  ```

  The JSON includes collection time and fixed scope; per-path ancestry,
  `uid`, `gid`, `mode_octal`, type, link count, device/inode, symlink target,
  unexpected hard-link flag and ACL status; mount ID/device/root/mountpoint,
  source, filesystem and options; capacity bytes; bounded directory entries
  and partial/truncated status; and model manifest identity plus each payload's
  expected size/hash and verification result. ACL values are reported only as
  `present`, `absent`, `unsupported`, `inaccessible` or `error`; no file
  contents are output. A nonzero exit with `inspection_incomplete` means the
  mount table or top-level inspection failed and must be reviewed.
- **NOT ESTABLISHED** — The operator has not reviewed or run the command with
  authorized privilege. Full storage ancestry, inaccessible descendants,
  ACLs, mount boundaries and existing model-root children remain unqualified.
- **OBSERVED** — `make verify PYTHON=.venv/bin/python` completed with exit 0.
  Ruff/format checks, config and Compose validation, release validation, Go
  vet/race tests, all discovered script tests, 61 STT service tests, Go build,
  governance validation, and STT lock checks passed. Compose commands only
  rendered or validated configuration.
- **OBSERVED** — `make governance-check PYTHON=.venv/bin/python` completed
  with exit 0; structural checks and two governance tests passed.
  `git diff --check` and explicit final-newline/trailing-whitespace checks
  passed. A static scan found no `sudo`, external-command invocation, Docker
  reference, or filesystem mutation operation in the inspector.

## Final snapshot capture preparation — 2026-10-20

- **OBSERVED — operator-reported** — The privileged command
  `sudo .venv/bin/python -m scripts.provision_models check --release
  releases/voiceservice-v0.1.2.yaml --store /srv/speech-platform/models`
  succeeded and reported
  `verified: large-v3-turbo -> /srv/speech-platform/models/86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`.
  Worker read access passed as UID `65532` with supplementary GID `988`
  (operator-reported exit code 0). Complete artifact integrity and worker
  read access are PASS for the operator's privileged verification environment.
- **OBSERVED** — A fresh read-only collector run returned release v0.1.2,
  descriptor digest
  `08ea79cecd719738ad8de6bfe5d1eb58ffe5b9775a14b4b91a8ee1c1675e9cf6`,
  candidate `g0-53e27ac5627c6911`, fingerprint
  `2d3a279deeea8be1bc8935eae22f7edebabb74f2c64a5641fb6c88b7313f432b`,
  and no observed runtime drift. Every service was running, healthy and
  `READY`; all report UID/GID `65532:65532`, supplementary GID `988`,
  read-only root filesystem, dropped capabilities and no-new-privileges.
  Project installed state is absent and the uncertainty marker is absent.
- **OBSERVED** — The collected runtime model bind remains
  `/var/tmp/speech-platform-m01e-fresh-v012/model-store/86d87665c1a794b30f99e800e7bc180a7615b82caea88e4b02c22a7214168ff6`.
  The retained store is `/srv/speech-platform/models/<same digest>`; no
  hierarchy creation, copy, relocation or bind change is needed for capture.
  Snapshot artifact validation now checks this retained store, while live
  collection continues to check the active `/var/tmp` bind.
- **OBSERVED** — Configuration/runtime identity pairs from this collection:

  | Service | Image digest | Configuration SHA-256 | Runtime / Compose SHA-256 | Health |
  | --- | --- | --- | --- | --- |
  | Gateway | `cab80ebc04bc78ec608c1f81c69ce1dfc8e048227e4892053c86783833064d30` | `66cafb9d52b0bd6ac89651fd8b22316ad07852aedae92f0e5d18a7c7860ec181` | `5aa15b9ccaa51ffe18062fad7b66021dfad9bc961583f1aa164ffd147261a1b4` / Compose `6031ccc4b7167665eea7beb3c8ea029abba4d5999e824a0299c64735bbde64fe` | healthy / READY |
  | STT | `31440127a13a1892f07fe480f013f1185c2d978ee981b5ce56fcd4a09a702ad8` | `87066bb617f1b6a85baa1b8f3ced401cae3a0c570b85b591a05555fed65ab4c4` | `f59627c30ff2a8c5fad2965376896dea682f1aec9a9c0bb31627d61e8a231109` / Compose `f59627c30ff2a8c5fad2965376896dea682f1aec9a9c0bb31627d61e8a231109` | healthy / READY |
  | TTS | `6ac1e87e1290f657dae613fafcf5357505c129185d34e1966f4b35a7dc8543c9d6` | `3a15d1d1c8ff61280bf59f26d67a15bd53d1356f4a6f3fce8b90ce7bdbee1261` | `3c4fa5ebdd4d0a3e4f62f75f48f68ceff400f92b75b4393bd6049664a1fae791` / Compose `5852729ea6267665eea7beb3c8ea029abba4d5999e824a0299c64735bbde64fe` | healthy / READY |
- **OBSERVED** — Remaining planner blockers are exactly
  `gateway:restore_inputs_missing`, `stt:restore_inputs_missing`, and
  `tts:restore_inputs_missing`; retained restoration inventory is
  `MISSING_OR_INCOMPLETE`. These block adoption and are the inputs this first
  snapshot is intended to preserve.
- **OBSERVED** — The source-only adapter preflight passed for project
  `speech-platform-m01e-fresh-v012`, release v0.1.2 and services
  `gateway`, `stt`, `tts`; HEAD equals approved source revision
  `6e99eaf4516afd0fa54e8a1fe6c7576b03bc529b`. The snapshot storage root and
  all writer-created descendants are absent: `restoration/`,
  `restoration/staging/`, `restoration/objects/`,
  `restoration/objects/sha256/`, `restoration/snapshots/`, and
  `restoration/snapshots/sha256/` below
  `private/deployment/m01e-fresh-v012/`. The writer creates private
  directories mode `0700` and files mode `0600`.
- **OBSERVED** — This shell cannot traverse `/srv/speech-platform/models`
  (UID `1000` lacks GID `988`); `sudo -n` and `setpriv --groups 988` were
  unavailable here. This does not override the separately attributed
  operator-reported privileged model check and worker access result. No
  storage inspection or model command changed host contents.
- **INTERPRETATION** — The production adapter can perform the first snapshot
  as one bounded operation: it validates tracked sources and configuration,
  renders Compose, gathers fresh Docker/readiness evidence, verifies release
  images and the persistent model store, then publishes the manifest last
  under the shared B2 lock. Missing retained inventory is expected before
  this initial capture.
- **NOT ESTABLISHED** — A real snapshot does not yet exist. Capture remains
  gated by separate operator approval. No snapshot directories were
  initialized, no lock was acquired, and no lifecycle operation was run.
  External backup qualification is outside this requested capture scope.
- **OBSERVED** — Focused regression suite
  `.venv/bin/python -m unittest scripts.test_snapshot_capture_adapter
  scripts.test_restore_snapshot scripts.test_inspect_storage_preflight -v`:
  39 passed. Its first run exposed a missing `git_source_revision` in the new
  test fixture; after correcting the fixture, the rerun passed.
- **OBSERVED** — Final `make verify PYTHON=.venv/bin/python`: exit 0.
  Ruff and format checks passed; config, Compose and release checks passed;
  Go vet/race tests and build passed; all 423 script tests and 61 service
  tests passed; governance validation and STT lock checks passed. Compose
  commands rendered or validated configuration; no containers were started
  or changed.
- **OBSERVED** — Final `make governance-check PYTHON=.venv/bin/python`: exit
  0; structural validation and two governance tests passed.
- **OBSERVED** — Final `git diff --check`: exit 0. The first full verification
  attempt stopped at Ruff format checking for the new test; the file was
  formatted and the complete verification command then passed.
- **OBSERVED** — Final independent read-only runtime identity summary
  confirmed the three pinned image references and configuration/runtime/
  Compose hashes in the table above; all health/readiness results remained
  healthy/READY.
- **OBSERVED** — After making the retained model-store path an explicit
  absolute adapter input, focused adapter and snapshot suites
  `.venv/bin/python -m unittest scripts.test_snapshot_capture_adapter
  scripts.test_restore_snapshot -v` passed 31 tests. The final
  `make verify PYTHON=.venv/bin/python` rerun after that change also exited 0.
