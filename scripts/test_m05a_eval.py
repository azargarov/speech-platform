import unittest
import tempfile
from pathlib import Path

from scripts import m05a_eval


class M05AEvalTests(unittest.TestCase):
    def test_repository_corpus_is_valid_and_covers_requested_cases(self):
        cases = m05a_eval.read_cases()
        self.assertEqual(m05a_eval.validate_cases(cases), [])
        self.assertEqual(len(cases), 39)

    def test_input_length_classes_cover_short_medium_and_long(self):
        classes = {
            m05a_eval.input_length_class(case["text"])
            for case in m05a_eval.read_cases()
        }
        self.assertEqual(classes, {"short", "medium", "long"})

    def test_validator_rejects_raw_concise_case(self):
        case = {
            "id": "bad",
            "input_language": "en",
            "text": "Hello",
            "mode": "raw",
            "formatting": "concise",
            "target_language": "en",
            "invariants": ["Hello"],
            "review_constraints": "Preserve text",
        }
        errors = m05a_eval.validate_cases([case])
        self.assertIn("bad: raw mode requires normal formatting", errors)

    def test_prompt_is_loaded_from_versioned_quoted_instruction(self):
        prompt = m05a_eval.system_prompt()
        self.assertIn("Preserve every fact", prompt)
        self.assertIn("Return only the transformed text", prompt)

    def test_prompt_v2_states_preservation_and_language_policy(self):
        prompt = m05a_eval.system_prompt(
            m05a_eval.ROOT / "docs/milestones/M05A/prompts/v2.md"
        )
        self.assertIn("preserve the source language", prompt)
        self.assertIn("Never reverse or remove negation", prompt)
        self.assertIn("Never invent events", prompt)

    def test_unseen_corpus_has_valid_independent_cases(self):
        cases = m05a_eval.read_cases(
            m05a_eval.ROOT / "docs/milestones/M05A/unseen-cases.jsonl"
        )
        self.assertEqual(len(cases), 7)
        self.assertEqual(m05a_eval.validate_cases(cases, False), [])

    def test_invariant_check_reports_missing_lexical_tokens(self):
        self.assertEqual(
            m05a_eval.invariant_flags(
                "Ticket T-88 failed at 09:10", ["T-88", "09:10", "three"]
            ),
            ["three"],
        )

    def test_numeric_invariant_does_not_match_inside_a_larger_number(self):
        self.assertEqual(m05a_eval.invariant_flags("349 items", ["3"]), ["3"])

    def test_docker_memory_parser_handles_binary_units(self):
        self.assertEqual(m05a_eval.parse_memory_bytes("1.5GiB"), int(1.5 * 1024**3))

    def test_cold_request_requires_material_model_load_duration(self):
        self.assertFalse(
            m05a_eval.is_cold_request(
                {"timing": {"ollama_load_duration_ns": 10_000_000}}
            )
        )
        self.assertTrue(
            m05a_eval.is_cold_request(
                {"timing": {"ollama_load_duration_ns": 9_000_000_000}}
            )
        )

    def test_host_memory_summary_uses_available_memory_samples(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "memory.csv"
            path.write_text("t1,1000,600,400\nt2,1000,500,500\n", encoding="utf-8")
            summary = m05a_eval.host_memory_summary(path)
        self.assertEqual(summary["sample_count"], 2)
        self.assertEqual(summary["peak_used_bytes"], 500)
        self.assertEqual(summary["minimum_available_bytes"], 500)

    def test_private_run_directory_guard_is_path_based(self):
        private = Path(m05a_eval.ROOT / "private/m05a/run").resolve()
        unrelated = Path(m05a_eval.ROOT / "docs/milestones/M05A/run").resolve()
        self.assertTrue(
            private.is_relative_to((m05a_eval.ROOT / "private/m05a").resolve())
        )
        self.assertFalse(
            unrelated.is_relative_to((m05a_eval.ROOT / "private/m05a").resolve())
        )


if __name__ == "__main__":
    unittest.main()
