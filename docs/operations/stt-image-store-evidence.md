# One-time containerd image-store evidence collection

This procedure describes the diagnostic collector in
`scripts/collect_stt_image_store_evidence.py`. It is not part of the production
deployment validator and does not make `ctr` a production dependency. `ctr` is
used because the supported Docker Engine inspection API does not expose the
containerd image-record association and content-store blob bytes needed by the
existing `containerd_oci_manifest` evidence contract. Its CLI and output are
version-dependent; the collector fails closed when the observed output does
not match the expected structure. For the target's reported containerd 2.2.1,
the collector uses `ctr images list --quiet` followed by `ctr images inspect
<exact-reference>` for every listed record. It does not use `ctr images info`,
which the target's read-only diagnosis found unavailable.

The 2.2.1 `images inspect` command prints an image name and a descriptor tree.
The collector requires the first line to equal the exact listed reference and
parses exactly one root descriptor line in this form:

```text
└── <media-type> @sha256:<64 lowercase hex digits> (<positive decimal> bytes)
```

The byte count is the OCI descriptor's `Size` field as rendered by
containerd's descriptor printer. The parser does not read the human-readable
`images list` SIZE column, infer sizes, use loose matching, or accept changed
formatting. Every record in the complete `--quiet` inventory is inspected;
there must be exactly one whose root descriptor digest matches the approved
manifest, and its media type and descriptor size must also match the approved
archive. The collector then independently reads and verifies the exact raw
manifest and all referenced content, including each stored layer digest and
byte count.

