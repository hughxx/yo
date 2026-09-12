import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from coreinsight_local_toolkit.config import Settings
from coreinsight_local_toolkit.instruction_files import InstructionFiles
from coreinsight_local_toolkit.model_resources import ModelResourceRunner


class FakeStdin:
    def __init__(self):
        self.value = ""
        self.closed = False

    def write(self, value):
        self.value += value

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, lines):
        self.stdin = FakeStdin()
        self.stdout = iter(lines)
        self.returncode = None
        self.pid = 12345

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


class ModelResourceTests(unittest.TestCase):
    def test_prompt_resource_calls_chat_completions(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{"message": {"content": '[{"operation":"create"}]'}}]
        }
        with tempfile.TemporaryDirectory() as directory:
            runner = ModelResourceRunner(Settings(
                data_dir=Path(directory), llm_base_url="https://model.test/v1",
                llm_api_key="key", llm_model_id="model"))
            with patch("coreinsight_local_toolkit.model_resources.requests.post",
                       return_value=response) as post:
                output = runner.generate("prompt", "提取", Path(directory))
        self.assertEqual('[{"operation":"create"}]', output)
        self.assertEqual("https://model.test/v1/chat/completions",
                         post.call_args.args[0])
        self.assertEqual("提取", post.call_args.kwargs["json"]["messages"][0]["content"])

    def test_skill_resource_uses_stdin_and_result_event(self):
        process = FakeProcess([
            json.dumps({"type": "session", "session_id": "session-1"}) + "\n",
            json.dumps({"type": "assistant", "message": {
                "content": [{"type": "text", "text": "working"}]}}) + "\n",
            json.dumps({"type": "result", "result": "final"}) + "\n",
        ])
        with tempfile.TemporaryDirectory() as directory:
            runner = ModelResourceRunner(Settings(data_dir=Path(directory)))
            with patch("coreinsight_local_toolkit.model_resources.subprocess.Popen",
                       return_value=process) as popen, patch(
                       "coreinsight_local_toolkit.model_resources.subprocess.run"), patch(
                       "coreinsight_local_toolkit.model_resources.shutil.which",
                       return_value="C:\\Tools\\codeagent.exe"):
                output = runner.generate("skill", "多行\n提取任务", Path(directory))
        self.assertEqual("final", output)
        self.assertEqual("多行\n提取任务", process.stdin.value)
        self.assertTrue(process.stdin.closed)
        command = popen.call_args.args[0]
        self.assertEqual("C:\\Tools\\codeagent.exe", command[0])
        self.assertNotIn("多行\n提取任务", command)
        self.assertIn("stream-json", command)

    def test_windows_npm_command_wrapper_uses_cmd_without_prompt_argument(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = ModelResourceRunner(Settings(data_dir=Path(directory)))
            with patch(
                    "coreinsight_local_toolkit.model_resources.shutil.which",
                    return_value="C:\\Users\\User Name\\npm\\codeagent.cmd"), patch.dict(
                    "coreinsight_local_toolkit.model_resources.os.environ",
                    {"COMSPEC": "C:\\Windows\\System32\\cmd.exe"}):
                command = runner._resolve_codeagent_command(
                    ["--print", "--output-format", "stream-json"],
                    windows=True)

        self.assertEqual("C:\\Windows\\System32\\cmd.exe", command[0])
        self.assertEqual(["/d", "/s", "/c"], command[1:4])
        self.assertIn('"C:\\Users\\User Name\\npm\\codeagent.cmd"', command[4])
        self.assertIn("--output-format stream-json", command[4])

    def test_instruction_files_keep_manual_edits_and_read_latest_content(self):
        with tempfile.TemporaryDirectory() as directory:
            files = InstructionFiles(Path(directory))
            files.prompt_path.write_text("用户最新 Prompt", encoding="utf-8")
            files.skill_path.write_text("# 用户最新 Skill", encoding="utf-8")
            self.assertEqual("用户最新 Prompt", files.read_prompt())
            skill, digest = files.read_skill()
            self.assertEqual("# 用户最新 Skill", skill)
            self.assertEqual(
                hashlib.sha256(files.skill_path.read_bytes()).hexdigest(), digest)
            InstructionFiles(Path(directory))
            self.assertEqual("用户最新 Prompt", files.read_prompt())


if __name__ == "__main__":
    unittest.main()
