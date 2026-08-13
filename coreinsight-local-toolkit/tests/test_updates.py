import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from coreinsight_local_toolkit.config import Settings
from coreinsight_local_toolkit.updates import check_for_update


class UpdateTests(unittest.TestCase):
    def settings(self, url=""):
        return Settings(data_dir=Path("D:/CoreInsight/LocalToolkit"),
                        update_config_url=url,
                        update_config_key="coreinsight_local_toolkit_release")

    def test_unconfigured_update_check(self):
        status = check_for_update(self.settings())
        self.assertFalse(status.configured)
        self.assertFalse(status.updateAvailable)

    def test_new_version_requires_https_and_sha256(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"data": {"configVal": json.dumps({
            "enabled": True,
            "latestVersion": "9.0.0",
            "minimumSupportedVersion": "0.1.0",
            "forceUpdate": False,
            "downloadUrl": "https://downloads.example/toolkit.exe",
            "sha256": "a" * 64,
            "releaseNotes": ["更新说明"],
        })}}
        session = Mock()
        session.get.return_value = response
        with patch("coreinsight_local_toolkit.updates.requests.Session",
                   return_value=session):
            status = check_for_update(self.settings("https://updates.example/manifest.json"))
        self.assertTrue(status.configured)
        self.assertTrue(status.updateAvailable)
        self.assertEqual("a" * 64, status.sha256)
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
            "sha256": "b" * 64,
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


if __name__ == "__main__":
    unittest.main()
