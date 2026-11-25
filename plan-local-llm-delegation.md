# 計畫：雲端規劃 + 地端模型執行工具組（local-llm-delegation）

> 狀態：已實作完成（已依實作更新架構圖與流程圖並標註偏差）

## 1. 目標與範圍
- **做什麼**：
  - 建立一套「雲端模型（Gemini 4 Neon）規劃規格 → Python 腳本呼叫本機 OpenAI 相容 API 執行 → 自動化測試驗收」的工作流專案。
  - 透過設定檔（`config/models.json`）、環境變數與 CLI 參數，讓地端模型與引擎（`llama.cpp` / Ollama / vLLM / LM Studio）可以免改程式碼直接抽換。
  - 提供離線單元測試與本機 Inkling-2-Mini 端對端實測。
- **明確不做什麼**：
  - 不自動啟動或管理 `llama-server` 行程。
  - 不納入任何 GGUF 模型權重檔或個人 API 金鑰。
  - 暫不實作多執行緒併發派發，先以循序執行確保單張 GPU 穩定性。

## 2. 架構圖（已更新為實際實作版本）

```text
+---------------------+      task spec (JSON)      +------------------------+
| Planner (Neon)      | -------------------------> | task_runner.py         |
| design & review     |                            | load / dispatch / save |
+---------------------+                            +-----------+------------+
                                                               |
+---------------------+      profile & override                |
| config/models.json  | ---> config_loader.py -----------------+
+---------------------+                                        v
                                                   +-----------+------------+
+---------------------+      content & metrics     | local_llm_client.py    |
| outputs/ & tests/   | <------------------------- | HTTP POST + validation |
| reports & unittest  |                            +-----------+------------+
+---------------------+                                        |
                                           OpenAI-compat API   v
                                                   +-----------+------------+
                                                   | Local LLM Server (Ext) |
                                                   | llama.cpp / Ollama /.. |
                                                   +------------------------+
```

## 3. 流程圖（已更新為實際實作版本）

```text
 1. 載入模型設定與覆寫          --> load_model_profile()  config_loader.py
 2. 檢查本機服務健康狀態        --> check_health()        local_llm_client.py
    2a. [例外] 服務未啟動       --> LocalLLMConnectionError local_llm_client.py
 3. 讀取任務規格檔              --> load_tasks()          task_runner.py
 4. 逐筆呼叫地端模型執行        --> chat_complete()       local_llm_client.py
    4a. [例外] 逾時或非 200     --> 記錄 error 繼續下一筆 task_runner.py
 5. 儲存產出與速度指標          --> run_task_file()       task_runner.py
 6. 執行單元與端對端測試驗收    --> unittest suite        test_local_llm.py
```
未涵蓋或不確定之處：尚未實作多執行緒批次併發與自動重試（retry）機制。

## 4. 與初版計畫的偏差對照
- **新增模組**：依使用者「希望未來容易更換地端模型」需求，新增 `config/models.json` 與 `src/config_loader.py`，提供三層設定覆寫（CLI > 環境變數 > JSON profile）。
- **逾時與輸出上限調整**：將預設 `timeout_sec` 由 120 秒提高至 300 秒，避免本機思考型模型在高負載或長思考時提前逾時；示範任務設定 `max_tokens: 2048` 與 `reasoning_effort: minimal`（因 `reasoning_content` 與 `content` 共用 `max_tokens`，設太小會截斷程式碼輸出）。

## 5. 關鍵設計決策
- **零外部套件相依**：僅使用 Python 標準庫（`urllib.request` / `json` / `unittest`），免 `pip install`。
- **健康檢查自動相容**：`check_health()` 先檢查 `health_url`（如 `llama-server` 的 `/health`），失敗時自動退回標準 OpenAI `/v1/models`，確保切換至 Ollama 或其他引擎時同樣運作。
