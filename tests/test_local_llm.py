"""單元測試與本機模型端對端驗收測試。"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import load_model_profile
from src.local_llm_client import LocalLLMClient, LocalLLMConnectionError
from src.task_runner import load_tasks, run_task_file


def extract_python_code(text: str) -> str:
    """從模型回覆中擷取第一個 ```python ... ``` 程式碼區塊。"""
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return re.sub(r"^```(?:python)?\s*\n?|\s*```$", "", text.strip(), flags=re.IGNORECASE).strip()


def extract_json_object(text: str) -> dict:
    """從模型回覆中擷取 JSON 物件（容許外層 code fence）。"""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    return json.loads(cleaned)


class TestConfigAndClientUnit(unittest.TestCase):
    """離線單元測試：驗證模型切換機制與防禦性錯誤處理。"""

    def test_load_default_profile(self) -> None:
        profile = load_model_profile()
        self.assertEqual(profile.name, "inkling-2-mini-q8")
        self.assertEqual(profile.model, "inkling-2-mini-q8")
        self.assertIn("127.0.0.1:8080", profile.base_url)

    def test_switch_profile_and_env_override(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "LOCAL_LLM_BASE_URL": "http://127.0.0.1:9999/v1",
                "LOCAL_LLM_MODEL": "custom-test-model",
                "LOCAL_LLM_REASONING_EFFORT": "high",
            },
            clear=False,
        ):
            profile = load_model_profile("ollama-local")
            self.assertEqual(profile.base_url, "http://127.0.0.1:9999/v1")
            self.assertEqual(profile.model, "custom-test-model")
            self.assertEqual(profile.default_reasoning_effort, "high")

    def test_invalid_reasoning_effort_raises(self) -> None:
        profile = load_model_profile()
        client = LocalLLMClient(profile)
        with self.assertRaises(ValueError):
            client.build_chat_payload(
                [{"role": "user", "content": "hi"}],
                reasoning_effort="ultra_invalid",
            )

    def test_unreachable_server_raises_connection_error(self) -> None:
        profile = load_model_profile(base_url_override="http://127.0.0.1:1")
        client = LocalLLMClient(profile)
        with self.assertRaises(LocalLLMConnectionError):
            client.check_health(timeout=1)

    def test_load_demo_tasks(self) -> None:
        tasks = load_tasks(PROJECT_ROOT / "tasks" / "demo_tasks.json")
        self.assertGreaterEqual(len(tasks), 2)


class TestLocalLLMIntegration(unittest.TestCase):
    """本機端對端實測：實際派發示範任務給地端模型並驗收產出。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = load_model_profile()
        cls.client = LocalLLMClient(cls.profile)
        try:
            cls.client.check_health(timeout=3)
            cls.server_online = True
        except LocalLLMConnectionError:
            cls.server_online = False
            if os.environ.get("REQUIRE_LOCAL_LLM") == "1":
                raise

    def test_end_to_end_demo_tasks(self) -> None:
        if not self.server_online:
            self.skipTest("本機 llama-server 未啟動，略過端對端測試")

        with tempfile.TemporaryDirectory() as tmpdir:
            report = run_task_file(
                PROJECT_ROOT / "tasks" / "demo_tasks.json",
                output_dir=tmpdir,
            )

        by_id = {item["id"]: item for item in report["results"]}
        self.assertEqual(
            by_id["code_markdown_table_parser"]["status"],
            "ok",
            msg=by_id["code_markdown_table_parser"].get("error"),
        )
        self.assertEqual(
            by_id["structured_incident_summary"]["status"],
            "ok",
            msg=by_id["structured_incident_summary"].get("error"),
        )

        # 驗收任務 1：實際執行地端模型生成的 Python 函式
        code = extract_python_code(by_id["code_markdown_table_parser"]["content"])
        namespace: dict = {}
        exec(code, namespace)  # noqa: S102 - 沙盒驗收本機示範函式
        self.assertIn("parse_markdown_table", namespace)

        parse_fn = namespace["parse_markdown_table"]
        sample_md = (
            "說明文字\n\n"
            "| 欄位 | 數值 |\n"
            "| --- | --- |\n"
            "| GPU | RTX Spark |\n"
            "| Layers | 49/49 |\n"
        )
        parsed = parse_fn(sample_md)
        self.assertEqual(
            parsed,
            [
                {"欄位": "GPU", "數值": "RTX Spark"},
                {"欄位": "Layers", "數值": "49/49"},
            ],
        )
        self.assertEqual(parse_fn("沒有表格的文字"), [])

        # 驗收任務 2：檢查地端模型生成的結構化 JSON
        summary_obj = extract_json_object(by_id["structured_incident_summary"]["content"])
        self.assertIn("summary", summary_obj)
        self.assertIn("root_cause", summary_obj)
        self.assertIsInstance(summary_obj.get("action_items"), list)
        self.assertGreaterEqual(len(summary_obj["action_items"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
