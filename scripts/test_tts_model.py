from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from scripts.model_artifacts import model_directory
from scripts.tts_model import MANIFEST_SHA256, _model
from services.stt.artifacts import canonical_manifest_digest, load_artifact_manifest


class TTSModelArtifactTests(unittest.TestCase):
    def test_manifest_identity_and_hashes(self):
        model = _model()
        manifest = load_artifact_manifest(model["manifest_path"], MANIFEST_SHA256)
        self.assertEqual(MANIFEST_SHA256, canonical_manifest_digest(manifest))
        self.assertEqual(model["family"], "voxcpm2")
        self.assertEqual(model["revision"], "32279effe8c19989596f05d353d1447f51d9e915")
        self.assertEqual(len(manifest["files"]), 7)
        self.assertIn(
            "model.safetensors", {entry["path"] for entry in manifest["files"]}
        )
        self.assertIn("audiovae.pth", {entry["path"] for entry in manifest["files"]})

    def test_manifest_identity_references_match_digest_based_store(self):
        model = _model()
        manifest = load_artifact_manifest(model["manifest_path"], MANIFEST_SHA256)
        self.assertEqual(model["manifest_sha256"], canonical_manifest_digest(manifest))
        self.assertEqual(
            model_directory(Path("/models"), model), Path("/models") / MANIFEST_SHA256
        )
        root = Path(__file__).resolve().parents[1]
        config = yaml.safe_load((root / "configs/tts.yaml").read_text())
        self.assertEqual(config["model_manifest_sha256"], MANIFEST_SHA256)
        env_example = (root / ".env.example").read_text()
        self.assertIn(f"TTS_MODEL_MANIFEST_SHA256={MANIFEST_SHA256}", env_example)


if __name__ == "__main__":
    unittest.main()
