import asyncio
import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend_app.services import chat, session_state, workspace
from backend_app.routers import chat as chat_router


def stream_text(text):
    yield text, {"choices": [{"finish_reason": "stop"}]}


def execution_outcome(result="ok"):
    return SimpleNamespace(
        result=result,
        execution_content=f"\n<Execute>\n```\n{result}\n```\n</Execute>\n",
    )


class ChatProtocolIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        safe_settings = replace(
            chat.settings,
            workspace_base_dir=self.temp_dir.name,
            chat_max_rounds=3,
            chat_max_duration_sec=30,
            chat_max_response_chars=10_000,
        )
        self.chat_settings_patch = patch.object(chat, "settings", safe_settings)
        self.workspace_settings_patch = patch.object(workspace, "settings", safe_settings)
        self.chat_settings_patch.start()
        self.workspace_settings_patch.start()
        self.prewarm_patch = patch.object(chat, "ensure_execution_backend_ready")
        self.prewarm_patch.start()
        self.addCleanup(self.chat_settings_patch.stop)
        self.addCleanup(self.workspace_settings_patch.stop)
        self.addCleanup(self.prewarm_patch.stop)

    def test_truncated_code_is_never_executed(self):
        execute_mock = Mock(return_value=execution_outcome("must not run"))
        with (
            patch.object(chat, "_iter_local_stream", return_value=stream_text(
                "<Analyze>plan</Analyze><Code>print('unsafe')"
            )),
            patch.object(chat, "execute_managed_code", execute_mock),
        ):
            output = "".join(chat.bot_stream(
                [{"role": "user", "content": "analyze"}], [], "session-truncated"
            ))
        self.assertIn("[Protocol Error]", output)
        execute_mock.assert_not_called()

    def test_prewarm_releases_container_when_stop_arrives_during_creation(self):
        stop_event = threading.Event()

        def complete_after_stop(_session_id):
            stop_event.set()

        with (
            patch.object(
                chat,
                "ensure_execution_backend_ready",
                side_effect=complete_after_stop,
            ) as ensure_backend,
            patch.object(chat, "release_session_container") as release_container,
        ):
            chat._prewarm_execution_backend("session-prewarm-stop", stop_event)

        ensure_backend.assert_called_once_with("session-prewarm-stop")
        release_container.assert_called_once_with("session-prewarm-stop")

    def test_complete_code_then_answer_runs_once_and_saves_report(self):
        responses = iter([
            stream_text("<Analyze>plan</Analyze><Code>print('ok')</Code>"),
            stream_text("<Understand>result is valid</Understand><Answer>done</Answer>"),
        ])
        with (
            patch.object(chat, "_iter_local_stream", side_effect=lambda *_: next(responses)),
            patch.object(
                chat, "execute_managed_code", return_value=execution_outcome()
            ) as execute_mock,
        ):
            output = "".join(chat.bot_stream(
                [{"role": "user", "content": "analyze"}], [], "session-complete"
            ))
        self.assertIn("<Execute>", output)
        self.assertIn("<Answer>done</Answer>", output)
        execute_mock.assert_called_once()
        reports = list(
            (Path(self.temp_dir.name) / "session-complete" / "generated").glob(
                "Answer_Report_*.md"
            )
        )
        self.assertEqual(len(reports), 1)

    def test_code_execution_count_does_not_stop_analysis(self):
        responses = iter(
            [
                stream_text(f"<Analyze>step {index}</Analyze><Code>print({index})</Code>")
                for index in range(3)
            ]
            + [stream_text("<Answer>done</Answer>")]
        )
        settings_without_early_round_limit = replace(chat.settings, chat_max_rounds=5)
        with (
            patch.object(chat, "settings", settings_without_early_round_limit),
            patch.object(chat, "_iter_local_stream", side_effect=lambda *_: next(responses)),
            patch.object(
                chat,
                "execute_managed_code",
                return_value=execution_outcome(),
            ) as execute_mock,
        ):
            output = "".join(
                chat.bot_stream(
                    [{"role": "user", "content": "analyze"}],
                    [],
                    "session-unlimited-code-executions",
                )
            )

        self.assertIn("<Answer>done</Answer>", output)
        self.assertNotIn("analysis exceeded", output)
        self.assertEqual(execute_mock.call_count, 3)

    def test_manual_mode_pauses_after_execute_before_model_feedback(self):
        model_stream = Mock(
            return_value=stream_text(
                "<Analyze>plan</Analyze><Code>print('ok')</Code>"
            )
        )
        with (
            patch.object(chat, "_iter_local_stream", model_stream),
            patch.object(
                chat,
                "execute_managed_code",
                return_value=execution_outcome("observed output"),
            ),
        ):
            output = "".join(
                chat.bot_stream(
                    [{"role": "user", "content": "analyze"}],
                    [],
                    "session-manual-pause",
                    interaction_mode="manual",
                )
            )

        self.assertIn("<Execute>", output)
        self.assertEqual(model_stream.call_count, 1)
        pending = session_state.load_pending_continuation("session-manual-pause")
        self.assertIsNotNone(pending)
        self.assertEqual(pending["execution_output"], "observed output")
        self.assertEqual(pending["conversation"][-1]["role"], "assistant")
        self.assertNotIn(
            "execute",
            [message["role"] for message in pending["conversation"]],
        )

    def test_manual_resume_appends_instruction_to_execute_feedback(self):
        session_id = "session-manual-resume"
        with (
            patch.object(
                chat,
                "_iter_local_stream",
                return_value=stream_text(
                    "<Analyze>plan</Analyze><Code>print('ok')</Code>"
                ),
            ),
            patch.object(
                chat,
                "execute_managed_code",
                return_value=execution_outcome("observed output"),
            ),
        ):
            list(
                chat.bot_stream(
                    [{"role": "user", "content": "analyze"}],
                    [],
                    session_id,
                    interaction_mode="manual",
                )
            )

        pending = session_state.load_pending_continuation(session_id)
        captured_conversations = []

        def answer_stream(conversation, *_args):
            captured_conversations.append(conversation)
            return stream_text("<Answer>done</Answer>")

        with patch.object(chat, "_iter_local_stream", side_effect=answer_stream):
            output = "".join(
                chat.bot_stream(
                    [],
                    [],
                    session_id,
                    interaction_mode="manual",
                    resume_state=pending,
                    additional_instruction="Focus on the regional anomaly.",
                )
            )

        self.assertIn("<Answer>done</Answer>", output)
        feedback = captured_conversations[0][-1]
        self.assertEqual(feedback["role"], "execute")
        self.assertEqual(
            feedback["content"],
            "observed output\n\n# Additional Instruction\n"
            "Focus on the regional anomaly.",
        )
        self.assertIsNone(session_state.load_pending_continuation(session_id))

    def test_manual_resume_without_instruction_forwards_unchanged_execute_feedback(self):
        session_id = "session-manual-resume-directly"
        session_state.save_pending_continuation(
            session_id,
            {
                "conversation": [
                    {"role": "user", "content": "analyze"},
                    {"role": "assistant", "content": "<Code>print('ok')</Code>"},
                ],
                "execution_output": "observed output",
                "round_count": 1,
                "code_execution_count": 1,
                "elapsed_seconds": 0.1,
            },
        )
        pending = session_state.load_pending_continuation(session_id)
        captured_conversations = []

        def answer_stream(conversation, *_args):
            captured_conversations.append(conversation)
            return stream_text("<Answer>done</Answer>")

        with patch.object(chat, "_iter_local_stream", side_effect=answer_stream):
            output = "".join(
                chat.bot_stream(
                    [],
                    [],
                    session_id,
                    interaction_mode="manual",
                    resume_state=pending,
                )
            )

        self.assertIn("<Answer>done</Answer>", output)
        self.assertEqual(
            captured_conversations[0][-1],
            {"role": "execute", "content": "observed output"},
        )
        self.assertIsNone(session_state.load_pending_continuation(session_id))

    def test_stream_end_chunk_reports_manual_pause_state(self):
        session_id = "session-manual-stream-status"

        def paused_stream(*_args, **_kwargs):
            session_state.save_pending_continuation(
                session_id,
                {
                    "conversation": [
                        {"role": "user", "content": "analyze"},
                        {"role": "assistant", "content": "<Code>print(1)</Code>"},
                    ],
                    "execution_output": "1",
                    "round_count": 1,
                    "code_execution_count": 1,
                    "elapsed_seconds": 0.1,
                },
            )
            yield "<Execute>1</Execute>"

        async def consume(response):
            chunks = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
            return "".join(chunks)

        with patch.object(chat_router, "bot_stream", side_effect=paused_stream):
            response = asyncio.run(
                chat_router.chat(
                    {
                        "messages": [{"role": "user", "content": "analyze"}],
                        "session_messages": [
                            {"id": "user-1", "role": "user", "content": "analyze"}
                        ],
                        "workspace": [],
                        "session_id": session_id,
                        "interaction_mode": "manual",
                    }
                )
            )
            body = asyncio.run(consume(response))

        end_chunk = json.loads(body.strip().splitlines()[-1])
        self.assertEqual(
            end_chunk["deepanalyze"]["interaction_status"],
            "awaiting_user",
        )

    def test_forwards_tagged_model_deltas_without_repacking_the_whole_round(self):
        model_deltas = iter(
            [
                ("<Analyze>", {"choices": [{"finish_reason": None}]}),
                ("plan", {"choices": [{"finish_reason": None}]}),
                ("</Analyze><Code>", {"choices": [{"finish_reason": None}]}),
                ("print('ok')", {"choices": [{"finish_reason": None}]}),
                ("</Code>", {"choices": [{"finish_reason": "stop"}]}),
                ("<Answer>done</Answer>", {"choices": [{"finish_reason": "stop"}]}),
            ]
        )
        with (
            patch.object(chat, "_iter_local_stream", return_value=model_deltas),
            patch.object(
                chat, "execute_managed_code", return_value=execution_outcome()
            ),
        ):
            chunks = list(
                chat.bot_stream(
                    [{"role": "user", "content": "analyze"}],
                    [],
                    "session-delta-forwarding",
                )
            )

        self.assertEqual(
            chunks[:5],
            ["<Analyze>", "plan", "</Analyze><Code>", "print('ok')", "</Code>"],
        )
        self.assertNotIn(
            "<Analyze>plan</Analyze>\n<Code>print('ok')</Code>",
            chunks,
        )

    def test_forwards_tagged_deltas_after_leading_whitespace(self):
        model_responses = iter(
            [
                iter(
                    [
                        ("\n", {"choices": [{"finish_reason": None}]}),
                        ("<Analyze>", {"choices": [{"finish_reason": None}]}),
                        ("plan", {"choices": [{"finish_reason": None}]}),
                        (
                            "</Analyze><Code>",
                            {"choices": [{"finish_reason": None}]},
                        ),
                        (
                            "print('ok')",
                            {"choices": [{"finish_reason": None}]},
                        ),
                        ("</Code>", {"choices": [{"finish_reason": "stop"}]}),
                    ]
                ),
                iter(
                    [
                        (
                            "<Answer>done</Answer>",
                            {"choices": [{"finish_reason": "stop"}]},
                        )
                    ]
                ),
            ]
        )
        with (
            patch.object(
                chat,
                "_iter_local_stream",
                side_effect=lambda *args, **kwargs: next(model_responses),
            ),
            patch.object(
                chat, "execute_managed_code", return_value=execution_outcome()
            ),
        ):
            chunks = list(
                chat.bot_stream(
                    [{"role": "user", "content": "analyze"}],
                    [],
                    "session-leading-whitespace",
                )
            )

        self.assertEqual(
            chunks[:6],
            ["\n", "<Analyze>", "plan", "</Analyze><Code>", "print('ok')", "</Code>"],
        )

    def test_forwards_initial_tagged_deltas_after_plain_prefix(self):
        model_responses = iter(
            [
                iter(
                    [
                        (
                            "I will inspect the data first.\n",
                            {"choices": [{"finish_reason": None}]},
                        ),
                        ("<Analyze>", {"choices": [{"finish_reason": None}]}),
                        ("plan", {"choices": [{"finish_reason": None}]}),
                        (
                            "</Analyze><Code>",
                            {"choices": [{"finish_reason": None}]},
                        ),
                        ("print('ok')", {"choices": [{"finish_reason": None}]}),
                        ("</Code>", {"choices": [{"finish_reason": "stop"}]}),
                    ]
                ),
                iter(
                    [
                        (
                            "<Answer>done</Answer>",
                            {"choices": [{"finish_reason": "stop"}]},
                        )
                    ]
                ),
            ]
        )
        with (
            patch.object(
                chat,
                "_iter_local_stream",
                side_effect=lambda *args, **kwargs: next(model_responses),
            ),
            patch.object(
                chat, "execute_managed_code", return_value=execution_outcome()
            ),
        ):
            chunks = list(
                chat.bot_stream(
                    [{"role": "user", "content": "analyze"}],
                    [],
                    "session-initial-prefix-streaming",
                )
            )

        self.assertEqual(
            chunks[:8],
            [
                "<Analyze>",
                "I will inspect the data first.\n",
                "</Analyze>",
                "<Analyze>",
                "plan",
                "</Analyze><Code>",
                "print('ok')",
                "</Code>",
            ],
        )

    def test_forwards_initial_tagged_deltas_after_think_prefix(self):
        model_responses = iter(
            [
                iter(
                    [
                        ("<think>", {"choices": [{"finish_reason": None}]}),
                        (
                            "inspect the available data",
                            {"choices": [{"finish_reason": None}]},
                        ),
                        ("</think>\n", {"choices": [{"finish_reason": None}]}),
                        ("<Analyze>", {"choices": [{"finish_reason": None}]}),
                        ("plan", {"choices": [{"finish_reason": None}]}),
                        (
                            "</Analyze><Code>",
                            {"choices": [{"finish_reason": None}]},
                        ),
                        ("print('ok')", {"choices": [{"finish_reason": None}]}),
                        ("</Code>", {"choices": [{"finish_reason": "stop"}]}),
                    ]
                ),
                iter(
                    [
                        (
                            "<Answer>done</Answer>",
                            {"choices": [{"finish_reason": "stop"}]},
                        )
                    ]
                ),
            ]
        )
        with (
            patch.object(
                chat,
                "_iter_local_stream",
                side_effect=lambda *args, **kwargs: next(model_responses),
            ),
            patch.object(
                chat, "execute_managed_code", return_value=execution_outcome()
            ),
        ):
            chunks = list(
                chat.bot_stream(
                    [{"role": "user", "content": "analyze"}],
                    [],
                    "session-initial-think-streaming",
                )
            )

        self.assertEqual(
            chunks[:10],
            [
                "<Analyze>",
                "<think>",
                "inspect the available data",
                "</think>\n",
                "</Analyze>",
                "<Analyze>",
                "plan",
                "</Analyze><Code>",
                "print('ok')",
                "</Code>",
            ],
        )

    def test_forwards_heywhale_like_plain_thinking_shape_incrementally(self):
        model_deltas = iter(
            [
                (
                    "Thinking before the action block.\n",
                    {"choices": [{"finish_reason": None}]},
                ),
                ("</Analyze>\n", {"choices": [{"finish_reason": None}]}),
                ("<Answer>", {"choices": [{"finish_reason": None}]}),
                ("ok", {"choices": [{"finish_reason": None}]}),
                ("</Answer>", {"choices": [{"finish_reason": "stop"}]}),
            ]
        )
        with patch.object(chat, "_iter_local_stream", return_value=model_deltas):
            chunks = list(
                chat.bot_stream(
                    [{"role": "user", "content": "analyze"}],
                    [],
                    "session-heywhale-like-streaming",
                )
            )

        self.assertEqual(
            chunks[:6],
            [
                "<Analyze>",
                "Thinking before the action block.\n",
                "</Analyze>",
                "\n",
                "<Answer>",
                "ok",
            ],
        )
        self.assertEqual(chunks[6], "</Answer>")

    def test_format_drift_is_silently_normalized(self):
        with patch.object(
            chat,
            "_iter_local_stream",
            return_value=stream_text("Here is the result.\n<Answer>done</Answer>"),
        ):
            output = "".join(
                chat.bot_stream(
                    [
                        {"role": "user", "content": "first question"},
                        {"role": "assistant", "content": "<Answer>first</Answer>"},
                        {"role": "user", "content": "analyze"},
                    ],
                    [],
                    "session-normalized",
                )
            )
        self.assertEqual(
            output.split("\n<File>", 1)[0],
            "<Analyze>Here is the result.</Analyze>\n<Answer>done</Answer>",
        )
        self.assertNotIn("Protocol Warning", output)

    def test_initial_response_gets_analyze_open_tag_when_plain_text_starts_it(self):
        heywhale_shape = (
            "Thinking before the action block.\n"
            "</Analyze>\n<Answer>ok</Answer>"
        )
        with patch.object(
            chat,
            "_iter_local_stream",
            return_value=stream_text(heywhale_shape),
        ):
            output = "".join(
                chat.bot_stream(
                    [{"role": "user", "content": "analyze"}],
                    [],
                    "session-initial-prefix",
                )
            )
        self.assertIn(
            "<Analyze>Thinking before the action block.\n</Analyze>",
            output,
        )
        self.assertIn("<Answer>ok</Answer>", output)
        self.assertNotIn("Protocol Error", output)

    def test_follow_up_response_does_not_get_initial_analyze_tag(self):
        heywhale_shape = (
            "Thinking before the action block.\n"
            "</Analyze>\n<Answer>ok</Answer>"
        )
        with patch.object(
            chat,
            "_iter_local_stream",
            return_value=stream_text(heywhale_shape),
        ):
            output = "".join(
                chat.bot_stream(
                    [
                        {"role": "user", "content": "first question"},
                        {"role": "assistant", "content": "<Answer>first</Answer>"},
                        {"role": "user", "content": "follow up"},
                    ],
                    [],
                    "session-follow-up-no-prefix",
                )
            )
        self.assertIn("[Protocol Error]", output)

    def test_heywhale_stream_uses_stop_sequences_and_restores_code_close_tag(self):
        lines = [
            'data: {"choices":[{"delta":{"content":"<Code>print(1)"},"finish_reason":null}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            "data: [DONE]",
        ]
        response = Mock()
        response.raise_for_status = Mock()
        response.iter_lines.return_value = lines
        stream_context = Mock()
        stream_context.__enter__ = Mock(return_value=response)
        stream_context.__exit__ = Mock(return_value=False)
        client = Mock()
        client.stream.return_value = stream_context
        client_context = Mock()
        client_context.__enter__ = Mock(return_value=client)
        client_context.__exit__ = Mock(return_value=False)
        runtime = chat.ChatRuntimeConfig(
            provider="heywhale",
            model="DeepAnalyze-8B",
            api_key="test-key",
            api_base=chat.HEYWHALE_API_BASE,
        )

        with patch.object(chat.httpx, "Client", return_value=client_context):
            chunks = list(chat._iter_heywhale_stream([], runtime))

        request_payload = client.stream.call_args.kwargs["json"]
        self.assertEqual(request_payload["stop"], ["</Code>", "</Answer>"])
        self.assertEqual("".join(delta or "" for delta, _ in chunks), "<Code>print(1)</Code>")

    def test_round_budget_stops_an_unfinished_workflow(self):
        limited_settings = replace(chat.settings, chat_max_rounds=1)
        with (
            patch.object(chat, "settings", limited_settings),
            patch.object(chat, "_iter_local_stream", return_value=stream_text(
                "<Analyze>plan</Analyze><Code>print('ok')</Code>"
            )),
            patch.object(
                chat, "execute_managed_code", return_value=execution_outcome()
            ),
        ):
            output = "".join(chat.bot_stream(
                [{"role": "user", "content": "analyze"}], [], "session-budget"
            ))
        self.assertIn("[Budget Exceeded]", output)

    def test_same_session_rejects_concurrent_run(self):
        lock = chat.try_acquire_session_run("session-busy")
        self.assertIsNotNone(lock)
        try:
            output = "".join(chat.bot_stream([], [], "session-busy"))
        finally:
            chat.release_session_run("session-busy", lock)
        self.assertIn("[Session Busy]", output)

    def test_stop_endpoint_waits_until_session_accepts_a_new_run(self):
        session_id = "session-stop-release"
        stream_started = threading.Event()

        def slow_stream(*_args):
            stream_started.set()
            while True:
                yield "working", {"choices": [{"finish_reason": None}]}
                time.sleep(0.01)

        with (
            patch.object(chat, "_iter_local_stream", side_effect=slow_stream),
            patch.object(
                chat_router,
                "release_session_container",
                return_value=True,
            ) as release_container,
        ):
            worker = threading.Thread(
                target=lambda: list(
                    chat.bot_stream(
                        [{"role": "user", "content": "analyze"}],
                        [],
                        session_id,
                    )
                ),
                daemon=True,
            )
            worker.start()
            self.assertTrue(stream_started.wait(timeout=1))
            result = asyncio.run(chat_router.stop_chat({"session_id": session_id}))
            worker.join(timeout=1)

        self.assertFalse(worker.is_alive())
        self.assertTrue(result["stopped"])
        self.assertTrue(result["container_released"])
        release_container.assert_called_once_with(session_id)
        with patch.object(
            chat,
            "_iter_local_stream",
            return_value=stream_text("<Answer>done</Answer>"),
        ):
            output = "".join(
                chat.bot_stream(
                    [{"role": "user", "content": "analyze again"}],
                    [],
                    session_id,
                )
            )
        self.assertNotIn("[Session Busy]", output)
        self.assertIn("<Answer>done</Answer>", output)

    def test_stop_endpoint_closes_a_blocked_upstream_stream(self):
        session_id = "session-stop-blocked-stream"

        class BlockingStream:
            def __init__(self):
                self.started = threading.Event()
                self.closed = threading.Event()
                self.release = threading.Event()
                self.close_release = threading.Event()

            def __iter__(self):
                return self

            def __next__(self):
                self.started.set()
                self.release.wait(timeout=2)
                raise StopIteration

            def close(self):
                self.closed.set()
                self.close_release.wait(timeout=2)

        blocked_stream = BlockingStream()
        mock_client = Mock()
        mock_client.with_options.return_value.chat.completions.create.return_value = (
            blocked_stream
        )

        with (
            patch.object(chat, "client", mock_client),
            patch.object(
                chat_router,
                "release_session_container",
                return_value=True,
            ) as release_container,
        ):
            worker = threading.Thread(
                target=lambda: list(
                    chat.bot_stream(
                        [{"role": "user", "content": "analyze"}],
                        [],
                        session_id,
                    )
                ),
                daemon=True,
            )
            worker.start()
            self.assertTrue(blocked_stream.started.wait(timeout=1))
            started_at = time.monotonic()
            result = asyncio.run(chat_router.stop_chat({"session_id": session_id}))
            elapsed = time.monotonic() - started_at
            worker.join(timeout=1)

        self.assertTrue(blocked_stream.closed.is_set())
        self.assertFalse(worker.is_alive())
        self.assertTrue(result["stopped"])
        self.assertTrue(result["container_released"])
        release_container.assert_called_once_with(session_id)
        self.assertLess(elapsed, 1)
        Path(workspace.get_session_workspace(session_id), "partial.csv").write_text(
            "value\n1\n",
            encoding="utf-8",
        )
        session_state.replace_messages(
            session_id,
            [{"id": "partial", "role": "assistant", "content": "partial"}],
        )
        workspace.clear_workspace(session_id)
        session_state.replace_messages(session_id, [])
        with patch.object(
            chat,
            "_iter_local_stream",
            return_value=stream_text("<Answer>new task done</Answer>"),
        ):
            output = "".join(
                chat.bot_stream(
                    [{"role": "user", "content": "new task"}],
                    [],
                    session_id,
                )
            )
        self.assertNotIn("[Session Busy]", output)
        self.assertIn("<Answer>new task done</Answer>", output)
        blocked_stream.close_release.set()
        blocked_stream.release.set()

    def test_cancelled_late_stream_cannot_replace_new_run_stream(self):
        session_id = "session-late-cancelled-stream"
        old_stop_event = chat.begin_session_run_stop_event(session_id)
        old_stop_event.set()
        new_stop_event = chat.begin_session_run_stop_event(session_id)
        new_close = Mock()
        new_token = chat._register_active_stream(
            session_id,
            new_close,
            new_stop_event,
        )
        old_close = Mock()

        old_token = chat._register_active_stream(
            session_id,
            old_close,
            old_stop_event,
        )

        self.assertIsNone(old_token)
        old_close.assert_called_once_with()
        chat.request_stop(session_id)
        new_close.assert_called_once_with()
        chat._clear_active_stream(session_id, new_token)

    def test_explicit_empty_file_selection_does_not_include_all_files(self):
        workspace_dir = workspace.get_session_workspace("session-selection")
        Path(workspace_dir, "input.csv").write_text("a\n1\n", encoding="utf-8")
        explicit_messages = [{"role": "user", "content": "analyze"}]
        chat._build_user_prompt(
            explicit_messages,
            [],
            workspace_dir,
            use_all_files_when_empty=False,
        )
        self.assertNotIn("# Data", explicit_messages[-1]["content"])

        legacy_messages = [{"role": "user", "content": "analyze"}]
        chat._build_user_prompt(
            legacy_messages,
            [],
            workspace_dir,
            use_all_files_when_empty=True,
        )
        self.assertIn("input.csv", legacy_messages[-1]["content"])


if __name__ == "__main__":
    unittest.main()
