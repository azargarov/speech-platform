from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts.inspect_storage_preflight import MODEL_MANIFEST_SHA256, inspect_storage


class StoragePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.targets = {
            "speech_platform": self.root / "srv/speech-platform",
            "models": self.root / "srv/speech-platform/models",
            "deployment_state": self.root / "srv/speech-platform/deployment-state",
            "model_store": self.root / "var/tmp/model-store",
        }
        for path in self.targets.values():
            path.mkdir(parents=True, exist_ok=True)
        mountinfo = self.root / "mountinfo"
        mountinfo.write_text(
            "42 1 253:0 / / rw,relatime - ext4 /dev/test rw\n",
            encoding="utf-8",
        )
        self.mountinfo = mountinfo
        self.digest_dir = self.targets["model_store"] / MODEL_MANIFEST_SHA256
        (self.digest_dir / "artifact").mkdir(parents=True)
        (self.digest_dir / "manifest.yaml").write_text(
            "synthetic manifest fixture\n", encoding="utf-8"
        )
        self.expected_files = [
            {"path": "model.bin", "size_bytes": 7, "sha256": "a" * 64},
            {"path": "tokenizer.json", "size_bytes": 9, "sha256": "b" * 64},
        ]
        self.manifest = {
            "model": {"revision": "test-revision"},
            "artifact": {"format": "test-format"},
            "files": self.expected_files,
        }
        self.verifier = Mock(return_value=object())
        self.manifest_loader = Mock(return_value=self.manifest)

    def inspect(self):
        return inspect_storage(
            targets=self.targets,
            mountinfo_path=self.mountinfo,
            model_verifier=self.verifier,
            manifest_loader=self.manifest_loader,
        )

    def test_reports_mount_owner_mode_capacity_and_bounded_structure(self):
        state = self.targets["deployment_state"]
        (state / "locks").mkdir()
        nested = state / "private" / "deep"
        nested.mkdir(parents=True)
        (nested / "should-not-be-listed").write_text("private", encoding="utf-8")
        report = self.inspect()

        model_root = report["locations"]["models"]
        self.assertEqual(model_root["filesystem"]["filesystem"], "ext4")
        self.assertEqual(model_root["filesystem"]["source"], "/dev/test")
        self.assertEqual(model_root["capacity"]["status"], "available")
        self.assertEqual(model_root["target"]["kind"], "directory")
        state_paths = {
            item.get("relative_path")
            for item in report["locations"]["deployment_state"]["structure"]["entries"]
        }
        self.assertEqual(state_paths, {"locks", "private"})
        self.assertNotIn("should-not-be-listed", str(report))
        self.assertFalse(report["safety_limits"]["deployment_state_recursion"])

    def test_model_manifest_and_payload_expectations_are_reported(self):
        report = self.inspect()
        evidence = report["model_artifact_evidence"]
        self.assertEqual(evidence["status"], "available")
        self.assertTrue(evidence["manifest"]["readable"])
        self.assertEqual(
            evidence["manifest"]["expected_identity_sha256"],
            MODEL_MANIFEST_SHA256,
        )
        self.assertEqual(
            {item["path"] for item in evidence["payloads"]},
            {item["path"] for item in self.expected_files},
        )
        self.assertTrue(
            all(item["readable_and_verified"] for item in evidence["payloads"])
        )
        self.verifier.assert_called_once()
        self.manifest_loader.assert_called_once_with(
            self.digest_dir / "manifest.yaml", MODEL_MANIFEST_SHA256
        )

    def test_model_failure_is_safe_and_never_includes_exception_text(self):
        self.verifier.side_effect = PermissionError("private-content-must-not-appear")
        report = self.inspect()
        evidence = report["model_artifact_evidence"]
        self.assertEqual(evidence["status"], "verification_failed")
        self.assertNotIn("private-content-must-not-appear", str(report))
        self.assertTrue(
            all(not item["readable_and_verified"] for item in evidence["payloads"])
        )

    def test_symlinked_model_manifest_is_reported_without_opening_target(self):
        manifest = self.digest_dir / "manifest.yaml"
        manifest.unlink()
        outside = self.root / "outside-manifest"
        outside.write_text("private-marker", encoding="utf-8")
        manifest.symlink_to(outside)
        report = self.inspect()
        self.assertEqual(
            report["model_artifact_evidence"]["status"], "verification_failed"
        )
        self.manifest_loader.assert_not_called()
        self.verifier.assert_not_called()
        self.assertNotIn("private-marker", str(report))

    def test_tree_marks_symlinks_and_unexpected_hard_links_without_following(self):
        models = self.targets["models"]
        (models / "real").mkdir()
        source = models / "real/file.bin"
        source.write_bytes(b"fixture")
        (models / "real/alias.bin").hardlink_to(source)
        (models / "link").symlink_to(models / "real", target_is_directory=True)
        report = self.inspect()
        entries = report["locations"]["models"]["structure"]["entries"]
        by_path = {item["relative_path"]: item for item in entries}
        self.assertEqual(by_path["link"]["kind"], "symlink")
        self.assertTrue(by_path["real/file.bin"]["unexpected_hard_link"])
        self.assertTrue(by_path["real/alias.bin"]["unexpected_hard_link"])
        self.assertNotIn("link/file.bin", by_path)

    def test_target_roles_cannot_be_expanded(self):
        with self.assertRaisesRegex(ValueError, "target roles are fixed"):
            inspect_storage(
                targets={**self.targets, "unrelated": self.root / "other"},
                mountinfo_path=self.mountinfo,
            )

    def test_symlinked_ancestor_is_reported_without_traversal(self):
        actual = self.root / "actual"
        actual.mkdir()
        (actual / "private-marker").write_text("do-not-read", encoding="utf-8")
        alias = self.root / "alias"
        alias.symlink_to(actual, target_is_directory=True)
        targets = {
            role: alias / path.relative_to(self.root)
            for role, path in self.targets.items()
        }
        verifier = Mock()
        report = inspect_storage(
            targets=targets,
            mountinfo_path=self.mountinfo,
            model_verifier=verifier,
            manifest_loader=self.manifest_loader,
        )
        self.assertEqual(
            report["locations"]["models"]["structure"]["status"],
            "not_inspected_unsafe_or_inaccessible_ancestry",
        )
        self.assertEqual(
            report["model_artifact_evidence"]["status"],
            "unsafe_or_inaccessible_ancestry",
        )
        self.assertNotIn("do-not-read", str(report))
        verifier.assert_not_called()

    def test_inspection_does_not_modify_fixture_files(self):
        marker = self.targets["deployment_state"] / "sentinel"
        marker.write_bytes(b"unchanged")
        before = marker.stat()
        self.inspect()
        after = marker.stat()
        self.assertEqual(marker.read_bytes(), b"unchanged")
        self.assertEqual(
            (before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns)
        )


if __name__ == "__main__":
    unittest.main()
