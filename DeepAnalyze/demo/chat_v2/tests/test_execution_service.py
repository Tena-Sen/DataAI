import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend_app.services import execution_service, session_state, workspace


class ManagedExecutionServiceTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        safe_settings = replace(workspace.settings, workspace_base_dir=self.temp_dir.name)
        self.workspace_patch = patch.object(workspace, "settings", safe_settings)
        self.workspace_patch.start()
        self.addCleanup(self.workspace_patch.stop)

    def test_records_script_diff_output_and_artifacts(self):
        def fake_execute(_code, workspace_dir, *_args, **_kwargs):
            Path(workspace_dir, "result.csv").write_text("value\n1\n", encoding="utf-8")
            return "completed"

        with patch.object(
            execution_service,
            "execute_code_safe",
            side_effect=fake_execute,
        ):
            outcome = execution_service.execute_managed_code(
                "print('new')",
                "session-run",
                source="manual",
                instruction="change the output",
                original_code="print('old')",
            )

        self.assertTrue(outcome.success)
        self.assertIn("before.py", outcome.diff)
        self.assertIn("<Code>", outcome.trace_content)
        self.assertIn("<Execute>", outcome.trace_content)
        self.assertRegex(outcome.trace_content, r"result\.csv[^)]*v=\\d+")
        artifact_paths = {str(item["path"]) for item in outcome.artifacts}
        self.assertTrue(any(path.endswith("result.csv") for path in artifact_paths))
        self.assertTrue(any(path.startswith("generated/code/") for path in artifact_paths))

        state = session_state.load_session_state("session-run")
        self.assertEqual(len(state["executions"]), 1)
        self.assertEqual(state["executions"][0]["instruction"], "change the output")
        generated_index = workspace.load_generated_index("session-run")
        self.assertTrue(any(path.startswith("generated/code/") for path in generated_index))


if __name__ == "__main__":
    unittest.main()
