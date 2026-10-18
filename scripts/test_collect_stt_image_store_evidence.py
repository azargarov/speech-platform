from __future__ import annotations

import hashlib
import gzip
import io
import json
import os
import socket
import subprocess
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts.collect_stt_image_store_evidence import (
    OCI_CONFIG,
    OCI_MANIFEST,
    CollectionError,
    SubprocessReader,
    _atomic_private_json,
    _parse_inspect_output,
    collect_evidence,
)
from scripts.stt_deployment_profile import validate_local_artifact_identity


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _tar_bytes(payload: bytes) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:") as archive:
        info = tarfile.TarInfo("fixture.bin")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return output.getvalue()


class Fixture:
    def __init__(
        self,
        root: Path,
        *,
        media_type=None,
        declared_layer_size=None,
        compressed=False,
        reverse_docker_layer_order=False,
    ):
        self.root = root
        self.uncompressed_layers = [_tar_bytes(b"one"), _tar_bytes(b"two")]
        self.layers = (
            [gzip.compress(layer, mtime=0) for layer in self.uncompressed_layers]
            if compressed
            else self.uncompressed_layers
        )
        self.layer_digests = [_digest(layer) for layer in self.layers]
        self.config = {
            "architecture": "amd64",
            "os": "linux",
            "rootfs": {
                "type": "layers",
                "diff_ids": [_digest(layer) for layer in self.uncompressed_layers],
            },
        }
        self.raw_config = json.dumps(self.config, separators=(",", ":")).encode()
        self.config_digest = _digest(self.raw_config)
        layer_descriptors = []
        for index, layer in enumerate(self.layers):
            layer_descriptors.append(
                {
                    "mediaType": media_type
                    or (
                        "application/vnd.oci.image.layer.v1.tar+gzip"
                        if compressed
                        else "application/vnd.oci.image.layer.v1.tar"
                    ),
                    "digest": self.layer_digests[index],
                    "size": (
                        declared_layer_size
                        if index == 0 and declared_layer_size is not None
                        else len(layer)
                    ),
                }
            )
        self.manifest = {
            "schemaVersion": 2,
            "mediaType": OCI_MANIFEST,
            "config": {
                "mediaType": OCI_CONFIG,
                "digest": self.config_digest,
                "size": len(self.raw_config),
            },
            "layers": layer_descriptors,
        }
        self.raw_manifest = json.dumps(self.manifest, separators=(",", ":")).encode()
        self.manifest_digest = _digest(self.raw_manifest)
        self.index = {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "manifests": [
                {
                    "mediaType": OCI_MANIFEST,
                    "digest": self.manifest_digest,
                    "size": len(self.raw_manifest),
                }
            ],
        }
        self.archive_path = root / "approved-image.tar"
        with tarfile.open(self.archive_path, "w:") as archive:
            self._add(archive, "oci-layout", b'{"imageLayoutVersion":"1.0.0"}')
            self._add(archive, "index.json", json.dumps(self.index).encode())
            self._add(
                archive,
                "manifest.json",
                json.dumps(
                    [
                        {
                            "Config": f"blobs/sha256/{self.config_digest[7:]}",
                            "RepoTags": None,
                            "Layers": [
                                f"blobs/sha256/{digest[7:]}"
                                for digest in (
                                    list(reversed(self.layer_digests))
                                    if reverse_docker_layer_order
                                    else self.layer_digests
                                )
                            ],
                        }
                    ]
                ).encode(),
            )
            self._add(
                archive,
                f"blobs/sha256/{self.manifest_digest[7:]}",
                self.raw_manifest,
            )
            self._add(
                archive,
                f"blobs/sha256/{self.config_digest[7:]}",
                self.raw_config,
            )
            for digest, layer in zip(self.layer_digests, self.layers, strict=True):
                self._add(archive, f"blobs/sha256/{digest[7:]}", layer)
        self.archive_sha256 = hashlib.sha256(self.archive_path.read_bytes()).hexdigest()

    @staticmethod
    def _add(archive, name, raw):
        info = tarfile.TarInfo(name)
        info.size = len(raw)
        archive.addfile(info, io.BytesIO(raw))


