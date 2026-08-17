import socket
import unittest
from unittest.mock import MagicMock, patch

from coreinsight_local_toolkit.desktop import _activate_existing, _port_is_open


class DesktopTests(unittest.TestCase):
    def test_detects_occupied_port(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        try:
            self.assertTrue(_port_is_open(listener.getsockname()[1]))
        finally:
            listener.close()

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


if __name__ == "__main__":
    unittest.main()
