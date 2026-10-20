"""Deterministic offline tests for deployment-state records and crash inspection."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.deployment_state import StateError, StateStore, record_digest


def generation(generation_id="g0", parent=None):
    record = {
        "schema_version": 1,
        "generation_id": generation_id,
        "created_at": "2026-10-20T00:00:00Z",
        "project_name": "voice-test",
        "parent_generation_id": parent,
        "operation_id": "op1",
        "services": {
            "gateway": {
                "release_id": "v0.1.2",
                "release_descriptor_sha256": "a" * 64,
                "image_reference": "example.invalid/gateway@sha256:" + "b" * 64,
                "image_manifest_sha256": "b" * 64,
                "platform": "linux/amd64",
                "runtime_variant": "foundation",
                "configuration_sha256": "c" * 64,
                "model_identities": [],
                "compatible": True,
                "runtime_identity_sha256": "d" * 64,
                "health_status": "HEALTHY",
                "health_evidence_sha256": "e" * 64,
            }
        },
    }
    record["sha256"] = record_digest(record)
    return record


def revision(number=1, outcome=None):
    return {
        "schema_version": 1,
        "operation_id": "op1",
        "operation_type": "UPDATE",
        "created_at": "2026-10-20T00:00:00Z",
        "state": outcome or "PLANNED",
        "outcome": outcome,
        "metadata": {},
        "rollback_eligibility": None,
        "revision": number,
        "previous_revision_sha256": None,
        "sha256": "0" * 64,
    }


class DeploymentStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "state"
        self.store = StateStore.initialize(
            self.root, "voice-test", filesystem_type=lambda _path: "ext4"
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_generation_rejects_unknown_field_and_bad_digest(self):
        record = generation()
        record["unexpected"] = True
        with self.assertRaises(StateError):
            self.store.put_generation(record)
        record = generation()
        record["services"]["gateway"]["secret_token"] = "private"
        with self.assertRaises(StateError):
            self.store.put_generation(record)
        record = generation()
        record["schema_version"] = 99
        with self.assertRaises(StateError):
            self.store.put_generation(record)

    def test_unhashable_schema_values_fail_closed_without_type_error(self):
        malformed_generation = generation()
        malformed_generation["services"]["gateway"]["health_status"] = []
        malformed_generation["sha256"] = record_digest(malformed_generation)
        with self.assertRaises(StateError):
            self.store.put_generation(malformed_generation)

        malformed_operation = revision()
        malformed_operation["rollback_eligibility"] = []
        with self.assertRaises(StateError):
            self.store.put_operation_revision(malformed_operation)

        malformed_generation["services"]["gateway"]["health_status"] = []
        path = self.store.generations / "g0.json"
        path.write_text(
            json.dumps(malformed_generation, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        path.chmod(0o600)
        self.assertEqual(self.store.inspect()["status"], "STATE_INCONSISTENT")

    def test_path_traversal_and_symlink_rejected(self):
        with self.assertRaises(StateError):
            StateStore.initialize(self.root, "../escape")
        link = Path(self.temp.name) / "link"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(StateError):
            StateStore(link, "voice-test", filesystem_type=lambda _path: "ext4")

    def test_unsupported_filesystem_fails_closed(self):
        with self.assertRaises(StateError):
            StateStore(self.root, "voice-test", filesystem_type=lambda _path: "nfs")

    def test_owner_and_permissions_checked(self):
        with self.assertRaises(StateError):
            StateStore(self.root, "voice-test", expected_uid=os.getuid() + 1)
        os.chmod(self.store.project, 0o755)
        with self.assertRaises(StateError):
            StateStore(self.root, "voice-test")

    def test_duplicate_generation_and_duplicate_revision_rejected(self):
        self.store.put_generation(generation())
        with self.assertRaises(StateError):
            self.store.put_generation(generation())
        self.store.put_operation_revision(revision())
        with self.assertRaises(StateError):
            self.store.put_operation_revision(revision())

    def test_canonical_record_and_corruption_detection(self):
        self.store.put_generation(generation())
        path = self.store.generations / "g0.json"
        path.write_text("{", encoding="utf-8")
        self.assertEqual(self.store.inspect()["status"], "STATE_INCONSISTENT")
        altered = generation()
        altered["created_at"] = "2026-10-21T00:00:00Z"
        path.write_bytes(
            json.dumps(altered, sort_keys=True, separators=(",", ":")).encode()
        )
        self.assertIn("checksum", " ".join(self.store.inspect()["issues"]))

    def test_interrupted_temp_write_is_ignored_without_repair(self):
        program = (
            "from scripts.deployment_state import StateStore; "
            f"store=StateStore({str(self.root)!r}, 'voice-test', "
            "before_publish=lambda _tmp,_target: __import__('os')._exit(73)); "
            f"store.put_generation({generation()!r})"
        )
        result = subprocess.run([sys.executable, "-c", program], check=False)
        self.assertEqual(result.returncode, 73)
        self.assertEqual(self.store.inspect()["status"], "STATE_INCONSISTENT")
        self.assertTrue(any(self.store.generations.glob(".pending-*")))

    def test_fsync_failure_leaves_no_committed_record(self):
        def fail_fsync(_fd):
            raise OSError("injected fsync failure")

        failing = StateStore(
            self.root,
            "voice-test",
            fsync=fail_fsync,
            filesystem_type=lambda _path: "ext4",
        )
        with self.assertRaises(StateError):
            failing.put_generation(generation())
        self.assertFalse((self.store.generations / "g0.json").exists())

    def test_directory_fsync_failure_reports_uncertain_published_record(self):
        calls = 0

        def fail_directory_fsync(_fd):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected parent-directory fsync failure")
            os.fsync(_fd)

        failing = StateStore(
            self.root,
            "voice-test",
            fsync=fail_directory_fsync,
            filesystem_type=lambda _path: "ext4",
        )
        with self.assertRaises(StateError):
            failing.put_generation(generation())
        self.assertTrue((self.store.generations / "g0.json").exists())

    def test_missing_revision_and_broken_hash_chain_are_reported(self):
        self.store.put_operation_revision(revision())
        second = revision(2)
        second["state"] = "READY"
        self.store.put_operation_revision(second)
        first_path = self.store.operations / "op1" / "r1.json"
        first = json.loads(first_path.read_text())
        first["state"] = "READY"
        first["sha256"] = record_digest(first)
        first_path.write_bytes(
            json.dumps(first, sort_keys=True, separators=(",", ":")).encode()
        )
        self.assertEqual(self.store.inspect()["status"], "STATE_INCONSISTENT")
        (self.store.operations / "op1" / "r1.json").unlink()
        self.assertIn("sequence", " ".join(self.store.inspect()["issues"]))

    def test_terminal_revision_is_immutable(self):
        for number, state in (
            (1, "PLANNED"),
            (2, "READY"),
            (3, "APPLYING"),
            (4, "VERIFYING"),
        ):
            entry = revision(number)
            entry["state"] = state
            self.store.put_operation_revision(entry)
        terminal = revision(5, outcome="SUCCEEDED")
        terminal["state"] = "SUCCEEDED"
        self.store.put_operation_revision(terminal)
        with self.assertRaises(StateError):
            self.store.put_operation_revision(revision(6))

    def test_inspection_reports_empty_operation_and_contradictory_terminals(self):
        empty = self.store.operations / "empty-op"
        empty.mkdir(mode=0o700)
        self.store.put_operation_revision(revision())
        ready = revision(2)
        ready["state"] = "READY"
        self.store.put_operation_revision(ready)
        rejected = revision(3, outcome="REJECTED")
        rejected["state"] = "REJECTED"
        self.store.put_operation_revision(rejected)
        first_path = self.store.operations / "op1" / "r1.json"
        contradictory = revision(4, outcome="SUCCEEDED")
        contradictory["state"] = "SUCCEEDED"
        contradictory["previous_revision_sha256"] = json.loads(
            (first_path.parent / "r3.json").read_text()
        )["sha256"]
        contradictory["sha256"] = record_digest(contradictory)
        second_path = first_path.parent / "r4.json"
        second_path.write_bytes(
            json.dumps(contradictory, sort_keys=True, separators=(",", ":")).encode()
        )
        second_path.chmod(0o600)
        issues = " ".join(self.store.inspect()["issues"])
        self.assertIn("no committed revisions", issues)
        self.assertIn("terminal operation revision was extended", issues)
        self.assertIn("illegal operation state transition", issues)

    def test_pointer_requires_matching_generation(self):
        self.store.put_operation_revision(revision())
        for number, state in ((2, "READY"), (3, "APPLYING"), (4, "VERIFYING")):
            entry = revision(number)
            entry["state"] = state
            self.store.put_operation_revision(entry)
        self.store.put_generation(generation())
        self.store.set_installed_generation("g0")
        self.assertEqual(self.store.inspect()["installed_generation_id"], "g0")
        pointer = self.store.project / "installed.json"
        value = json.loads(pointer.read_text())
        value["sha256"] = "0" * 64
        pointer.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
        self.assertEqual(self.store.inspect()["status"], "STATE_INCONSISTENT")
        with self.assertRaises(StateError):
            self.store.set_installed_generation("g0")

    def test_operation_identity_metadata_and_state_machine_are_immutable(self):
        self.store.put_operation_revision(revision())
        for field, value in (
            ("operation_type", "ROLLBACK"),
            ("created_at", "2026-10-21T00:00:00Z"),
            ("metadata", {"actor": "changed"}),
        ):
            changed = revision(2)
            changed["state"] = "READY"
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(StateError):
                self.store.put_operation_revision(changed)
        illegal = revision(2)
        illegal["state"] = "APPLYING"
        with self.assertRaises(StateError):
            self.store.put_operation_revision(illegal)

    def test_nonterminal_state_outcome_mismatch_and_type_specific_state_rejected(self):
        entry = revision()
        entry["outcome"] = "SUCCEEDED"
        entry["state"] = "READY"
        with self.assertRaises(StateError):
            self.store.put_operation_revision(entry)
        entry = revision()
        entry["operation_type"] = "ROLLBACK"
        entry["state"] = "APPLYING"
        with self.assertRaises(StateError):
            self.store.put_operation_revision(entry)

    def test_promotion_accepts_verifying_crash_window_but_rejects_incomplete_operation(
        self,
    ):
        self.store.put_operation_revision(revision())
        self.store.put_generation(generation())
        with self.assertRaisesRegex(StateError, "verified promotion state"):
            self.store.set_installed_generation("g0")
        self.assertFalse((self.store.project / "installed.json").exists())
        ready = revision(2)
        ready["state"] = "READY"
        self.store.put_operation_revision(ready)
        applying = revision(3)
        applying["state"] = "APPLYING"
        self.store.put_operation_revision(applying)
        verifying = revision(4)
        verifying["state"] = "VERIFYING"
        self.store.put_operation_revision(verifying)
        self.store.set_installed_generation("g0")
        self.assertEqual(self.store.inspect()["installed_generation_id"], "g0")

    def test_generation_without_producer_operation_is_orphan_and_not_promotable(self):
        record = generation()
        record["operation_id"] = "missing-op"
        record["sha256"] = record_digest(record)
        self.store.put_generation(record)
        self.assertEqual(self.store.inspect()["status"], "STATE_INCONSISTENT")
        with self.assertRaisesRegex(StateError, "no operation evidence"):
            self.store.set_installed_generation("g0")

    def test_generation_parent_must_match_current_pointer(self):
        self.store.put_operation_revision(revision())
        for number, state in ((2, "READY"), (3, "APPLYING"), (4, "VERIFYING")):
            entry = revision(number)
            entry["state"] = state
            self.store.put_operation_revision(entry)
        self.store.put_generation(generation())
        self.store.set_installed_generation("g0")
        child = generation("g1", parent="wrong-parent")
        child["sha256"] = record_digest(child)
        self.store.put_generation(child)
        with self.assertRaisesRegex(StateError, "parent does not match"):
            self.store.set_installed_generation("g1")

    def test_malformed_operation_directory_and_revision_filename_are_reported(self):
        bad_dir = self.store.operations / "bad id"
        bad_dir.mkdir(mode=0o700)
        self.store.put_operation_revision(revision())
        path = self.store.operations / "op1" / "notes.txt"
        path.write_text("ignored?", encoding="utf-8")
        path.chmod(0o600)
        report = self.store.inspect()
        self.assertEqual(report["status"], "STATE_INCONSISTENT")
        issues = " ".join(report["issues"])
        self.assertIn("invalid operation id", issues)
        self.assertIn("unsupported type or filename", issues)

    def test_corrupt_pointer_types_and_unknown_fields_are_reported(self):
        pointer = self.store.project / "installed.json"
        pointer.write_text(
            '{"generation_id":[],"schema_version":true,"sha256":7}', encoding="utf-8"
        )
        pointer.chmod(0o600)
        report = self.store.inspect()
        self.assertEqual(report["status"], "STATE_INCONSISTENT")
        pointer.write_text(
            '{"extra":1,"generation_id":"g0","schema_version":1,"sha256":"'
            + "0" * 64
            + '"}',
            encoding="utf-8",
        )
        self.assertEqual(self.store.inspect()["status"], "STATE_INCONSISTENT")

    def test_hard_link_record_is_rejected(self):
        self.store.put_operation_revision(revision())
        source = self.store.operations / "op1" / "r1.json"
        os.link(source, self.store.operations / "op1" / "r1-copy.json")
        self.assertEqual(self.store.inspect()["status"], "STATE_INCONSISTENT")

    def test_outcome_and_rollback_eligibility_are_separate(self):
        entry = revision(outcome="FAILED")
        entry["rollback_eligibility"] = "ROLLBACK_READY"
        entry["sha256"] = record_digest(entry)
        self.assertEqual(entry["outcome"], "FAILED")
        self.assertEqual(entry["rollback_eligibility"], "ROLLBACK_READY")


if __name__ == "__main__":
    unittest.main()
