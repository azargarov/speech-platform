# ADR-0010: Explicit local image identity for CUDA STT deployment

Status: Accepted for the offline local-image-ID deployment mode scope; revised
content-identity contract pending review.

## Context

The production CUDA worker image was built locally and has an exact Docker image
ID, but no repository-qualified OCI manifest digest. A bounded create-only
compatibility experiment established that Compose can use that exact ID with
`pull_policy: never` on Docker Engine `29.7.2-ce` and Compose `5.6.0`. This is
version-specific evidence and does not establish container startup or worker
runtime behavior.

These identifiers are distinct and must not be substituted for each other:

- A Docker image ID is the identifier returned by the particular Docker image
  store. Its relationship to OCI descriptors must be established from that
  store's inspected content, not assumed universally.
- An OCI image configuration digest is SHA-256 of the raw configuration blob.
- An OCI manifest digest is SHA-256 of the raw manifest bytes; its descriptors
  bind the configuration and ordered layer blobs.
- A Docker repository digest (`RepoDigest`) is a repository-qualified manifest
  identity. It is not the local image ID.
- A RootFS diff ID identifies an uncompressed layer tar stream, not an OCI
  compressed layer descriptor.
- A `docker save` archive SHA-256 identifies the complete transfer archive
  bytes, not a manifest or configuration object.

The target evidence supplied for the identity correction records one specific
observation: on target Docker Engine 29.1.3 with containerd 2.2.1 and the
containerd image store, Docker reported `7f710bf8…b60eb45c`; the associated OCI
manifest had that digest and referenced configuration digest
`3780e43b…09f1f406`. The raw configuration bytes hashed to the configuration
digest, and the transferred archive hash was
`cdb4d88c…3fa06dfd`. This evidence explains the earlier failed comparison:
the check compared the target's manifest-level Docker identifier with the
workstation's configuration digest. It is evidence about this image and store
observation only, not a general guarantee about Docker/containerd behavior.

## Decision

Keep registry-digest mode unchanged and add a separately selected, strict
`runtime.identity_mode` discriminator:

- `registry_digest`: requires the existing repository-qualified immutable
  `image` reference, exact expected local `image_id`, and verified reference to
  image-ID relationship.
- `local_image_id`: requires explicit typed image-store evidence, the exact
  store-reported identifier, the approved archive SHA-256, raw configuration
  digest, platform and RootFS diff IDs. For a containerd OCI-manifest identity,
  it additionally requires the namespace and unique image-record association,
  raw manifest bytes and digest, the manifest-to-config relationship, ordered
  layer descriptor identities and separately recorded verification of those
  layer contents. It has no image-tag field or fallback.

Both modes retain the source revision, platform-specific base manifest digest,
CUDA lock digest, platform, model revision and manifest digest, complete
configuration-set digest, resource policy, GPU identity and Compose security
requirements. The local evidence digest is checked against the private build
record; read-only Docker inspection then compares the installed image's ID,
platform, user, entrypoint and provenance labels with those validated inputs.
Labels are consistency checks, not independent provenance proof.

The local-image Compose deployment path requires exact-ID `image`,
`pull_policy: never`, and no build directive. The only currently supported
local-image CLI versions are Engine `29.7.2-ce` and Compose `5.6.0`; other
versions fail closed until separately tested.

The trust boundary is the operator-reviewed private deployment profile,
build-evidence file, approved archive digest and image-store evidence file.
The profile pins the evidence file hashes and expected identities; validation
checks the archive configuration and RootFS data, the raw OCI manifest digest
and descriptor relationships, and consistency of the recorded image-store
identity. The layer-content verification observations are bound to the reviewed
image-store evidence; the validator does not independently fetch target
containerd blobs. These hashes establish integrity relative to reviewed inputs,
not independent authenticity or a signature. Before preparation or deployment,
an authorized operator must review how evidence was collected and approve its
provenance and protected storage. Image labels and parsed configuration fields
are supporting consistency checks only. Evidence must never supply or redefine
the approved identity: the private profile remains authoritative, and missing,
contradictory, ambiguous or unsupported evidence fails closed.

Before starting a newly created deployment container, an operator must inspect
that exact full container ID and verify its configured image ID equals the
validated expected ID and that it remains in `created` state. Creation and
start are separate authorization gates. This is an operator-enforced sequence,
not an atomic create-and-start guard: anyone able to issue an independent start
through Docker or another orchestration path could bypass the procedure. Keep
start authorization withheld until exact-ID verification succeeds.

## Consequences

- Local image mode supports offline transfer and deployment without a registry,
  while the original registry mode remains available.
- The archive SHA-256 protects transfer integrity only. A store-specific
  identity is accepted only when the approved profile selects its evidence
  kind and the content relationships are verified; matching labels or a
  matching config alone are insufficient.
- Local daemon retention, access control and rollback become operator duties.
  Previously verified image IDs and immutable model/configuration releases must
  be retained explicitly; no mutable tags or automatic fallback are allowed.
- The workstation create-only compatibility result remains limited to Engine
  `29.7.2-ce` / Compose `5.6.0`. The target Engine 29.1.3 observation does not
  expand that allowlist. No target deployment compatibility, production
  container start, CUDA execution or deployment is implied by this ADR.
