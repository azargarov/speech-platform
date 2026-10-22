"""Synthetic tests for immutable model cache validation and staging."""

import hashlib
import os
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from scripts.model_artifacts import (
    ModelProvisionError,
    check_models,
    download_from_huggingface,
    model_directory,
    provision_models,
)


def digest(contents):
    return hashlib.sha256(contents).hexdigest()


class ModelArtifactProvisioning(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = self.root / "private/model-store"
        self.manifest_dir = self.root / "releases/artifacts"
        self.manifest_dir.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def create_model(
        self, artifact_id="model", contents=b"fixture weights", revision="a" * 40
    ):
        manifest = {
            "manifest_version": 1,
            "model": {
                "family": "fixture",
                "repository": f"acme/{artifact_id}",
                "revision": revision,
            },
            "artifact": {
                "format": "fixture-v1",
                "tool": "test-fixture",
                "tool_version": "1",
            },
            "files": [
                {
                    "path": "weights.bin",
                    "size_bytes": len(contents),
                    "sha256": digest(contents),
                }
            ],
        }
        canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        manifest_digest = hashlib.sha256(canonical).hexdigest()
        manifest_path = self.manifest_dir / f"{artifact_id}-{revision[:6]}.yaml"
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
        reference = {
            "id": artifact_id,
            "source": "huggingface_hub",
            "family": "fixture",
            "repository": f"acme/{artifact_id}",
            "revision": revision,
            "artifact_format": "fixture-v1",
            "manifest_path": manifest_path.relative_to(self.root).as_posix(),
            "manifest_sha256": manifest_digest,
        }
        return reference, contents

    @staticmethod
    def release(*models):
        return {"services": {"stt": {"required_model_artifacts": list(models)}}}

    @staticmethod
    def write_download(contents):
        def download(model, relative_path, destination, maximum_bytes):
            if len(contents) > maximum_bytes:
                raise ModelProvisionError("fixture exceeds the manifest size")
            destination.write_bytes(contents)

        return download

    def test_valid_install_then_cache_check_and_reuse(self):
        model, contents = self.create_model()
        release = self.release(model)
        downloads = []

        def download(entry, relative_path, destination, maximum_bytes):
            downloads.append(relative_path)
            self.assertLessEqual(len(contents), maximum_bytes)
            destination.write_bytes(contents)

        installed = provision_models(release, self.store, self.root, download)
        self.assertEqual(installed[0].status, "installed")
        existing_files = [
            path
            for path in model_directory(self.store, model).rglob("*")
            if path.is_file()
        ]
        before = {
            path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
            for path in existing_files
        }
        checked = check_models(release, self.store, self.root)
        self.assertEqual(checked[0].status, "verified")
        self.assertEqual(
            before,
            {
                path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
                for path in existing_files
            },
            "verification must not rewrite historical artifact files or metadata",
        )

        reused = provision_models(
            release,
            self.store,
            self.root,
            lambda *_: self.fail("verified cache entries must not be downloaded again"),
        )
        self.assertEqual(reused[0].status, "reused")
        self.assertEqual(downloads, ["weights.bin"])

    def test_group_readable_staging_uses_the_configured_owner_and_reader_group(self):
        model, contents = self.create_model()
        store = self.root / "group-readable-store"
        results = provision_models(
            self.release(model),
            store,
            self.root,
            self.write_download(contents),
            directory_mode=0o2750,
            file_mode=0o640,
            expected_owner_uid=os.geteuid(),
            expected_group_gid=os.getegid(),
        )
        self.assertEqual(results[0].status, "installed")
        directory = model_directory(store, model)
        self.assertEqual(directory.stat().st_mode & 0o7777, 0o2750)
        self.assertEqual((directory / "manifest.yaml").stat().st_mode & 0o777, 0o640)
        self.assertEqual(
            (directory / "artifact/weights.bin").stat().st_mode & 0o777, 0o640
        )
        self.assertEqual(directory.stat().st_gid, os.getegid())

    def test_production_layout_allows_parent_group_different_from_reader_gid(self):
        model, contents = self.create_model()
        parent = self.root / "speech-platform"
        parent.mkdir(mode=0o711)
        parent.chmod(0o711)
        store = parent / "models"
        store.mkdir(mode=0o2710)
        store.chmod(0o2710)

        original_lstat = Path.lstat
        original_stat = Path.stat

        def production_parent_metadata(path):
            result = original_lstat(path)
            if path in {self.root, parent}:
                values = list(result)
                values[4] = 0
                values[5] = 0
                return os.stat_result(values)
            return result

        def production_store_metadata(path, *args, **kwargs):
            result = original_stat(path, *args, **kwargs)
            if path == store or store in path.parents:
                values = list(result)
                values[4] = 0
                values[5] = 988
                return os.stat_result(values)
            return result

        with (
            mock.patch.object(Path, "lstat", production_parent_metadata),
            mock.patch.object(Path, "stat", production_store_metadata),
            mock.patch("scripts.model_artifacts.os.geteuid", return_value=0),
            mock.patch("scripts.model_artifacts.os.getegid", return_value=988),
        ):
            results = provision_models(
                self.release(model),
                store,
                self.root,
                self.write_download(contents),
                directory_mode=0o2750,
                file_mode=0o640,
                expected_owner_uid=0,
                expected_group_gid=988,
            )
            self.assertEqual(results[0].status, "installed")
            self.assertEqual(store.stat().st_uid, 0)
            self.assertEqual(store.stat().st_gid, 988)
            self.assertEqual(model_directory(store, model).stat().st_gid, 988)

        self.assertEqual(results[0].status, "installed")
        self.assertEqual(store.stat().st_mode & 0o7777, 0o2710)
        directory = model_directory(store, model)
        self.assertEqual(directory.stat().st_mode & 0o7777, 0o2750)
        self.assertEqual((directory / "manifest.yaml").stat().st_mode & 0o777, 0o640)
        self.assertEqual(
            (directory / "artifact/weights.bin").stat().st_mode & 0o777, 0o640
        )
        self.assertEqual(directory.stat().st_gid, os.getegid())

    def test_missing_cache_is_reported_without_network_activity(self):
        model, _ = self.create_model()
        with self.assertRaisesRegex(ModelProvisionError, "not cached"):
            check_models(self.release(model), self.store, self.root)
        self.assertFalse(self.store.exists())

    def test_missing_required_file_in_cached_version_is_rejected(self):
        model, contents = self.create_model()
        release = self.release(model)
        provision_models(release, self.store, self.root, self.write_download(contents))
        target = model_directory(self.store, model) / "artifact/weights.bin"
        target.unlink()
        with self.assertRaises(ModelProvisionError):
            check_models(release, self.store, self.root)

    def test_corrupt_existing_version_is_rejected_without_replacement(self):
        model, contents = self.create_model()
        release = self.release(model)
        provision_models(release, self.store, self.root, self.write_download(contents))
        directory = model_directory(self.store, model)
        target = directory / "artifact/weights.bin"
        target.write_bytes(b"corrupt")
        corrupted_before = target.read_bytes()

        with self.assertRaises(ModelProvisionError):
            provision_models(
                release,
                self.store,
                self.root,
                lambda *_: self.fail(
                    "a corrupt content-addressed version must not be overwritten"
                ),
            )
        self.assertEqual(target.read_bytes(), corrupted_before)

    def test_download_checksum_mismatch_leaves_no_activated_directory(self):
        model, expected_contents = self.create_model(contents=b"good")
        actual_contents = b"evil"
        with self.assertRaisesRegex(
            ModelProvisionError,
            "failed local verification: artifact file digest mismatch for "
            "weights.bin: expected SHA-256 "
            + digest(expected_contents)
            + ", got "
            + digest(actual_contents),
        ) as raised:
            provision_models(
                self.release(model),
                self.store,
                self.root,
                self.write_download(actual_contents),
            )
        self.assertIsNotNone(raised.exception.__cause__)
        self.assertIsNotNone(raised.exception.__cause__.__cause__)
        self.assertFalse(model_directory(self.store, model).exists())
        self.assertEqual(list(self.store.glob(".staging-*")), [])

    def test_interrupted_download_cleans_staging_and_preserves_existing_version(self):
        existing, existing_bytes = self.create_model("existing", b"stable content")
        failing, _ = self.create_model("candidate", b"candidate content")
        existing_release = self.release(existing)
        provision_models(
            existing_release,
            self.store,
            self.root,
            self.write_download(existing_bytes),
        )
        existing_path = model_directory(self.store, existing) / "artifact/weights.bin"
        original = existing_path.read_bytes()

        def interrupt(_model, _path, destination, _size):
            destination.write_bytes(b"partial")
            raise OSError("simulated interrupted transfer")

        with self.assertRaises(ModelProvisionError):
            provision_models(
                self.release(existing, failing), self.store, self.root, interrupt
            )
        self.assertEqual(existing_path.read_bytes(), original)
        self.assertFalse(model_directory(self.store, failing).exists())
        self.assertEqual(list(self.store.glob(".staging-*")), [])

    def test_keyboard_interrupt_cleans_staging_without_activation(self):
        model, _ = self.create_model()

        def interrupt(*_args):
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            provision_models(self.release(model), self.store, self.root, interrupt)
        self.assertFalse(model_directory(self.store, model).exists())
        self.assertEqual(list(self.store.glob(".staging-*")), [])

    def test_previous_verified_model_versions_are_retained(self):
        first, first_bytes = self.create_model("large-v3-turbo", b"version one")
        second, second_bytes = self.create_model(
            "large-v3-turbo", b"version two", revision="b" * 40
        )
        provision_models(
            self.release(first), self.store, self.root, self.write_download(first_bytes)
        )
        provision_models(
            self.release(second),
            self.store,
            self.root,
            self.write_download(second_bytes),
        )
        self.assertEqual(
            (model_directory(self.store, first) / "artifact/weights.bin").read_bytes(),
            first_bytes,
        )
        self.assertEqual(
            (model_directory(self.store, second) / "artifact/weights.bin").read_bytes(),
            second_bytes,
        )
        self.assertNotEqual(first["manifest_sha256"], second["manifest_sha256"])

    def test_shared_provisioner_accepts_artifacts_for_another_service(self):
        model, contents = self.create_model("tts-fixture", b"tts weights")
        release = {"services": {"tts": {"required_model_artifacts": [model]}}}
        result = provision_models(
            release, self.store, self.root, self.write_download(contents)
        )
        self.assertEqual(result[0].status, "installed")
        self.assertEqual(
            (result[0].directory / "artifact/weights.bin").read_bytes(), contents
        )

    def test_huggingface_adapter_uses_the_pinned_revision_and_streams(self):
        model = {
            "repository": "dropbox-dash/model",
            "revision": "a" * 40,
        }
        payload = b"streamed fixture"
        opened = {}

        class FakeOpener:
            def open(self, request, timeout):
                opened["url"] = request.full_url
                opened["timeout"] = timeout
                return io.BytesIO(payload)

        destination = self.root / "download.bin"
        with mock.patch(
            "scripts.model_artifacts.urllib.request.build_opener",
            return_value=FakeOpener(),
        ):
            download_from_huggingface(
                model, "nested/model.bin", destination, len(payload)
            )
        self.assertEqual(
            opened["url"],
            f"https://huggingface.co/dropbox-dash/model/resolve/{'a' * 40}/nested/model.bin",
        )
        self.assertEqual(opened["timeout"], 60)
        self.assertEqual(destination.read_bytes(), payload)

    def test_huggingface_adapter_rejects_data_larger_than_manifest(self):
        model = {"repository": "acme/model", "revision": "a" * 40}

        class FakeOpener:
            def open(self, _request, timeout):
                return io.BytesIO(b"larger than expected")

        destination = self.root / "oversized.bin"
        with mock.patch(
            "scripts.model_artifacts.urllib.request.build_opener",
            return_value=FakeOpener(),
        ):
            with self.assertRaises(ModelProvisionError):
                download_from_huggingface(model, "weights.bin", destination, 2)
        self.assertEqual(destination.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
