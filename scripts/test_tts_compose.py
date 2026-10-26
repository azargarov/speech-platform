from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class CanonicalTTSComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = yaml.safe_load((ROOT / "compose.yaml").read_text())

    def test_existing_tts_service_uses_private_inference_worker(self):
        services = self.compose["services"]
        tts = services["tts"]
        self.assertEqual(tts["networks"], ["tts_private"])
        self.assertNotIn("ports", tts)
        self.assertTrue(tts["read_only"])
        self.assertEqual(tts["user"], "65532:65532")
        self.assertEqual(tts["cap_drop"], ["ALL"])
        self.assertEqual(tts["security_opt"], ["no-new-privileges:true"])
        self.assertEqual(
            tts["build"]["dockerfile"], "deployments/compose/worker-tts-cuda.Dockerfile"
        )
        self.assertIn("TTS_MODEL_MANIFEST_SHA256", tts["volumes"][1])
        self.assertIn(
            "TTS_GPU_DEVICE",
            tts["deploy"]["resources"]["reservations"]["devices"][0]["device_ids"][0],
        )
        self.assertIn("tts_private", services["gateway"]["networks"])
        self.assertNotIn("depends_on", services["gateway"])
        self.assertEqual(tts["profiles"], ["tts"])

    def test_stt_gpu_and_model_profile_remain_separate(self):
        stt = self.compose["services"]["stt"]
        self.assertEqual(stt["profiles"], ["stt"])
        self.assertIn(
            "STT_GPU_DEVICE",
            stt["deploy"]["resources"]["reservations"]["devices"][0]["device_ids"][0],
        )
        self.assertIn("MODEL_MANIFEST_SHA256", stt["volumes"][3])
        self.assertEqual(stt["networks"], ["stt_private"])


if __name__ == "__main__":
    unittest.main()
