# ADR-0010: Explicit local Docker image ID deployment identity

Status: Accepted for the offline local-image-ID deployment mode scope.

## Context

The production CUDA worker image was built locally and has an exact Docker image
ID, but no repository-qualified OCI manifest digest. A bounded create-only
compatibility experiment established that Compose can use that exact ID with
`pull_policy: never` on Docker Engine `29.7.2-ce` and Compose `5.6.0`. This is
version-specific evidence and does not establish container startup or worker
runtime behavior.

An image ID, OCI registry manifest digest, mutable tag, and `docker save`
archive SHA-256 identify different things. In particular, an image ID is the
digest of the local image configuration; it is not a registry manifest digest
or proof of the build inputs.

## Decision

Keep registry-digest mode unchanged and add a separately selected, strict
`runtime.identity_mode` discriminator:

- `registry_digest`: requires the existing repository-qualified immutable
  `image` reference, exact expected local `image_id`, and verified reference to
  image-ID relationship.
- `local_image_id`: requires an exact `sha256:<64 lowercase hex>` image ID and
  SHA-256 of private build evidence. It has no image-tag field or fallback.

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

The trust boundary is the operator-reviewed private deployment profile and
build-evidence file. The profile's `build_evidence_sha256` binds the exact
evidence-file bytes, and validation requires the evidence fields to match the
profile; the digest does not attest that the evidence is truthful or
independently signed. Before preparation or deployment, an authorized operator
must review and approve the profile, evidence provenance, and their protected
storage. Image labels are consistency checks only and cannot replace that
review. Evidence must never supply or redefine the approved image ID: the
private profile remains authoritative, and any mismatch fails closed.

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
- `docker save` archive SHA-256 protects transfer integrity only. After
  `docker load`, the exact image ID and image inspection must still match the
  private approved build record.
- Local daemon retention, access control and rollback become operator duties.
  Previously verified image IDs and immutable model/configuration releases must
  be retained explicitly; no mutable tags or automatic fallback are allowed.
- The compatibility result is narrow. No image transfer, production container
  start, CUDA execution or deployment is implied by this ADR.
