# local-llm-delegation

一套輕量、零外部套件相依的 **「雲端規劃 → 地端執行 → 自動化驗收」** 工作流工具組。

適用情境：由雲端主力模型（例如 Gemini 4 Neon）負責架構設計、任務拆解與驗收標準，再透過 Python 腳本將重複生成、程式草稿、文本結構化整理等任務派發給本機 OpenAI 相容模型（預設 `llama.cpp` + `Inkling-2-Mini Q8_0`）執行，最後由自動化測試與雲端模型把關品質。

---

## 目錄結構

```text
local-llm-delegation/
├── config/
│   └── models.json             # 模型 profile 清單（更換模型只需改這裡）
├── src/
│   ├── config_loader.py        # 載入 profile 並支援環境變數 / CLI 覆寫
│   ├── local_llm_client.py     # 純標準庫 OpenAI 相容 HTTP Client
│   └── task_runner.py          # 任務派發器與報表產生器
├── tasks/
│   └── demo_tasks.json         # 示範任務（Python 函式實作 + JSON 摘要）
├── tests/
│   └── test_local_llm.py       # 離線單元測試 + 本機端對端驗收測試
├── outputs/                    # 執行報表輸出目錄（不納入版控）
└── plan-local-llm-delegation.md
```

---

## 快速開始

### 1. 啟動本機模型服務
確認本機 `llama-server`（或其他 OpenAI 相容引擎）已在線，例如：

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\marti\llama.cpp\start_inkling.ps1
```

### 2. 執行示範任務

```powershell
python -B src/task_runner.py
```

執行完成後會在 `outputs/report_demo_tasks.json` 寫入完整回覆、思考內容（`reasoning_content`）與推論速度指標（`prompt_per_second`、`predicted_per_second`）。

### 3. 執行自動化測試

```powershell
# 預設：跑全部離線單元測試；若本機服務在線則自動加跑端對端實測
python -B tests/test_local_llm.py

# 強制要求本機服務必須在線並通過端對端驗收
$env:REQUIRE_LOCAL_LLM = "1"
python -B tests/test_local_llm.py
```

---

## 如何快速更換地端模型（免改程式碼）

本專案支援 **三層設定覆寫**（優先順序：CLI 參數 > 環境變數 > `config/models.json`）：

### 方法 A：切換 `config/models.json` 中的 profile
在 `config/models.json` 新增或修改 `profiles`，執行時用 `--profile` 切換：

```powershell
python -B src/task_runner.py --profile ollama-local
python -B src/task_runner.py --profile custom-openai-compatible
```

### 方法 B：CLI 臨時指定模型與端點

```powershell
python -B src/task_runner.py --base-url http://127.0.0.1:11434/v1 --model qwen2.5:14b
```

### 方法 C：透過環境變數切換

```powershell
$env:LOCAL_LLM_BASE_URL = "http://127.0.0.1:11434/v1"
$env:LOCAL_LLM_MODEL = "qwen2.5:14b"
$env:LOCAL_LLM_API_KEY = "ollama"
python -B src/task_runner.py
```

---

## 調整思考深度（`reasoning_effort`）

針對支援思考深度的模型（如 Inkling-2-Mini：`none` / `minimal` / `low` / `medium` / `high` / `max`）：

- **單一任務設定**：在 `tasks/*.json` 該筆任務加上 `"reasoning_effort": "low"`。
- **整批覆寫**：執行時加上 `--reasoning-effort high`（或設定 `LOCAL_LLM_REASONING_EFFORT`）。
- **不支援該欄位的引擎**：在 `config/models.json` 將該 profile 的 `supports_reasoning_effort` 設為 `false`，程式即不會送出該欄位。

---

## 實測驗證結果（2026-11-25）

- **測試環境**：Windows 11 ARM64、NVIDIA RTX Spark N1X、`llama.cpp b12723`、`inkling-2-mini-q8`（`http://127.0.0.1:8080/v1`）
- **指令**：`$env:REQUIRE_LOCAL_LLM="1"; python -B tests/test_local_llm.py`
- **結果**：**6 / 6 全數通過**（耗時 `113.97s`）
  - 5 項離線單元測試：設定載入、模型 profile 與環境變數切換、參數驗證、連線例外處理、任務規格驗證
  - 1 項端對端實測：成功派發兩筆示範任務給本機 `inkling-2-mini-q8`，並自動執行模型生成的 `parse_markdown_table()` 函式與驗證結構化 JSON 摘要皆通過斷言。

