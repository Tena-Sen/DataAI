import io
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile

from backend_app.routers import workspace as workspace_router
from backend_app.services import session_state, workspace


class WorkspaceSecurityTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.settings = replace(
            workspace.settings,
            workspace_base_dir=self.temp_dir.name,
            upload_max_file_bytes=8,
            workspace_max_bytes=12,
            workspace_max_files=2,
            upload_chunk_bytes=4,
        )
        self.settings_patch = patch.object(workspace, "settings", self.settings)
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    def test_rejects_invalid_session_ids_and_relative_escape(self):
        for session_id in ["../outside", "a/b", "C:escape", ".", ".."]:
            with self.subTest(session_id=session_id), self.assertRaises(HTTPException):
                workspace.resolve_workspace_root(session_id)

        root = workspace.resolve_workspace_root("session-1")
        with self.assertRaises(HTTPException):
            workspace.resolve_workspace_path("session-1", "../session-2/secret.csv")
        self.assertEqual(root.parent, Path(self.temp_dir.name).resolve())

    async def test_rejects_upload_filename_traversal(self):
        upload = UploadFile(filename="../secret.txt", file=io.BytesIO(b"data"))
        with self.assertRaisesRegex(HTTPException, "Invalid upload filename"):
            await workspace.upload_files_to_workspace("session-1", [upload])
        self.assertFalse((Path(self.temp_dir.name) / "secret.txt").exists())

    async def test_streams_upload_and_enforces_file_size(self):
        accepted = UploadFile(filename="small.txt", file=io.BytesIO(b"12345678"))
        result = await workspace.upload_files_to_workspace("session-1", [accepted])
        self.assertEqual(result["files"][0]["size"], 8)

        oversized = UploadFile(filename="large.txt", file=io.BytesIO(b"123456789"))
        file_limit_settings = replace(self.settings, workspace_max_bytes=100)
        with (
            patch.object(workspace, "settings", file_limit_settings),
            self.assertRaisesRegex(HTTPException, "file size"),
        ):
            await workspace.upload_files_to_workspace("session-1", [oversized])
        self.assertFalse((workspace.resolve_workspace_root("session-1") / "large.txt").exists())

    async def test_enforces_workspace_total_size(self):
        first = UploadFile(filename="first.txt", file=io.BytesIO(b"12345678"))
        second = UploadFile(filename="second.txt", file=io.BytesIO(b"12345"))
        await workspace.upload_files_to_workspace("session-1", [first])
        with self.assertRaisesRegex(HTTPException, "Workspace size"):
            await workspace.upload_files_to_workspace("session-1", [second])

    def test_loads_reusable_catalog_sample_without_overwriting_user_file(self):
        roomy_settings = replace(
            self.settings,
            upload_max_file_bytes=2_000_000,
            workspace_max_bytes=10_000_000,
            workspace_max_files=10,
        )
        with patch.object(workspace, "settings", roomy_settings):
            root = workspace.resolve_workspace_root("session-sample")
            (root / "penguins.csv").write_text("user data", encoding="utf-8")
            first = workspace.create_sample_data("session-sample", "palmer_penguins")
            second = workspace.create_sample_data("session-sample", "palmer_penguins")

            self.assertEqual(first["files"][0]["path"], "penguins (1).csv")
            self.assertEqual(second["files"][0]["path"], "penguins (1).csv")
            self.assertEqual((root / "penguins.csv").read_text(encoding="utf-8"), "user data")
            content = (root / "penguins (1).csv").read_text(encoding="utf-8")
            self.assertIn("Adelie,Torgersen", content)

    def test_sample_catalog_is_bilingual_and_rejects_unknown_ids(self):
        catalog = workspace.get_sample_catalog()["datasets"]
        self.assertEqual(len(catalog), 4)
        expected_question_counts = {
            "palmer_penguins": 3,
            "life_expectancy": 2,
            "bike_sharing": 4,
            "college_majors": 1,
        }
        for dataset in catalog:
            self.assertTrue(dataset["title"]["zh"])
            self.assertTrue(dataset["title"]["en"])
            self.assertEqual(
                len(dataset["questions"]), expected_question_counts[dataset["id"]]
            )
            self.assertEqual(
                len({question["id"] for question in dataset["questions"]}),
                len(dataset["questions"]),
            )
            for question in dataset["questions"]:
                self.assertTrue(question["prompt"]["zh"])
                self.assertTrue(question["prompt"]["en"])
                self.assertNotIn("\n3.", question["prompt"]["zh"])
                self.assertNotIn("\n3.", question["prompt"]["en"])

        with self.assertRaisesRegex(HTTPException, "Unknown sample dataset"):
            workspace.create_sample_data("session-sample", "not-a-sample")

    def test_loads_every_catalog_dataset(self):
        roomy_settings = replace(
            self.settings,
            upload_max_file_bytes=2_000_000,
            workspace_max_bytes=20_000_000,
            workspace_max_files=20,
        )
        catalog = workspace.get_sample_catalog()["datasets"]
        with patch.object(workspace, "settings", roomy_settings):
            for dataset in catalog:
                with self.subTest(dataset=dataset["id"]):
                    result = workspace.create_sample_data(
                        f"session-{dataset['id']}", dataset["id"]
                    )
                    self.assertEqual(len(result["files"]), len(dataset["files"]))
                    self.assertTrue(all(file["size"] > 0 for file in result["files"]))

    def test_sample_load_can_clear_workspace_first(self):
        roomy_settings = replace(
            self.settings,
            upload_max_file_bytes=2_000_000,
            workspace_max_bytes=10_000_000,
            workspace_max_files=10,
        )
        with patch.object(workspace, "settings", roomy_settings):
            root = workspace.resolve_workspace_root("session-replace-sample")
            (root / "old-upload.csv").write_text("old", encoding="utf-8")
            (root / "generated").mkdir()
            (root / "generated" / "old-chart.png").write_bytes(b"old")
            (root / workspace.INTERNAL_WORKSPACE_DIRNAME).mkdir()
            internal_marker = root / workspace.INTERNAL_WORKSPACE_DIRNAME / "state.json"
            internal_marker.write_text("{}", encoding="utf-8")

            result = workspace.create_sample_data(
                "session-replace-sample",
                "palmer_penguins",
                clear_existing=True,
            )

            self.assertTrue(result["workspace_cleared"])
            self.assertFalse((root / "old-upload.csv").exists())
            self.assertFalse((root / "generated").exists())
            self.assertTrue(internal_marker.exists())
            self.assertEqual([file["path"] for file in result["files"]], ["penguins.csv"])

    async def test_clear_route_releases_container_before_deleting_files(self):
        session_id = "session-clear-route"
        root = workspace.resolve_workspace_root(session_id)
        old_file = root / "old.csv"
        old_file.write_text("old", encoding="utf-8")
        session_state.save_pending_continuation(
            session_id,
            {"conversation": [{"role": "user", "content": "analyze"}]},
        )

        with patch.object(
            workspace_router,
            "release_session_container",
            return_value=True,
        ) as release_container:
            result = await workspace_router.clear_workspace(session_id)

        release_container.assert_called_once_with(session_id)
        self.assertFalse(old_file.exists())
        self.assertEqual(result["message"], "Workspace cleared successfully")
        self.assertIsNone(session_state.load_pending_continuation(session_id))

    async def test_sample_route_releases_container_when_replacing_workspace(self):
        roomy_settings = replace(
            self.settings,
            upload_max_file_bytes=2_000_000,
            workspace_max_bytes=10_000_000,
            workspace_max_files=10,
        )
        session_id = "session-sample-route"
        with (
            patch.object(workspace, "settings", roomy_settings),
            patch.object(
                workspace_router,
                "release_session_container",
                return_value=True,
            ) as release_container,
        ):
            root = workspace.resolve_workspace_root(session_id)
            old_file = root / "old.csv"
            old_file.write_text("old", encoding="utf-8")
            session_state.save_pending_continuation(
                session_id,
                {"conversation": [{"role": "user", "content": "analyze"}]},
            )
            result = await workspace_router.create_sample_data(
                "palmer_penguins",
                session_id,
                True,
            )

        release_container.assert_called_once_with(session_id)
        self.assertFalse(old_file.exists())
        self.assertTrue(result["workspace_cleared"])
        self.assertIsNone(session_state.load_pending_continuation(session_id))

    def test_list_workspace_files_uses_explicit_generated_metadata(self):
        root = workspace.resolve_workspace_root("session-classification")
        (root / "report.md").write_text("uploaded", encoding="utf-8")
        (root / "generated").mkdir()
        (root / "generated" / "report.md").write_text("generated", encoding="utf-8")
        workspace.register_generated_paths(
            "session-classification", ["generated/report.md"]
        )

        files = workspace.list_workspace_files("session-classification")
        by_path = {file["path"]: file for file in files}
        self.assertFalse(by_path["report.md"]["is_generated"])
        self.assertTrue(by_path["generated/report.md"]["is_generated"])

    def test_list_workspace_files_changes_version_when_same_name_is_overwritten(self):
        root = workspace.resolve_workspace_root("session-version")
        target = root / "generated" / "chart.png"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"old")
        first = workspace.list_workspace_files("session-version")
        target.write_bytes(b"new")
        stat = target.stat()
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))
        second = workspace.list_workspace_files("session-version")
        first_file = next(item for item in first if item["path"] == "generated/chart.png")
        second_file = next(item for item in second if item["path"] == "generated/chart.png")
        self.assertNotEqual(first_file["modified_at_ns"], second_file["modified_at_ns"])
        self.assertNotEqual(first_file["preview_url"], second_file["preview_url"])


if __name__ == "__main__":
    unittest.main()
