import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from coreinsight_local_toolkit.config import Settings
from coreinsight_local_toolkit.updates import (
    UpdateManager, UpdateStatus, check_for_update,
)


class UpdateTests(unittest.TestCase):
    def settings(self, url=""):
        return Settings(data_dir=Path("D:/CoreInsight/LocalToolkit"),
                        update_config_url=url,
                        update_config_key="coreinsight_local_toolkit_release")

    def test_unconfigured_update_check(self):
        status = check_for_update(self.settings())
        self.assertFalse(status.configured)
        self.assertFalse(status.updateAvailable)

    def test_update_can_be_disabled_explicitly(self):
        settings = Settings(
            data_dir=Path("D:/CoreInsight/LocalToolkit"),
            update_enabled=False,
            update_config_url="https://updates.example/config")
        status = check_for_update(settings)
        self.assertFalse(status.configured)

    def test_new_version_requires_https_download_page(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": {"configVal": json.dumps({
            "enabled": True,
            "latestVersion": "9.0.0",
            "minimumSupportedVersion": "0.1.0",
            "forceUpdate": False,
            "downloadUrl": "https://downloads.example/toolkit.exe",
            "releaseNotes": ["更新说明"],
        })}}
        session = MagicMock()
        session.get.return_value = response
        with patch("coreinsight_local_toolkit.updates.requests.Session",
                   return_value=session):
            status = check_for_update(self.settings("https://updates.example/manifest.json"))
        self.assertTrue(status.configured)
        self.assertTrue(status.updateAvailable)
        self.assertFalse(status.forceUpdate)
        session.get.assert_called_once_with(
            "https://updates.example/manifest.json",
            params={"key": "coreinsight_local_toolkit_release"},
            timeout=10, verify=False)

    def test_minimum_supported_version_forces_update(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": {"configVal": json.dumps({
            "latestVersion": "9.0.0",
            "minimumSupportedVersion": "8.0.0",
            "downloadUrl": "https://downloads.example/toolkit.exe",
            "releaseNotes": "必须升级",
        })}}
        session = Mock(); session.get.return_value = response
        with patch("coreinsight_local_toolkit.updates.requests.Session",
                   return_value=session):
            status = check_for_update(self.settings("https://updates.example/config"))
        self.assertTrue(status.forceUpdate)

    def test_http_manifest_is_rejected(self):
        with self.assertRaises(ValueError):
            check_for_update(self.settings("http://updates.example/manifest.json"))

    def test_install_request_delegates_to_browser_opener(self):
        manager = UpdateManager(self.settings())
        manager._status = UpdateStatus(
            currentVersion="0.2.0", latestVersion="9.0.0",
            updateAvailable=True,
            downloadUrl="https://downloads.example/toolkit")
        opened = []
        manager.set_installer(lambda status: opened.append(status.downloadUrl))

        manager.request_install()

        self.assertEqual(["https://downloads.example/toolkit"], opened)

    @patch("coreinsight_local_toolkit.updates.check_for_update")
    def test_manager_exposes_forced_update_state(self, check):
        check.return_value = UpdateStatus(
            currentVersion="0.2.0", latestVersion="9.0.0",
            updateAvailable=True, forceUpdate=True)
        manager = UpdateManager(self.settings())
        manager.check()
        self.assertTrue(manager.forced)
        self.assertEqual("available", manager.snapshot()["phase"])



if __name__ == "__main__":
    unittest.main()
