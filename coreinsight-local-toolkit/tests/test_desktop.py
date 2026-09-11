import socket
import unittest
import uuid
from unittest.mock import MagicMock, patch

from coreinsight_local_toolkit.desktop import (
    _activate_existing, _ensure_default_autostart, _port_is_open,
    _SingleInstanceMutex, _startup_command,
)


class DesktopTests(unittest.TestCase):
    def test_detects_occupied_port(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        try:
            self.assertTrue(_port_is_open(listener.getsockname()[1]))
        finally:
            listener.close()

    def test_named_mutex_allows_only_one_process_instance(self):
        name = f"Global\\CoreInsight.LocalToolkit.Test.{uuid.uuid4().hex}"
        first = _SingleInstanceMutex(name)
        second = _SingleInstanceMutex(name)
        replacement = _SingleInstanceMutex(name)
        try:
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.close()
            self.assertTrue(replacement.acquire())
        finally:
            first.close()
            second.close()
            replacement.close()

    @patch("coreinsight_local_toolkit.desktop.urllib.request.urlopen")
    def test_existing_instance_can_be_activated(self, urlopen):
        health = MagicMock()
        health.read.return_value = (
            b'{"code":200,"msg":"ok","data":'
            b'{"service":"coreinsight-local-toolkit"}}')
        activated = MagicMock(status=200)
        urlopen.side_effect = [
            MagicMock(__enter__=MagicMock(return_value=health)),
            MagicMock(__enter__=MagicMock(return_value=activated)),
        ]
        self.assertTrue(_activate_existing(17831))
        request = urlopen.call_args_list[1].args[0]
        self.assertEqual("POST", request.method)
        self.assertEqual("http://127.0.0.1:17831/desktop/show", request.full_url)

    @patch("coreinsight_local_toolkit.desktop.urllib.request.urlopen")
    def test_unrelated_service_is_not_activated(self, urlopen):
        health = MagicMock()
        health.read.return_value = b'{"service":"something-else"}'
        urlopen.return_value.__enter__.return_value = health
        self.assertFalse(_activate_existing(17831))
        self.assertEqual(1, urlopen.call_count)

    @patch("coreinsight_local_toolkit.desktop.sys.frozen", True, create=True)
    @patch("coreinsight_local_toolkit.desktop.sys.executable",
           r"C:\\Program Files\\CoreInsight\\toolkit.exe")
    def test_packaged_startup_command_contains_startup_flag(self):
        command = _startup_command()
        self.assertIn("toolkit.exe", command)
        self.assertIn("--startup", command)

    @patch("coreinsight_local_toolkit.desktop.sys.platform", "win32")
    @patch("coreinsight_local_toolkit.desktop.sys.frozen", True, create=True)
    @patch("coreinsight_local_toolkit.desktop._set_autostart")
    @patch("coreinsight_local_toolkit.desktop._autostart_initialized",
           return_value=False)
    @patch("coreinsight_local_toolkit.desktop._read_autostart_command",
           return_value="")
    def test_autostart_is_enabled_by_default(
            self, _read, _initialized, set_autostart):
        _ensure_default_autostart()
        set_autostart.assert_called_once_with(True)

    @patch("coreinsight_local_toolkit.desktop.sys.platform", "win32")
    @patch("coreinsight_local_toolkit.desktop.sys.frozen", True, create=True)
    @patch("coreinsight_local_toolkit.desktop._set_autostart")
    @patch("coreinsight_local_toolkit.desktop._autostart_initialized",
           return_value=True)
    @patch("coreinsight_local_toolkit.desktop._read_autostart_command",
           return_value="")
    def test_explicitly_disabled_autostart_stays_disabled(
            self, _read, _initialized, set_autostart):
        _ensure_default_autostart()
        set_autostart.assert_not_called()


if __name__ == "__main__":
    unittest.main()
