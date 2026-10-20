"""Synthetic Git and filesystem fixtures for tracked source trust checks."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.tracked_source_integrity import (
    TRACKED_SOURCE_PATHS,
    TrackedSourceError,
    validate_tracked_sources,
)


class TrackedSourceIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir(mode=0o755)
        self.paths = {}
        for role, relative in TRACKED_SOURCE_PATHS.items():
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("approved " + role + "\n", encoding="utf-8")
            path.chmod(0o664)
            self.paths[role] = path
        (self.repo / "releases").chmod(0o775)
        self._git("init", "-q")
        self._git("config", "user.email", "fixture@example.invalid")
        self._git("config", "user.name", "Fixture")
        self._git(
            "add", *[str(path.relative_to(self.repo)) for path in self.paths.values()]
        )
        self._git("commit", "-qm", "approved inputs")
        self.revision = self._git("rev-parse", "HEAD").stdout.decode().strip()

    def tearDown(self):
        self.temp.cleanup()

    def _git(self, *args):
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )

    def _runner(self, other_member=False, mutate_role=None):
        def run(command, *, cwd, input=None):
            if command[0] == "getent":
                uid = os.getuid()
                gid = os.stat(self.repo / "releases").st_gid
                if command[1] == "passwd":
                    text = f"root:x:0:0:root:/root:/bin/sh\noperator:x:{uid}:{gid}:operator:/home/operator:/bin/sh\n"
                    if other_member:
                        text += f"intruder:x:{uid + 1}:{gid}:intruder:/home/intruder:/bin/sh\n"
                else:
                    requested_gid = int(command[2])
                    members = "operator,intruder" if other_member else "operator"
                    if requested_gid == 0:
                        members = "root"
                    text = f"fixture:x:{requested_gid}:{members}\n"
                return subprocess.CompletedProcess(command, 0, text, "")
            result = subprocess.run(
                command,
                cwd=cwd,
                input=input,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if mutate_role and command[1:3] == ["cat-file", "blob"]:
                self.paths[mutate_role].write_text("raced content\n", encoding="utf-8")
            return result

        return run

    def _validate(self, *, runner=None, revision=None, captured=None):
        return validate_tracked_sources(
            self.paths,
            captured,
            approved_revision=self.revision if revision is None else revision,
            repository_root=self.repo,
            runner=runner or self._runner(),
        )

    def test_group_writable_sources_are_eligible_with_verified_single_operator_group(
        self,
    ):
        identities = self._validate()
        self.assertEqual(set(identities), set(TRACKED_SOURCE_PATHS))

    def test_changed_git_content_is_rejected(self):
        self.paths["compose.yaml"].write_text("modified\n", encoding="utf-8")
        with self.assertRaisesRegex(
            TrackedSourceError, "staged or working changes|differ"
        ):
            self._validate()

    def test_staged_git_content_is_rejected(self):
        self.paths["release.yaml"].write_text("staged change\n", encoding="utf-8")
        self._git("add", "releases/voiceservice-v0.1.2.yaml")
        with self.assertRaisesRegex(TrackedSourceError, "staged or working changes"):
            self._validate()

    def test_changed_group_membership_assumption_is_rejected(self):
        with self.assertRaisesRegex(TrackedSourceError, "group membership"):
            self._validate(runner=self._runner(other_member=True))

    def test_source_mutation_during_git_capture_is_rejected(self):
        captured = {role: path.read_bytes() for role, path in self.paths.items()}
        with self.assertRaisesRegex(TrackedSourceError, "bytes differ"):
            self._validate(
                runner=self._runner(mutate_role="compose.yaml"), captured=captured
            )

    def test_unsafe_path_and_hard_link_are_rejected(self):
        path = self.paths["compose.yaml"]
        replacement = self.repo / "replacement"
        path.rename(replacement)
        path.symlink_to(replacement)
        with self.assertRaises(TrackedSourceError):
            self._validate()
        path.unlink()
        path.hardlink_to(replacement)
        with self.assertRaises(TrackedSourceError):
            self._validate()

    def test_malformed_git_reference_is_rejected(self):
        with self.assertRaisesRegex(TrackedSourceError, "malformed"):
            self._validate(revision="HEAD~1")

    def test_missing_acl_or_group_membership_evidence_fails_closed(self):
        with patch(
            "scripts.tracked_source_integrity.os.listxattr", side_effect=OSError
        ):
            with self.assertRaisesRegex(TrackedSourceError, "ownership, path, ACL"):
                self._validate()

        def missing_group_evidence(command, *, cwd, input=None):
            if command[0] == "getent":
                return subprocess.CompletedProcess(command, 2, b"", b"")
            return self._runner()(command, cwd=cwd, input=input)

        with self.assertRaisesRegex(TrackedSourceError, "membership evidence"):
            self._validate(runner=missing_group_evidence)

    def test_captured_bytes_must_match_git_blob(self):
        captured = {role: path.read_bytes() for role, path in self.paths.items()}
        captured["release.yaml"] += b"tampered"
        with self.assertRaisesRegex(
            TrackedSourceError, "differ from approved Git blob"
        ):
            self._validate(captured=captured)


if __name__ == "__main__":
    unittest.main()
