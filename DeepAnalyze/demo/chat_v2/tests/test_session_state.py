import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from backend_app.services import session_state, workspace


class SessionStateTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        safe_settings = replace(workspace.settings, workspace_base_dir=self.temp_dir.name)
        self.workspace_patch = patch.object(workspace, "settings", safe_settings)
        self.workspace_patch.start()
        self.addCleanup(self.workspace_patch.stop)

    def test_persists_messages_task_and_isolates_sessions(self):
        first_root = workspace.resolve_workspace_root("session-one")
        (first_root / "input.csv").write_text("a\n1\n", encoding="utf-8")
        session_state.replace_messages(
            "session-one",
            [{"role": "user", "content": "analyze", "id": "message-1"}],
        )
        session_state.update_task_config(
            "session-one",
            {
                "instruction": "analyze",
                "selected_files": ["input.csv", "../outside.csv"],
                "provider": "local",
                "model": "DeepAnalyze-8B",
            },
        )

        first = session_state.load_session_state("session-one")
        second = session_state.load_session_state("session-two")
        self.assertEqual(first["messages"][0]["content"], "analyze")
        self.assertEqual(first["task_config"]["selected_files"], ["input.csv"])
        self.assertEqual(second["messages"], [])
        self.assertTrue(
            (first_root.parent / ".session_state" / "session-one" / "session.json").exists()
        )

    def test_internal_state_is_not_exposed_as_workspace_file(self):
        session_state.replace_messages(
            "session-hidden",
            [{"role": "user", "content": "hello"}],
        )
        visible_paths = {
            item["path"] for item in workspace.list_workspace_files("session-hidden")
        }
        self.assertFalse(any(path.startswith(".deepanalyze/") for path in visible_paths))
        with self.assertRaises(HTTPException):
            workspace.get_workspace_file_response(
                "session-hidden",
                ".deepanalyze/session.json",
            )

    def test_clear_workspace_preserves_session_state(self):
        root = workspace.resolve_workspace_root("session-clear")
        (root / "input.csv").write_text("a\n1\n", encoding="utf-8")
        session_state.replace_messages(
            "session-clear",
            [{"role": "user", "content": "keep me"}],
        )
        workspace.clear_workspace("session-clear")
        self.assertFalse((root / "input.csv").exists())
        restored = session_state.load_session_state("session-clear")
        self.assertEqual(restored["messages"][0]["content"], "keep me")

    def test_upsert_message_reuses_stream_message_id(self):
        session_state.upsert_message(
            "session-stream",
            {"id": "assistant-1", "role": "assistant", "content": "partial"},
        )
        session_state.upsert_message(
            "session-stream",
            {"id": "assistant-1", "role": "assistant", "content": "complete"},
        )
        state = session_state.load_session_state("session-stream")
        self.assertEqual(len(state["messages"]), 1)
        self.assertEqual(state["messages"][0]["content"], "complete")

    def test_persists_system_prompt_and_migrates_legacy_requirements(self):
        state = session_state.update_task_config(
            "session-migration",
            {
                "instruction": "analyze",
                "system_prompt": "Use concise Chinese",
            },
        )
        task = state["task_config"]
        self.assertEqual(task["system_prompt"], "Use concise Chinese")

        migrated = session_state.update_task_config(
            "session-migration-legacy",
            {"additional_requirements": "Use concise Chinese"},
        )
        self.assertEqual(migrated["task_config"]["system_prompt"], "Use concise Chinese")

    def test_persists_manual_mode_and_exposes_only_public_pause_state(self):
        configured = session_state.update_task_config(
            "session-manual",
            {"interaction_mode": "manual"},
        )
        self.assertEqual(configured["task_config"]["interaction_mode"], "manual")

        session_state.save_pending_continuation(
            "session-manual",
            {
                "conversation": [
                    {"role": "user", "content": "analyze"},
                    {"role": "assistant", "content": "<Code>print(1)</Code>"},
                ],
                "execution_output": "1",
                "round_count": 1,
                "code_execution_count": 1,
                "elapsed_seconds": 0.5,
            },
        )
        public_state = session_state.load_public_session_state("session-manual")
        self.assertNotIn("pending_continuation", public_state)
        self.assertEqual(
            public_state["interaction_state"]["status"],
            "awaiting_user",
        )

        session_state.clear_pending_continuation("session-manual")
        public_state = session_state.load_public_session_state("session-manual")
        self.assertEqual(public_state["interaction_state"]["status"], "idle")


if __name__ == "__main__":
    unittest.main()
