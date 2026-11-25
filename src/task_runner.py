"""任務派發器：讀取 JSON 任務規格，逐筆交給地端模型執行並保存報表。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config_loader import DEFAULT_CONFIG_PATH, load_model_profile
from src.local_llm_client import LocalLLMClient, LocalLLMError


def load_tasks(task_file: Path | str) -> list[dict[str, Any]]:
    """讀取並驗證任務規格 JSON。"""
    path = Path(task_file)
    if not path.is_file():
        raise FileNotFoundError(f"找不到任務檔：{path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = data.get("tasks") if isinstance(data, dict) else data
    if not isinstance(tasks, list) or not tasks:
        raise ValueError(f"任務檔 {path} 必須包含非空的 tasks 陣列")

    for idx, task in enumerate(tasks):
        if not isinstance(task, dict) or not task.get("id") or not task.get("prompt"):
            raise ValueError(f"第 {idx + 1} 筆任務缺少必要欄位 id 或 prompt")
    return tasks


def run_task_file(
    task_file: Path | str,
    *,
    profile_name: str | None = None,
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    output_dir: Path | str = PROJECT_ROOT / "outputs",
    reasoning_effort_override: str | None = None,
    base_url_override: str | None = None,
    model_override: str | None = None,
) -> dict[str, Any]:
    """依序執行任務檔內的所有任務並輸出 JSON 報表。"""
    profile = load_model_profile(
        profile_name=profile_name,
        config_path=config_path,
        base_url_override=base_url_override,
        model_override=model_override,
        reasoning_effort_override=reasoning_effort_override,
    )
    client = LocalLLMClient(profile)
    client.check_health()

    tasks = load_tasks(task_file)
    results: list[dict[str, Any]] = []

    for task in tasks:
        messages: list[dict[str, str]] = []
        if task.get("system"):
            messages.append({"role": "system", "content": str(task["system"])})
        messages.append({"role": "user", "content": str(task["prompt"])})

        effort = reasoning_effort_override or task.get("reasoning_effort") or profile.default_reasoning_effort
        entry: dict[str, Any] = {
            "id": task["id"],
            "title": task.get("title", task["id"]),
            "reasoning_effort": effort,
        }
        try:
            resp = client.chat_complete(
                messages,
                reasoning_effort=effort,
                temperature=task.get("temperature"),
                max_tokens=task.get("max_tokens"),
            )
            entry.update(
                {
                    "status": "ok",
                    "model": resp.model,
                    "finish_reason": resp.finish_reason,
                    "elapsed_sec": resp.elapsed_sec,
                    "usage": resp.usage,
                    "timings": {
                        "prompt_per_second": resp.timings.get("prompt_per_second"),
                        "predicted_per_second": resp.timings.get("predicted_per_second"),
                    },
                    "content": resp.content,
                    "reasoning_content": resp.reasoning_content,
                }
            )
        except LocalLLMError as exc:
            entry.update({"status": "error", "error": str(exc)})

        results.append(entry)

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "profile": profile.name,
        "base_url": profile.base_url,
        "model": profile.model,
        "task_file": str(Path(task_file).name),
        "results": results,
    }

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    report_file = out_path / f"report_{Path(task_file).stem}.json"
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_file"] = str(report_file)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="將規劃好的任務派發給本機 OpenAI 相容模型執行")
    parser.add_argument(
        "--tasks",
        default=str(PROJECT_ROOT / "tasks" / "demo_tasks.json"),
        help="任務規格 JSON 路徑（預設：tasks/demo_tasks.json）",
    )
    parser.add_argument("--profile", default=None, help="config/models.json 中的模型 profile 名稱")
    parser.add_argument("--base-url", default=None, help="臨時覆寫 API base_url")
    parser.add_argument("--model", default=None, help="臨時覆寫模型名稱")
    parser.add_argument(
        "--reasoning-effort",
        default=None,
        help="臨時覆寫思考深度（none/minimal/low/medium/high/max）",
    )
    args = parser.parse_args()

    report = run_task_file(
        args.tasks,
        profile_name=args.profile,
        base_url_override=args.base_url,
        model_override=args.model,
        reasoning_effort_override=args.reasoning_effort,
    )

    print(f"Profile: {report['profile']} | Model: {report['model']} | Base URL: {report['base_url']}")
    for r in report["results"]:
        if r["status"] == "ok":
            tps = r["timings"].get("predicted_per_second")
            tps_str = f"{tps:.2f} tok/s" if isinstance(tps, (int, float)) else "N/A"
            tokens = r["usage"].get("completion_tokens", "N/A")
            print(f"  [OK] {r['id']} ({r['reasoning_effort']}) | {tokens} tokens | {tps_str} | {r['elapsed_sec']}s")
        else:
            print(f"  [ERR] {r['id']}: {r['error']}")
    print(f"報表已存至：{report['report_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