class FakeRunner:
    def __init__(self, fixture: Fixture):
        self.fixture = fixture
        self.references = ["speech-platform/stt-cuda:approved"]
        self.blobs = {
            fixture.manifest_digest: fixture.raw_manifest,
            fixture.config_digest: fixture.raw_config,
            **dict(zip(fixture.layer_digests, fixture.layers, strict=True)),
        }
        self.command_failure = None
        self.inspect_output = {}
        self.malformed_inspect = False
        self.stdout_rootfs = fixture.config["rootfs"]["diff_ids"]
        for reference in self.references:
            self.inspect_output[reference] = {
                "mediaType": OCI_MANIFEST,
                "digest": fixture.manifest_digest,
                "size": len(fixture.raw_manifest),
            }
        self.commands = []

    def run_text(self, argv, deadline):
        self.commands.append(tuple(argv))
        if self.command_failure == tuple(argv):
            raise CollectionError("command_failed")
        if "namespaces" in argv:
            return "moby\n"
        if "images" in argv and "list" in argv:
            return "".join(f"{ref}\n" for ref in self.references)
        if "images" in argv and "inspect" in argv:
            reference = argv[-1]
            if self.malformed_inspect:
                return f"{reference}\n└── not-a-descriptor\n"
            target = self.inspect_output[reference]
            return (
                f"{reference}\n"
                "│ Created: 2026-01-01T00:00:00Z\n"
                "│ Updated: 2026-01-01T00:00:00Z\n"
                '│ Label "example": "sanitized"\n'
                f"└── {target['mediaType']} @{target['digest']} "
                f"({target['size']} bytes)\n"
            )
        if "images" in argv and "info" in argv:
            # The supported target CLI reports this legacy subcommand as an
            # unsuccessful command; the collector must not depend on it.
            raise CollectionError("command_failed")
        if "image" in argv and "inspect" in argv:
            return (
                f"{self.fixture.manifest_digest}|linux/amd64|"
                f"{json.dumps(self.stdout_rootfs)}\n"
            )
        raise AssertionError("unexpected command shape")

    def stream(self, argv, deadline):
        digest = argv[-1]
        if digest not in self.blobs:
            raise CollectionError("command_failed")
        data = self.blobs[digest]
        for offset in range(0, len(data), 13):
            yield data[offset : offset + 13]


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.root.chmod(0o700)
        self.fixture = Fixture(self.root)
        self.fake_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket_path = str(self.root / "containerd.sock")
        self.fake_socket.bind(self.socket_path)
        self.runner = FakeRunner(self.fixture)

    def tearDown(self):
        self.fake_socket.close()
        self.temporary.cleanup()

    def _collect(self, **overrides):
        options = {
            "socket_path": self.socket_path,
            "namespace": "moby",
            "docker_context": "default",
            "manifest_digest": self.fixture.manifest_digest,
            "config_digest": self.fixture.config_digest,
            "archive_path": self.fixture.archive_path,
            "archive_sha256": self.fixture.archive_sha256,
            "overall_timeout_seconds": 60,
            "runner": self.runner,
        }
        options.update(overrides)
        return collect_evidence(**options)

    def test_parser_accepts_observed_target_root_and_ignores_child_descriptors(self):
        reference = (
            "moby-dangling@sha256:"
            "7f710bf8fca9307d387a5d61ab84361756efa9c3e18a6d60e07b9c42b60eb45c"
        )
        output = (
            f"{reference}\n"
            "└── application/vnd.oci.image.manifest.v1+json @sha256:"
            "7f710bf8fca9307d387a5d61ab84361756efa9c3e18a6d60e07b9c42b60eb45c "
            "(1772 bytes)\n"
            "    ├── application/vnd.oci.image.config.v1+json @sha256:"
            "3780e43b86717c877d82bb65c9944c8df7d497efd8446263dbd22b5092f1f406 "
            "(10673 bytes)\n"
        )

        self.assertEqual(
            _parse_inspect_output(output, reference),
            {
                "mediaType": "application/vnd.oci.image.manifest.v1+json",
                "digest": (
                    "sha256:7f710bf8fca9307d387a5d61ab84361756efa9c3e18a6d60e07b9c42b60eb45c"
                ),
                "size": 1772,
            },
        )

    def test_valid_evidence_matches_existing_typed_contract(self):
        evidence = self._collect()
        self.assertEqual(evidence["identity_kind"], "containerd_oci_manifest")
        self.assertEqual(evidence["matching_image_records"], 1)
        self.assertEqual(evidence["verified_layer_digests"], self.fixture.layer_digests)
        evidence_path = self.root / "evidence.json"
        evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
        runtime = {
            "image_id": self.fixture.manifest_digest,
            "platform": "linux/amd64",
            "artifact_identity": {
                key: value
                for key, value in evidence.items()
                if key
                not in {
                    "schema_version",
                    "docker_image_id",
                    "platform",
                    "raw_manifest_base64",
                }
            },
        }
        runtime["image_store_evidence_sha256"] = hashlib.sha256(
            evidence_path.read_bytes()
        ).hexdigest()
        validate_local_artifact_identity(
            runtime,
            evidence,
            evidence_path,
            self.fixture.archive_path,
        )

    def test_compressed_layer_descriptor_is_not_confused_with_rootfs_diff_id(self):
        fixture = Fixture(self.root, compressed=True)
        evidence = collect_evidence(
            socket_path=self.socket_path,
            namespace="moby",
            docker_context="default",
            manifest_digest=fixture.manifest_digest,
            config_digest=fixture.config_digest,
            archive_path=fixture.archive_path,
            archive_sha256=fixture.archive_sha256,
            overall_timeout_seconds=60,
            runner=FakeRunner(fixture),
        )
        self.assertNotEqual(fixture.layer_digests, fixture.config["rootfs"]["diff_ids"])
        self.assertEqual(evidence["verified_layer_digests"], fixture.layer_digests)
        self.assertEqual(
            evidence["rootfs_diff_ids"], fixture.config["rootfs"]["diff_ids"]
        )

    def test_layer_digest_mismatch_fails_closed(self):
        self.runner.blobs[self.fixture.layer_digests[0]] = b"x" * len(
            self.fixture.layers[0]
        )
        with self.assertRaisesRegex(CollectionError, "content_digest_mismatch"):
            self._collect()

    def test_layer_size_mismatch_fails_closed(self):
        fixture = Fixture(self.root, declared_layer_size=1)
        with self.assertRaisesRegex(CollectionError, "archive_layer_mismatch"):
            collect_evidence(
                socket_path=self.socket_path,
                namespace="moby",
                docker_context="default",
                manifest_digest=fixture.manifest_digest,
                config_digest=fixture.config_digest,
                archive_path=fixture.archive_path,
                archive_sha256=fixture.archive_sha256,
                overall_timeout_seconds=60,
                runner=FakeRunner(fixture),
            )

    def test_docker_archive_layer_order_mismatch_fails_closed(self):
        fixture = Fixture(self.root, reverse_docker_layer_order=True)
        with self.assertRaisesRegex(
            CollectionError, "docker_archive_layer_order_mismatch"
        ):
            collect_evidence(
                socket_path=self.socket_path,
                namespace="moby",
                docker_context="default",
                manifest_digest=fixture.manifest_digest,
                config_digest=fixture.config_digest,
                archive_path=fixture.archive_path,
                archive_sha256=fixture.archive_sha256,
                overall_timeout_seconds=60,
                runner=FakeRunner(fixture),
            )

    def test_missing_content_fails_closed(self):
        del self.runner.blobs[self.fixture.config_digest]
        with self.assertRaisesRegex(CollectionError, "command_failed"):
            self._collect()

    def test_truncated_layer_stream_fails_closed(self):
        self.runner.blobs[self.fixture.layer_digests[0]] = self.fixture.layers[0][:-1]
        with self.assertRaisesRegex(CollectionError, "content_truncated"):
            self._collect()

    def test_multiple_matching_image_records_fail_closed(self):
        self.runner.references.append("other/stt:second-record")
        self.runner.inspect_output[self.runner.references[-1]] = {
            "mediaType": OCI_MANIFEST,
            "digest": self.fixture.manifest_digest,
            "size": len(self.fixture.raw_manifest),
        }
        with self.assertRaisesRegex(CollectionError, "matching_image_record_ambiguous"):
            self._collect()

    def test_missing_matching_image_record_fails_closed(self):
        self.runner.inspect_output[self.runner.references[0]]["digest"] = (
            "sha256:" + "a" * 64
        )
        with self.assertRaisesRegex(CollectionError, "matching_image_record_missing"):
            self._collect()

    def test_uses_supported_inspect_instead_of_unsupported_info(self):
        evidence = self._collect()
        self.assertEqual(evidence["image_record_reference"], self.runner.references[0])
        image_commands = [
            command for command in self.runner.commands if "images" in command
        ]
        self.assertTrue(any("inspect" in command for command in image_commands))
        self.assertFalse(any("info" in command for command in image_commands))

    def test_descriptor_size_and_media_type_must_match_approved_manifest(self):
        self.runner.inspect_output[self.runner.references[0]]["size"] += 1
        with self.assertRaisesRegex(CollectionError, "image_record_manifest_mismatch"):
            self._collect()

        self.runner.inspect_output[self.runner.references[0]] = {
            "mediaType": "application/octet-stream",
            "digest": self.fixture.manifest_digest,
            "size": len(self.fixture.raw_manifest),
        }
        with self.assertRaisesRegex(CollectionError, "image_record_manifest_mismatch"):
            self._collect()

    def test_unexpected_media_type_fails_closed(self):
        fixture = Fixture(self.root, media_type="application/x-unknown")
        with self.assertRaisesRegex(CollectionError, "layer_media_type_unsupported"):
            collect_evidence(
                socket_path=self.socket_path,
                namespace="moby",
                docker_context="default",
                manifest_digest=fixture.manifest_digest,
                config_digest=fixture.config_digest,
                archive_path=fixture.archive_path,
                archive_sha256=fixture.archive_sha256,
                overall_timeout_seconds=60,
                runner=FakeRunner(fixture),
            )

    def test_command_failure_and_malformed_inspect_output_fail_closed(self):
        self.runner.malformed_inspect = True
        with self.assertRaisesRegex(CollectionError, "image_record_descriptor_invalid"):
            self._collect()
        self.runner.malformed_inspect = False
        self.runner.command_failure = (
            "ctr",
            "--address",
            self.socket_path,
            "--namespace",
            "moby",
            "images",
            "inspect",
            self.runner.references[0],
        )
        with self.assertRaisesRegex(CollectionError, "command_failed"):
            self._collect()
        self.runner.command_failure = None
        self.runner.command_failure = (
            "ctr",
            "--address",
            self.socket_path,
            "--namespace",
            "moby",
            "namespaces",
            "list",
            "--quiet",
        )
        with self.assertRaisesRegex(CollectionError, "command_failed"):
            self._collect()

    def test_missing_or_duplicate_root_descriptor_fails_closed(self):
        reference = self.runner.references[0]
        self.runner.inspect_output[reference] = {
            "mediaType": OCI_MANIFEST,
            "digest": self.fixture.manifest_digest,
            "size": len(self.fixture.raw_manifest),
        }
        original_run = self.runner.run_text

        def missing_descriptor(argv, deadline):
            if "images" in argv and "inspect" in argv:
                return f"{reference}\nimage metadata only\n"
            return original_run(argv, deadline)

        self.runner.run_text = missing_descriptor
        with self.assertRaisesRegex(CollectionError, "image_record_descriptor_missing"):
            self._collect()

        def duplicate_descriptor(argv, deadline):
            if "images" in argv and "inspect" in argv:
                descriptor = (
                    f"└── {OCI_MANIFEST} @{self.fixture.manifest_digest} "
                    f"({len(self.fixture.raw_manifest)} bytes)"
                )
                return f"{reference}\n{descriptor}\n{descriptor}\n"
            return original_run(argv, deadline)

        self.runner.run_text = duplicate_descriptor
        with self.assertRaisesRegex(
            CollectionError, "image_record_descriptor_ambiguous"
        ):
            self._collect()

    def test_missing_namespace_and_invalid_socket_fail_closed(self):
        self.runner.run_text = lambda argv, deadline: "other\n"
        with self.assertRaisesRegex(CollectionError, "namespace_not_found"):
            self._collect()
        with self.assertRaisesRegex(CollectionError, "containerd_socket_invalid"):
            self._collect(socket_path=str(self.root))

    def test_wrong_expected_identity_fails_closed(self):
        with self.assertRaisesRegex(CollectionError, "manifest_identity_mismatch"):
            self._collect(manifest_digest="sha256:" + "a" * 64)
        with self.assertRaisesRegex(CollectionError, "config_identity_mismatch"):
            self._collect(config_digest="sha256:" + "b" * 64)

    def test_wrong_docker_rootfs_fails_closed(self):
        self.runner.stdout_rootfs = ["sha256:" + "c" * 64]
        with self.assertRaisesRegex(CollectionError, "docker_rootfs_mismatch"):
            self._collect()

    def test_private_atomic_output_and_no_overwrite(self):
        evidence = self._collect()
        path = self.root / "evidence.json"
        _atomic_private_json(path, evidence)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(CollectionError, "output_already_exists"):
            _atomic_private_json(path, evidence)

    def test_output_parent_symlink_is_rejected_without_redirecting_evidence(self):
        private_target = self.root / "real-private"
        private_target.mkdir(mode=0o700)
        symlink_parent = self.root / "redirect"
        symlink_parent.symlink_to(private_target, target_is_directory=True)
        with self.assertRaisesRegex(CollectionError, "output_directory_invalid"):
            _atomic_private_json(symlink_parent / "evidence.json", {"ok": True})
        self.assertEqual(list(private_target.iterdir()), [])

    def test_subprocess_reader_uses_mocked_pipe_and_discards_stderr(self):
        read_fd, write_fd = os.pipe()
        output = b"moby\n"
        os.write(write_fd, output)
        os.close(write_fd)
        process = mock.Mock()
        process.stdout = os.fdopen(read_fd, "rb", buffering=0)
        process.poll.return_value = 0
        process.wait.return_value = 0
        with mock.patch(
            "scripts.collect_stt_image_store_evidence.subprocess.Popen",
            return_value=process,
        ) as popen:
            actual = list(
                SubprocessReader().stream(
                    ["ctr", "namespaces", "list"], time.monotonic() + 60
                )
            )
        self.assertEqual(b"".join(actual), output)
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)

    def test_subprocess_reader_classifies_nonzero_exit_without_stderr(self):
        read_fd, write_fd = os.pipe()
        os.close(write_fd)
        process = mock.Mock()
        process.stdout = os.fdopen(read_fd, "rb", buffering=0)
        process.poll.return_value = 7
        process.wait.return_value = 7
        with mock.patch(
            "scripts.collect_stt_image_store_evidence.subprocess.Popen",
            return_value=process,
        ) as popen:
            with self.assertRaisesRegex(CollectionError, "command_failed"):
                list(
                    SubprocessReader().stream(
                        ["ctr", "content", "get", "sha256:" + "0" * 64],
                        time.monotonic() + 60,
                    )
                )
        self.assertEqual(popen.call_args.kwargs["stderr"], subprocess.DEVNULL)


if __name__ == "__main__":
    unittest.main()
