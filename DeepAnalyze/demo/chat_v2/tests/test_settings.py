import os
import unittest
from unittest.mock import patch

from backend_app.settings import _get_port_env


class PortSettingsTest(unittest.TestCase):
    def test_port_can_be_configured_from_environment(self):
        with patch.dict(os.environ, {"TEST_SERVICE_PORT": "8300"}):
            self.assertEqual(_get_port_env("TEST_SERVICE_PORT", 9000), 8300)

    def test_port_uses_default_when_environment_is_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_get_port_env("TEST_SERVICE_PORT", 9000), 9000)

    def test_invalid_port_is_rejected(self):
        for value in ("invalid", "0", "65536"):
            with self.subTest(value=value):
                with (
                    patch.dict(os.environ, {"TEST_SERVICE_PORT": value}),
                    self.assertRaisesRegex(ValueError, "TEST_SERVICE_PORT"),
                ):
                    _get_port_env("TEST_SERVICE_PORT", 9000)


if __name__ == "__main__":
    unittest.main()
