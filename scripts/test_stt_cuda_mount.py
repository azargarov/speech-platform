from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.stt_cuda_mount import (
    ReportMountPreflightError,
    validate_container_report_mount,
    validate_static_report_mount,
)


class ReportMountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.report_dir = self.root / "attempt" / "harness"
        self.report_dir.mkdir(parents=True)
        os.chmod(self.root / "attempt", 0o700)
        os.chown(self.report_dir, -1, os.getgid())
        os.chmod(self.report_dir, 0o2770)
        self.command = [
            "docker",
            "run",
            "--network",
            "none",
            "--read-only",
            "--user",
            "65532:65532",
            "--group-add",
            str(os.getgid()),
            "--mount",
            f"type=bind,src={self.report_dir},dst=/results",
        ]

    def validate(self, path=None, command=None, group=None):
        return validate_static_report_mount(
            path or self.report_dir,
            command or self.command,
            expected_group=os.getgid() if group is None else group,
        )

    def test_valid_static_mount_configuration(self):
        result = self.validate()
        self.assertEqual(result["mode"], "2770")
        self.assertEqual(result["acl"], "none")
        self.assertEqual(result["container_uid"], 65532)
        self.assertEqual(result["supplementary_gids"], [str(os.getgid())])
        self.assertEqual(result["bind_destination"], "/results")

    def test_wrong_group_and_mode_fail_closed(self):
        with self.assertRaisesRegex(ReportMountPreflightError, "group_mismatch"):
            self.validate(group=os.getgid() + 10000)
        os.chmod(self.report_dir, 0o2775)
        with self.assertRaisesRegex(ReportMountPreflightError, "mode_mismatch"):
            self.validate()

    def test_missing_directory_fails_closed(self):
        missing = self.root / "missing"
        with self.assertRaisesRegex(ReportMountPreflightError, "directory_missing"):
            self.validate(path=missing)

    def test_inaccessible_parent_fails_closed(self):
        parent = self.report_dir.parent
        real_access = os.access

        def deny_parent(path, mode, *args, **kwargs):
            if Path(path) == parent and mode == os.X_OK:
                return False
            return real_access(path, mode, *args, **kwargs)

        with patch("scripts.stt_cuda_mount.os.access", side_effect=deny_parent):
            with self.assertRaisesRegex(
                ReportMountPreflightError, "parent_traversal_unavailable"
            ):
                self.validate()

    def test_missing_supplementary_group_and_readonly_report_mount_fail(self):
        bad_group = self.command.copy()
        bad_group[bad_group.index("--group-add") + 1] = str(os.getgid() + 10000)
        with self.assertRaisesRegex(
            ReportMountPreflightError, "supplementary_group_mismatch"
        ):
            self.validate(command=bad_group)
        readonly = self.command.copy()
        readonly[readonly.index("--mount") + 1] += ",readonly"
        with self.assertRaisesRegex(
            ReportMountPreflightError, "bind_configuration_invalid"
        ):
            self.validate(command=readonly)

    def test_acl_presence_fails_closed(self):
        with patch("scripts.stt_cuda_mount._has_acl", return_value=True):
            with self.assertRaisesRegex(ReportMountPreflightError, "acl_present"):
                self.validate()

    def test_container_probe_atomically_writes_replaces_and_retains_report(self):
        path = self.report_dir / "harness-report.json"
        evidence = validate_container_report_mount(path, self.atomic_writer)
        self.assertEqual(evidence["write"], "pass")
        self.assertEqual(evidence["atomic_replace"], "pass")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        self.assertEqual(path.stat().st_uid, os.geteuid())
        self.assertEqual(path.stat().st_gid, os.getgid())
        self.assertEqual(list(self.report_dir.glob(".stt-diagnostic-*")), [])

    @staticmethod
    def atomic_writer(path, value):
        from scripts.stt_cuda_diagnostic import atomic_write_report

        atomic_write_report(path, value)

    def test_container_write_failure_is_safely_classified(self):
        def fail_write(_path, _value):
            raise PermissionError("private absolute path must not escape")

        with self.assertRaisesRegex(ReportMountPreflightError, "write_failed"):
            validate_container_report_mount(
                self.report_dir / "blocked.json", fail_write
            )


if __name__ == "__main__":
    unittest.main()
