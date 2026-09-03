import tempfile
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend_app.services import docker_executor, workspace


class DockerIsolationTest(unittest.TestCase):
    def tearDown(self):
        docker_executor._SESSION_CONTAINERS.clear()

    def test_container_mounts_only_session_and_applies_resource_limits(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            safe_settings = replace(
                docker_executor.settings,
                execution_mode="docker",
                workspace_base_dir=temp_dir,
                docker_image="deepanalyze-test:latest",
                docker_network_mode="none",
                docker_memory="512m",
                docker_cpus=0.5,
                docker_pids_limit=64,
                docker_user="1000:1000",
                docker_read_only=True,
                docker_tmpfs_size="64m",
            )
            commands = []

            def capture(args, **_kwargs):
                commands.append(args)
                return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            docker_executor._SESSION_CONTAINERS.clear()
            with (
                patch.object(docker_executor, "settings", safe_settings),
                patch.object(workspace, "settings", safe_settings),
                patch.object(docker_executor, "_container_is_running", return_value=False),
                patch.object(docker_executor, "_container_exists", return_value=False),
                patch.object(docker_executor, "_image_exists", return_value=True),
                patch.object(docker_executor, "_run_docker_command", side_effect=capture),
            ):
                docker_executor.ensure_execution_backend_ready("session-1")
                expected_owner = docker_executor._deployment_owner_id()

            run_args = commands[-1]
            mount_value = run_args[run_args.index("-v") + 1]
            expected_session_root = str(Path(temp_dir, "session-1").resolve())
            self.assertEqual(mount_value, f"{expected_session_root}:/workspace:rw")
            self.assertNotEqual(mount_value, f"{Path(temp_dir).resolve()}:/workspace:rw")
            self.assertIn(
                f"{docker_executor.APP_LABEL_KEY}={docker_executor.APP_LABEL_VALUE}",
                run_args,
            )
            self.assertIn(
                f"{docker_executor.OWNER_LABEL_KEY}={expected_owner}",
                run_args,
            )
            for required in [
                "--cap-drop",
                "--security-opt",
                "--network",
                "--memory",
                "--cpus",
                "--pids-limit",
                "--read-only",
                "--tmpfs",
                "--user",
            ]:
                self.assertIn(required, run_args)

    def test_container_names_do_not_collide_after_sanitizing(self):
        first = docker_executor._container_name_for_session("session.a")
        second = docker_executor._container_name_for_session("session-a")
        self.assertNotEqual(first, second)

    def test_existing_container_must_match_labels_and_session_mount(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session_root = Path(temp_dir, "session-1").resolve()
            session_root.mkdir()
            inspect_payload = [{
                "Config": {"Labels": {
                    docker_executor.MANAGED_LABEL_KEY: "true",
                    docker_executor.SESSION_LABEL_KEY: "session-1",
                }},
                "Mounts": [{"Source": str(session_root), "Destination": "/workspace"}],
            }]
            completed = type(
                "Completed",
                (),
                {"returncode": 0, "stdout": json.dumps(inspect_payload), "stderr": ""},
            )()
            with patch.object(docker_executor, "_run_docker_command", return_value=completed):
                self.assertTrue(docker_executor._container_matches_session(
                    "container", "session-1", session_root
                ))
                self.assertFalse(docker_executor._container_matches_session(
                    "container", "session-2", session_root
                ))

    def test_cleanup_discovers_and_removes_stale_container_after_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            safe_settings = replace(
                docker_executor.settings,
                workspace_base_dir=temp_dir,
                docker_session_idle_ttl_sec=30,
            )
            session_id = "session-stale"
            session_root = Path(temp_dir, session_id).resolve()
            session_root.mkdir()
            with patch.object(docker_executor, "settings", safe_settings):
                container_name = docker_executor._container_name_for_session(session_id)
                payload = [{
                    "Config": {
                        "Image": safe_settings.docker_image,
                        "Labels": {
                            docker_executor.MANAGED_LABEL_KEY: "true",
                            docker_executor.SESSION_LABEL_KEY: session_id,
                            docker_executor.APP_LABEL_KEY: docker_executor.APP_LABEL_VALUE,
                            docker_executor.OWNER_LABEL_KEY: docker_executor._deployment_owner_id(),
                        },
                    },
                    "Mounts": [{
                        "Source": str(session_root),
                        "Destination": safe_settings.docker_workspace_dir,
                    }],
                    "State": {
                        "Running": True,
                        "StartedAt": "1970-01-01T00:00:00.000000000Z",
                    },
                }]
                commands = []

                def capture(args, **_kwargs):
                    commands.append(args)
                    stdout = ""
                    if args[0] == "ps":
                        stdout = f"{container_name}\n"
                    elif args[0] == "inspect":
                        stdout = json.dumps(payload)
                    return type(
                        "Completed",
                        (),
                        {"returncode": 0, "stdout": stdout, "stderr": ""},
                    )()

                with patch.object(
                    docker_executor,
                    "_run_docker_command",
                    side_effect=capture,
                ):
                    docker_executor.cleanup_idle_containers(now=100)

            self.assertIn(["rm", "-f", container_name], commands)
            self.assertNotIn(session_id, docker_executor._SESSION_CONTAINERS)

    def test_cleanup_ignores_container_owned_by_another_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            safe_settings = replace(
                docker_executor.settings,
                workspace_base_dir=temp_dir,
                docker_session_idle_ttl_sec=30,
            )
            session_id = "session-foreign"
            session_root = Path(temp_dir, session_id).resolve()
            session_root.mkdir()
            with patch.object(docker_executor, "settings", safe_settings):
                container_name = docker_executor._container_name_for_session(session_id)
                payload = [{
                    "Config": {
                        "Image": safe_settings.docker_image,
                        "Labels": {
                            docker_executor.MANAGED_LABEL_KEY: "true",
                            docker_executor.SESSION_LABEL_KEY: session_id,
                            docker_executor.APP_LABEL_KEY: docker_executor.APP_LABEL_VALUE,
                            docker_executor.OWNER_LABEL_KEY: "another-workspace",
                        },
                    },
                    "Mounts": [{
                        "Source": str(session_root),
                        "Destination": safe_settings.docker_workspace_dir,
                    }],
                    "State": {
                        "Running": True,
                        "StartedAt": "1970-01-01T00:00:00.000000000Z",
                    },
                }]

                def capture(args, **_kwargs):
                    stdout = (
                        f"{container_name}\n"
                        if args[0] == "ps"
                        else json.dumps(payload)
                    )
                    return type(
                        "Completed",
                        (),
                        {"returncode": 0, "stdout": stdout, "stderr": ""},
                    )()

                with patch.object(
                    docker_executor,
                    "_run_docker_command",
                    side_effect=capture,
                ):
                    docker_executor.cleanup_idle_containers(now=100)

            self.assertFalse(docker_executor._SESSION_CONTAINERS)

    def test_cleanup_discovers_legacy_container_for_current_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            safe_settings = replace(
                docker_executor.settings,
                workspace_base_dir=temp_dir,
                docker_session_idle_ttl_sec=30,
            )
            session_id = "session-legacy-stale"
            session_root = Path(temp_dir, session_id).resolve()
            session_root.mkdir()
            with patch.object(docker_executor, "settings", safe_settings):
                container_name = docker_executor._legacy_container_name_for_session(
                    session_id
                )
                payload = [{
                    "Config": {
                        "Image": safe_settings.docker_image,
                        "Labels": {
                            docker_executor.MANAGED_LABEL_KEY: "true",
                            docker_executor.SESSION_LABEL_KEY: session_id,
                        },
                    },
                    "Mounts": [{
                        "Source": str(session_root),
                        "Destination": safe_settings.docker_workspace_dir,
                    }],
                    "State": {
                        "Running": True,
                        "StartedAt": "1970-01-01T00:00:00.000000000Z",
                    },
                }]
                commands = []

                def capture(args, **_kwargs):
                    commands.append(args)
                    stdout = ""
                    if args[0] == "ps":
                        stdout = f"{container_name}\n"
                    elif args[0] == "inspect":
                        stdout = json.dumps(payload)
                    return type(
                        "Completed",
                        (),
                        {"returncode": 0, "stdout": stdout, "stderr": ""},
                    )()

                with patch.object(
                    docker_executor,
                    "_run_docker_command",
                    side_effect=capture,
                ):
                    docker_executor.cleanup_idle_containers(now=100)

            self.assertIn(["rm", "-f", container_name], commands)

    def test_cleanup_discovers_v0_container_with_workspace_root_mount(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            safe_settings = replace(
                docker_executor.settings,
                workspace_base_dir=temp_dir,
                docker_session_idle_ttl_sec=30,
            )
            session_id = "session-v0-stale"
            workspace_root = Path(temp_dir).resolve()
            with patch.object(docker_executor, "settings", safe_settings):
                container_name = docker_executor._v0_container_name_for_session(session_id)
                payload = [{
                    "Config": {
                        "Image": safe_settings.docker_image,
                        "Labels": {
                            docker_executor.MANAGED_LABEL_KEY: "true",
                            docker_executor.SESSION_LABEL_KEY: session_id,
                        },
                    },
                    "Mounts": [{
                        "Source": str(workspace_root),
                        "Destination": safe_settings.docker_workspace_dir,
                    }],
                    "State": {
                        "Running": False,
                        "StartedAt": "1970-01-01T00:00:00.000000000Z",
                    },
                }]
                commands = []

                def capture(args, **_kwargs):
                    commands.append(args)
                    stdout = ""
                    if args[0] == "ps":
                        stdout = f"{container_name}\n"
                    elif args[0] == "inspect":
                        stdout = json.dumps(payload)
                    return type(
                        "Completed",
                        (),
                        {"returncode": 0, "stdout": stdout, "stderr": ""},
                    )()

                with patch.object(
                    docker_executor,
                    "_run_docker_command",
                    side_effect=capture,
                ):
                    docker_executor.cleanup_idle_containers(now=100)

            self.assertIn(["rm", "-f", container_name], commands)

    def test_failed_idle_cleanup_keeps_state_for_retry(self):
        state = docker_executor.SessionContainerState(
            session_id="session-retry",
            container_name="container-retry",
            created_by_app=True,
            started_by_app=True,
            last_used_at=0,
        )
        docker_executor._SESSION_CONTAINERS[state.session_id] = state
        safe_settings = replace(
            docker_executor.settings,
            docker_session_idle_ttl_sec=30,
        )
        with (
            patch.object(docker_executor, "settings", safe_settings),
            patch.object(docker_executor, "_discover_managed_containers"),
            patch.object(
                docker_executor,
                "_remove_container",
                side_effect=RuntimeError("Docker unavailable"),
            ),
        ):
            docker_executor.cleanup_idle_containers(now=100)

        self.assertIs(docker_executor._SESSION_CONTAINERS[state.session_id], state)

    def test_remove_container_raises_when_docker_probe_also_fails(self):
        failed = type(
            "Completed",
            (),
            {"returncode": 1, "stdout": "", "stderr": "Docker unavailable"},
        )()
        with (
            patch.object(
                docker_executor,
                "_run_docker_command",
                return_value=failed,
            ),
            self.assertRaisesRegex(RuntimeError, "Failed to query container"),
        ):
            docker_executor._remove_container("container-unavailable", remove=True)

    def test_release_session_removes_untracked_legacy_container(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            safe_settings = replace(docker_executor.settings, workspace_base_dir=temp_dir)
            session_id = "session-legacy"
            session_root = Path(temp_dir, session_id).resolve()
            session_root.mkdir()
            with patch.object(docker_executor, "settings", safe_settings):
                modern_name = docker_executor._container_name_for_session(session_id)
                legacy_name = docker_executor._legacy_container_name_for_session(session_id)
                payload = {
                    "Config": {
                        "Image": safe_settings.docker_image,
                        "Labels": {
                            docker_executor.MANAGED_LABEL_KEY: "true",
                            docker_executor.SESSION_LABEL_KEY: session_id,
                        },
                    },
                    "Mounts": [{
                        "Source": str(session_root),
                        "Destination": safe_settings.docker_workspace_dir,
                    }],
                }
                removed = []
                with (
                    patch.object(
                        docker_executor,
                        "_container_exists_checked",
                        side_effect=lambda name: name == legacy_name,
                    ),
                    patch.object(docker_executor, "_inspect_container", return_value=payload),
                    patch.object(
                        docker_executor,
                        "_remove_container",
                        side_effect=lambda name, **_kwargs: removed.append(name),
                    ),
                ):
                    released = docker_executor.release_session_container(session_id)

            self.assertNotEqual(modern_name, legacy_name)
            self.assertTrue(released)
            self.assertEqual(removed, [legacy_name])

    def test_missing_execution_image_is_built_from_project_dockerfile(self):
        safe_settings = replace(
            docker_executor.settings,
            docker_image="deepanalyze-test:latest",
            docker_auto_build=True,
        )
        completed = type(
            "Completed",
            (),
            {"returncode": 0, "stdout": "built", "stderr": ""},
        )()
        with (
            patch.object(docker_executor, "settings", safe_settings),
            patch.object(docker_executor, "_image_exists", return_value=False),
            patch.object(
                docker_executor,
                "_run_docker_command",
                return_value=completed,
            ) as run_command,
        ):
            docker_executor._ensure_docker_image_available()

        build_args = run_command.call_args.args[0]
        dockerfile = Path(build_args[build_args.index("-f") + 1])
        self.assertEqual(build_args[:3], ["build", "-t", "deepanalyze-test:latest"])
        self.assertEqual(dockerfile.name, "Dockerfile.exec")
        self.assertTrue(dockerfile.is_absolute())
        self.assertEqual(Path(build_args[-1]), dockerfile.parent)

    def test_missing_execution_image_respects_disabled_auto_build(self):
        safe_settings = replace(
            docker_executor.settings,
            docker_image="managed-externally:latest",
            docker_auto_build=False,
        )
        with (
            patch.object(docker_executor, "settings", safe_settings),
            patch.object(docker_executor, "_image_exists", return_value=False),
            self.assertRaisesRegex(RuntimeError, "DEEPANALYZE_DOCKER_AUTO_BUILD"),
        ):
            docker_executor._ensure_docker_image_available()

    def test_unavailable_docker_daemon_has_actionable_error(self):
        failed = type(
            "Completed",
            (),
            {"returncode": 1, "stdout": "", "stderr": "cannot connect"},
        )()
        with (
            patch.object(docker_executor, "_run_docker_command", return_value=failed),
            self.assertRaisesRegex(RuntimeError, "Start Docker Desktop"),
        ):
            docker_executor._ensure_docker_daemon_available()


if __name__ == "__main__":
    unittest.main()
