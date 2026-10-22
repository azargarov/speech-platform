import re
import unittest

from scripts import m05a_html_report as report


class M05AHtmlReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = report.load_report_data()

    def test_all_46_cases_have_aligned_original_and_three_outputs(self):
        self.assertEqual(len(self.cases), 46)
        self.assertEqual(len({case["id"] for case in self.cases}), 46)
        self.assertEqual(sum(case["corpus"] == "original" for case in self.cases), 39)
        self.assertEqual(sum(case["corpus"] == "unseen" for case in self.cases), 7)
        for case in self.cases:
            self.assertEqual(set(case["models"]), {"local", "groq-qwen", "groq-gpt"})
            for model in case["models"].values():
                self.assertIsInstance(model["response"], str)
            self.assertTrue(case["text"])

    def test_case_input_matches_each_models_transformation_input(self):
        # load_report_data rejects any case ID, corpus, or transformation mismatch.
        target = next(
            case for case in self.cases if case["id"] == "u-translate-identifiers"
        )
        self.assertEqual(target["input_language"], "ru")
        self.assertIn("CACHE_TTL=900", target["text"])
        self.assertIn("ru", target["input_language"])

    def test_utf8_inputs_and_outputs_are_preserved(self):
        russian = next(
            case for case in self.cases if case["id"] == "ru-01-spoken-written"
        )
        swedish = next(
            case for case in self.cases if case["id"] == "sv-01-spoken-written"
        )
        self.assertIn("отчёт", russian["text"])
        self.assertIn("skickade", swedish["text"])
        self.assertIn("отчёт", russian["models"]["groq-gpt"]["response"].lower())

    def test_missing_model_output_is_rendered_as_missing_not_pass(self):
        case = {
            "id": "xss-case",
            "input_language": "en",
            "text": "<img src=x>",
            "mode": "raw",
            "formatting": "normal",
            "target_language": None,
            "review_constraints": "keep <script>",
            "corpus": "original",
            "models": {
                key: {
                    "label": key,
                    "response": None,
                    "latency": None,
                    "finding": {
                        "category": "not individually assessed",
                        "categories": ["not individually assessed"],
                        "text": "Not individually assessed",
                    },
                }
                for key, *_ in report.MODEL_SOURCES
            },
        }
        page = report.build_html([case])
        self.assertIn("No response available", page)
        self.assertIn("Not individually assessed", page)
        self.assertNotIn("<img src=x>", page)
        self.assertIn("&lt;img src=x&gt;", page)
        self.assertIn("keep &lt;script&gt;", page)

    def test_untrusted_output_is_escaped_and_never_embedded_as_script(self):
        case = dict(self.cases[0])
        case["id"] = "safe-case"
        case["text"] = "source"
        case["models"] = {
            key: dict(value) for key, value in self.cases[0]["models"].items()
        }
        case["models"]["local"]["response"] = '</pre><script>alert("x")</script>&'
        page = report.build_html([case])
        self.assertIn(
            "&lt;/pre&gt;&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;&amp;", page
        )
        self.assertNotIn('</pre><script>alert("x")', page)

    def test_filter_groups_and_language_buckets_cover_each_case(self):
        page = report.build_html(self.cases)
        for language in ("English", "Swedish", "Russian", "Mixed-language"):
            self.assertIn(
                f'<details class="language-group" open><summary>{language}', page
            )
        self.assertEqual(len(re.findall(r'<article class="case"', page)), 46)
        for attribute in (
            "data-mode",
            "data-format",
            "data-translation",
            "data-corpus",
            "data-status",
            "data-search",
        ):
            self.assertIn(attribute, page)

    def test_generated_content_does_not_include_credentials_or_artifact_paths(self):
        page = report.build_html(self.cases)
        self.assertNotRegex(
            page,
            re.compile(
                r"(?i)(authorization:\s*bearer|\bgsk_[a-z0-9]{16,}|\bsk-[a-z0-9]{16,})"
            ),
        )
        self.assertNotIn("private/m05a/", page)
        self.assertNotIn("api_key", page.lower())


if __name__ == "__main__":
    unittest.main()