This interface is a narrowly pinned diagnostic compatibility path, not a
stable machine-readable containerd API. The containerd v2.2.1 source defines
`images inspect` and its output formatter ([command](https://github.com/containerd/containerd/blob/v2.2.1/cmd/ctr/commands/images/inspect.go),
[descriptor printer](https://github.com/containerd/containerd/blob/v2.2.1/pkg/display/manifest_printer.go),
[quiet image listing](https://github.com/containerd/containerd/blob/v2.2.1/cmd/ctr/commands/images/images.go)).
The prior target diagnosis established that `images inspect` is available,
but this code change has not run the collector or verified the target's exact
rendered output. The next separately authorized operator run must therefore
confirm that it matches this strict grammar; otherwise collection stops with a
safe diagnostic code and no evidence is finalized.

## Authority and effects

An operator must run the collector on the already approved target, using an
existing, separately approved privileged-access mechanism. The collector does
not invoke `sudo`, ask for or store a password, and does not change host state.
It reads the explicitly selected containerd socket, namespace, image records,
content blobs, Docker image metadata, and the approved image archive. It does
not create containers, load or mutate images, access model files, initialize
CUDA, inspect environment variables, or contact Ollama or Dify.

The collector streams each target layer through SHA-256 and a byte counter. It
does not buffer or persist layer bytes. It retains only the bounded raw OCI
manifest bytes required by the current evidence schema; raw config and layer
contents are never written. The evidence contains image digests, descriptors,
RootFS diff IDs, a containerd image-record reference and raw-manifest base64.
It contains no credentials, labels, arbitrary command output, or Docker/containerd
environment values.

## Inputs

Supply all values explicitly; the collector has no default socket, namespace,
Docker context, image identity, archive or output path:

- Containerd socket path discovered by the operator from read-only host
  inspection.
- Containerd namespace, expected here to be `moby`, then confirmed by the
  collector against the namespace list returned by that socket.
- Explicit Docker context.
- Approved OCI manifest digest and config digest.
- The already transferred archive at
  `/home/master/speech-platform-staging/M02/M02-C/M02-C.6B/attempts/image-transfer-20261018-01/stt-cuda-image.tar`
  and its reviewed archive SHA-256. This archive is retained from Phase B;
  do not transfer it again for collection.
- A reviewed overall time bound for the content reads.
- A protected output path, or `-` to write only the typed JSON to stdout.

The operator must first confirm the host identity and socket using read-only
inspection. Do not guess a socket path or silently fall back to a default.
The explicit socket is checked to be a Unix socket and the explicit namespace
must be present. Docker inspection also uses the explicit context and image
digest. The collector requires the approved archive to contain exactly one
OCI manifest, verifies the archive hash, manifest/config/layer descriptor
hashes and sizes, config platform and RootFS diff IDs, and the Docker archive's
ordered layer paths against the OCI layer descriptors. Layer blob digests
identify stored (possibly compressed) bytes; RootFS diff IDs identify
uncompressed layer bytes and are checked separately through the exact config
bytes. It then requires exactly one containerd image
record whose target descriptor is the expected manifest and verifies the raw
manifest, raw config and every target content-store layer against those
approved bytes and descriptors. It compares Docker's reported image ID,
platform and RootFS diff IDs as well.

## Operator command

Use placeholders from reviewed local/target records; do not copy a mutable
image tag into this command. The collector can be streamed to a target Python
interpreter so no collector file needs to be installed on the host. The local
temporary output is created with a restrictive umask and promoted without
overwriting an existing evidence file. This is a command template: replace
every `<...>` token with a reviewed value before execution; do not paste it
literally because angle brackets have shell meaning:

```sh
set -eu
umask 077
PRIVATE_EVIDENCE_DIR='<existing operator-private directory with mode 0700>'
OUTPUT="$PRIVATE_EVIDENCE_DIR/image-store-evidence.json"
TEMP_OUTPUT="$(mktemp "$PRIVATE_EVIDENCE_DIR/.image-store-evidence.XXXXXX")"
trap 'rm -f "$TEMP_OUTPUT"' EXIT

ssh wisper 'sudo -n python3 - \
  --containerd-socket <operator-discovered-socket> \
  --namespace moby \
  --docker-context default \
  --manifest-digest sha256:7f710bf8fca9307d387a5d61ab84361756efa9c3e18a6d60e07b9c42b60eb45c \
  --config-digest sha256:3780e43b86717c877d82bb65c9944c8df7d497efd8446263dbd22b5092f1f406 \
  --archive /home/master/speech-platform-staging/M02/M02-C/M02-C.6B/attempts/image-transfer-20261018-01/stt-cuda-image.tar \
  --archive-sha256 cdb4d88c51c4b8ebcdceed3f119b622b29f046a2786fd39b4c478cd73fa06dfd \
  --overall-timeout-seconds <reviewed-positive-bound> \
  --output -' \
  < scripts/collect_stt_image_store_evidence.py > "$TEMP_OUTPUT"

.venv/bin/python -m json.tool "$TEMP_OUTPUT" >/dev/null
test "$(stat -c '%a' "$TEMP_OUTPUT")" = 600
ln "$TEMP_OUTPUT" "$OUTPUT"  # fails if prior evidence already exists
rm "$TEMP_OUTPUT"
trap - EXIT
sha256sum "$OUTPUT"
```

Run the command only after separately approving privileged diagnostic access.
`sudo -n` fails immediately if the configured privilege mechanism cannot run
without prompting. Do not pipe a password or weaken access controls. The
operator must choose and review the exact socket, archive path, timeout and
private output directory before execution. The output directory must be
operator-owned, mode `0700`, and have no ACL granting other access. The emitted
file is canonical JSON compatible with
`validate_local_artifact_identity()` and must be mode `0600`.
The collector walks the output parent using directory descriptors with
no-follow semantics, requires the final directory to be owned by the effective
operator and have no group/other mode bits, and atomically links the completed
file without replacing an existing path. The operator remains responsible for
reviewing ACLs on the output directory.

The command does not change the target. Hashing the archive and reading every
layer can produce substantial disk I/O; the operator should confirm that this
bounded read-only work is acceptable before running it. No retry is automatic.

## Review and profile binding

Treat the output as collected observations, not authenticated provenance.
Review its namespace, unique image-record reference/count, Docker identity,
platform, manifest/config relationship, descriptor order/sizes, RootFS diff IDs
and verified target layer digest list against the approved archive and build
record. The archive SHA-256 proves transfer-byte identity; build and evidence
file hashes bind reviewed bytes. Neither supplies an independent signature or
proves that the operator's observations are truthful. Docker labels are not
part of the evidence and cannot redefine approved identity.

Only after review, place the evidence file in the approved private evidence
tree, set restrictive ownership/mode and verify no permissive ACLs. Bind its
exact SHA-256 as `runtime.image_store_evidence_sha256` in the private
`local_image_id` profile. Keep the approved archive SHA, config digest, target
manifest identity, ordered layer identity, RootFS identity, platform, build
evidence digest, model identity and all configuration files consistent with
that reviewed record. Compute the existing configuration-set digest over the
profile, application, deployment, worker, Compose files, build evidence and
image-store evidence. Do not change the deployment identity contract or
compatibility allowlist as part of evidence collection.

The current workstation's `private/` root and `private/results/` directory
were observed with group/other permission bits, so they do not currently meet
the deployment validator's private-input policy. Do not write deployment
configuration or evidence under those paths until an operator has established
restrictive permissions for the complete path and verified ACL absence. This
collector does not change existing directory permissions.

The collector establishes evidence consistency only. It does not authorize
Compose creation or startup. Target Engine `29.1.3` remains outside the
currently verified local-image compatibility policy.
