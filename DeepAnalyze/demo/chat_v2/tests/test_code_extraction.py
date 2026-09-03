import unittest

from backend_app.services.chat import _extract_code_to_execute
from backend_app.services.execution_service import _truncate_output


class CodeExtractionTest(unittest.TestCase):
    def test_extracts_common_fence_languages(self):
        for language in ("python", "py", "Python"):
            with self.subTest(language=language):
                content = f"```{language}\nprint('hi')\n```"
                self.assertEqual(_extract_code_to_execute(content), "print('hi')")

    def test_extracts_bare_fence(self):
        self.assertEqual(
            _extract_code_to_execute("```\nprint('hi')\n```"),
            "print('hi')",
        )

    def test_accepts_unfenced_code(self):
        self.assertEqual(_extract_code_to_execute("print('hi')"), "print('hi')")

    def test_prepends_matplotlib_bootstrap(self):
        content = "```python\nimport matplotlib.pyplot as plt\nplt.plot([1])\n```"
        extracted = _extract_code_to_execute(content)
        self.assertIsNotNone(extracted)
        self.assertIn("SimHei", extracted or "")
        self.assertIn("plt.plot([1])", extracted or "")


class OutputTruncationTest(unittest.TestCase):
    def test_short_output_passes_through(self):
        self.assertEqual(_truncate_output("abc", 100), "abc")

    def test_long_output_is_bounded(self):
        truncated = _truncate_output("x" * 100_000, 1024)
        self.assertLess(len(truncated), 2048)
        self.assertIn("output truncated", truncated)

    def test_error_marker_is_preserved(self):
        text = "[Error]: boom\n" + "y" * 100_000
        self.assertTrue(_truncate_output(text, 2048).startswith("[Error]"))


if __name__ == "__main__":
    unittest.main()
