import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from coreinsight_local_toolkit.config import Settings
from coreinsight_local_toolkit.updates import (
    UpdateManager, UpdateStatus, check_for_update, create_updater_script,
    download_update,
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
        session = MagicMock()
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

    def test_download_verifies_sha256_and_exe_signature(self):
        content = b"MZ" + b"new executable"
        status = UpdateStatus(
            currentVersion="0.2.0", latestVersion="9.0.0",
            updateAvailable=True, downloadUrl="https://downloads.example/toolkit.exe",
            sha256=hashlib.sha256(content).hexdigest())
        response = Mock()
        response.headers = {"Content-Length": str(len(content))}
        response.iter_content.return_value = [content[:4], content[4:]]
        response.raise_for_status.return_value = None
        session = MagicMock()
        session.get.return_value.__enter__.return_value = response
        progress = []
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=Path(directory))
            path = download_update(settings, status, progress.append, session)
            self.assertEqual(content, path.read_bytes())
            self.assertEqual(100, progress[-1])
            self.assertFalse(path.with_suffix(".exe.part").exists())
        session.get.assert_called_once_with(
            status.downloadUrl, stream=True, timeout=(10, 300), verify=False)

    def test_download_removes_partial_file_after_hash_failure(self):
        status = UpdateStatus(
            currentVersion="0.2.0", latestVersion="9.0.0",
            updateAvailable=True, downloadUrl="https://downloads.example/toolkit.exe",
            sha256="0" * 64)
        response = Mock()
        response.headers = {}
        response.iter_content.return_value = [b"MZbad"]
        session = MagicMock()
        session.get.return_value.__enter__.return_value = response
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(data_dir=Path(directory))
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                download_update(settings, status, session=session)
            self.assertFalse(any((Path(directory) / "updates").glob("*.part")))

    def test_updater_script_waits_replaces_and_restarts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(data_dir=root)
            package = root / "updates" / "new.exe"
            package.parent.mkdir()
            package.write_bytes(b"MZ")
            target = root / "installed" / "toolkit.exe"
            script = create_updater_script(
                settings, package, target, process_ids=(123, 456))
            text = script.read_text(encoding="utf-8-sig")
            self.assertIn('PID eq 123', text)
            self.assertIn('PID eq 456', text)
            self.assertIn(f'set "SOURCE={package.resolve()}"', text)
            self.assertIn('installed\\toolkit.exe"', text)
            self.assertIn('start "" "%TARGET%"', text)

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
