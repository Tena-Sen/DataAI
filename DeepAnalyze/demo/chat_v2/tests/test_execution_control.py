import tempfile
import threading
import time
import unittest
from dataclasses import replace
from unittest.mock import patch

from backend_app.services import execution


class ExecutionControlTest(unittest.TestCase):
    def test_local_development_execution_can_be_cancelled(self):
        local_settings = replace(
            execution.settings,
            execution_mode="local",
            allow_unsafe_local_execution=True,
        )
        cancel_event = threading.Event()
        timer = threading.Timer(0.3, cancel_event.set)
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            execution, "settings", local_settings
        ):
            started_at = time.monotonic()
            timer.start()
            try:
                result = execution.execute_code_safe(
                    "import time\ntime.sleep(10)",
                    temp_dir,
                    "session-cancel",
                    5,
                    cancel_event,
                )
            finally:
                timer.cancel()
        self.assertIn("[Cancelled]", result)
        self.assertLess(time.monotonic() - started_at, 4)

    def test_local_execution_requires_explicit_opt_in(self):
        local_settings = replace(
            execution.settings,
            execution_mode="local",
            allow_unsafe_local_execution=False,
        )
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            execution, "settings", local_settings
        ):
            result = execution.execute_code_safe("print('no')", temp_dir)
        self.assertIn("local execution is disabled", result)


if __name__ == "__main__":
    unittest.main()
