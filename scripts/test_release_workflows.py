"""Release safety policies without GitHub, credentials, GPUs or private weights."""

import re
import unittest
from pathlib import Path

import yaml


class WorkflowPolicyTests(unittest.TestCase):
    def test_actions_pinned_and_permissions_scoped(self):
        for path in Path(".github/workflows").glob("*.yaml"):
            doc = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
            self.assertEqual(doc["permissions"], {"contents": "read"})
            for job in doc["jobs"].values():
                self.assertEqual(job["runs-on"], "ubuntu-24.04")
                for step in job.get("steps", []):
                    if "uses" in step:
                        self.assertRegex(step["uses"], r"^[\w./-]+@[0-9a-f]{40}$")
                        if step["uses"].startswith("gitleaks/"):
                            self.assertEqual(
                                step["env"]["GITLEAKS_ENABLE_COMMENTS"], "false"
                            )
                            self.assertEqual(
                                step["env"]["GITLEAKS_ENABLE_UPLOAD_ARTIFACT"], "false"
                            )
                if "permissions" in job:
                    self.assertEqual(
                        job["permissions"], {"contents": "read", "packages": "write"}
                    )

    def test_verify_builds_worker_variants_on_independent_gpu_free_runners(self):
        doc = yaml.load(
            Path(".github/workflows/verify.yaml").read_text(), Loader=yaml.BaseLoader
        )
        builds = doc["jobs"]["images"]["strategy"]["matrix"]["include"]
        self.assertEqual(
            {(x["service"], x["variant"]) for x in builds},
            {("gateway", "cpu"), ("stt", "cpu"), ("stt", "cuda"), ("tts", "cuda")},
        )
        self.assertIn("secrets", doc["jobs"])
        self.assertTrue(
            any(
                s.get("run") == "make verify"
                for s in doc["jobs"]["foundation"]["steps"]
            )
        )

    def test_release_requires_verification_and_separate_immutable_metadata(self):
        doc = yaml.load(
            Path(".github/workflows/release.yaml").read_text(), Loader=yaml.BaseLoader
        )
        publish = doc["jobs"]["publish"]
        self.assertEqual(set(publish["needs"]), {"verify", "images"})
        self.assertEqual(
            doc["jobs"]["images"]["strategy"]["matrix"]["service"],
            ["gateway", "stt", "tts"],
        )
        self.assertEqual(
            publish["strategy"]["matrix"]["service"], ["gateway", "stt", "tts"]
        )
        steps = publish["steps"]
        uploads = [
            s for s in steps if re.match(r"actions/upload-artifact@", s.get("uses", ""))
        ]
        self.assertEqual(len(uploads), 1)
        self.assertIn("matrix.service", uploads[0]["with"]["name"])
        self.assertEqual(uploads[0]["with"]["if-no-files-found"], "error")
