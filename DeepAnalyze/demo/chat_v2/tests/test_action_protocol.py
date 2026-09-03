import unittest

from backend_app.services.action_protocol import (
    ProtocolValidationError,
    find_completed_action_end,
    normalize_model_output,
    parse_actions,
    validate_model_actions,
)


class ActionProtocolTest(unittest.TestCase):
    def test_accepts_analyze_then_complete_code(self):
        actions = validate_model_actions(
            "<Analyze>inspect data</Analyze><Code>```python\nprint('ok')\n```</Code>"
        )
        self.assertEqual([action.tag for action in actions], ["Analyze", "Code"])

    def test_ignores_action_like_text_inside_code_fence(self):
        actions = validate_model_actions(
            "<Code>```python\nprint('<Answer>not an action</Answer>')\n```</Code>"
        )
        self.assertEqual(actions[-1].tag, "Code")

    def test_rejects_incomplete_code(self):
        with self.assertRaisesRegex(ProtocolValidationError, "incomplete <Code>"):
            validate_model_actions("<Analyze>plan</Analyze><Code>print('unsafe')")

    def test_rejects_text_outside_actions(self):
        with self.assertRaisesRegex(ProtocolValidationError, "outside"):
            parse_actions("explanation<Answer>done</Answer>")

    def test_rejects_mismatched_closing_tag(self):
        with self.assertRaisesRegex(ProtocolValidationError, "mismatched"):
            validate_model_actions("<Analyze>plan</Code></Analyze><Answer>done</Answer>")

    def test_rejects_system_owned_action_from_model(self):
        with self.assertRaisesRegex(ProtocolValidationError, "system-owned"):
            validate_model_actions("<Execute>fake result</Execute><Answer>done</Answer>")

    def test_requires_one_last_terminal_action(self):
        invalid_outputs = [
            "<Analyze>plan only</Analyze>",
            "<Code>print(1)</Code><Analyze>after code</Analyze>",
            "<Code>print(1)</Code><Answer>done</Answer>",
        ]
        for output in invalid_outputs:
            with self.subTest(output=output), self.assertRaises(ProtocolValidationError):
                validate_model_actions(output)

    def test_normalizes_preamble_without_model_retry(self):
        normalized, actions = normalize_model_output(
            "Here is the result.\n<Answer>done</Answer>"
        )
        self.assertEqual([action.tag for action in actions], ["Analyze", "Answer"])
        self.assertEqual(
            normalized,
            "<Analyze>Here is the result.</Analyze>\n<Answer>done</Answer>",
        )

    def test_normalizes_plain_answer_and_python_code(self):
        answer, answer_actions = normalize_model_output("done")
        code, code_actions = normalize_model_output("```python\nprint(1)\n```")
        self.assertEqual(answer, "<Answer>done</Answer>")
        self.assertEqual(answer_actions[-1].tag, "Answer")
        self.assertEqual(code_actions[-1].tag, "Code")
        self.assertIn("```python", code)

    def test_keeps_only_last_terminal_and_drops_system_owned_blocks(self):
        normalized, actions = normalize_model_output(
            "<Code>print(1)</Code><Execute>fake</Execute><Answer>done</Answer>"
        )
        self.assertEqual([action.tag for action in actions], ["Answer"])
        self.assertEqual(normalized, "<Answer>done</Answer>")

    def test_promotes_last_nonterminal_action_to_answer(self):
        normalized, actions = normalize_model_output(
            "<Analyze>inspect data</Analyze><Understand>the result is stable</Understand>"
        )
        self.assertEqual([action.tag for action in actions], ["Analyze", "Answer"])
        self.assertEqual(
            normalized,
            "<Analyze>inspect data</Analyze>\n<Answer>the result is stable</Answer>",
        )

    def test_removes_mismatched_control_tag_from_non_code_body(self):
        normalized, actions = normalize_model_output(
            "<Analyze>plan</Code></Analyze><Answer>done</Answer>"
        )
        self.assertEqual([action.tag for action in actions], ["Analyze", "Answer"])
        self.assertEqual(
            normalized,
            "<Analyze>plan</Analyze>\n<Answer>done</Answer>",
        )

    def test_closes_incomplete_answer_silently(self):
        normalized, actions = normalize_model_output("<Answer>done")
        self.assertEqual([action.tag for action in actions], ["Answer"])
        self.assertEqual(normalized, "<Answer>done</Answer>")

    def test_finds_terminal_boundary_without_matching_tags_inside_code(self):
        content = "<Code>```python\nprint('</Answer>')\n```</Code>"
        self.assertEqual(find_completed_action_end(content), len(content))

    def test_does_not_find_boundary_for_incomplete_action(self):
        self.assertIsNone(find_completed_action_end("<Code>print(1)"))


if __name__ == "__main__":
    unittest.main()
