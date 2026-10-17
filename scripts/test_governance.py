"""Regression checks for governance validator failure detection."""

import tempfile
import unittest
from pathlib import Path

from validate_governance import SECTIONS, validate_links, validate_skill


class GovernanceValidation(unittest.TestCase):
    def test_valid_and_invalid_skill_inputs(self):
        valid = (
            "---\nname: example\ndescription: Validate example changes.\n---\n\n"
            + "\n".join(
                f"## {section}\n\nInstructions for {section}.\n" for section in SECTIONS
            )
        )
        cases = {
            "valid": valid,
            "bad_yaml": valid.replace("name: example", "name: ["),
            "wrong_name": valid.replace("name: example", "name: other"),
            "missing_description": valid.replace(
                "description: Validate example changes.\n", ""
            ),
            "duplicate": valid.replace("name: example", "name: example\nname: example"),
            "empty_section": valid.replace("Instructions for Workflow.", ""),
            "placeholder": valid + "\n[TODO: finish]\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "example"
            folder.mkdir()
            self.assertTrue(validate_skill(folder))
            for name, content in cases.items():
                with self.subTest(name=name):
                    (folder / "SKILL.md").write_text(content)
                    self.assertEqual(not validate_skill(folder), name == "valid")

    def test_broken_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "doc.md"
            path.write_text("[missing](absent.md)")
            self.assertTrue(validate_links(path))
            (path.parent / "absent.md").write_text("present")
            self.assertFalse(validate_links(path))


if __name__ == "__main__":
    unittest.main()
