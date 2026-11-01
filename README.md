# 中興 AI 租屋資訊助手：資料處理與儲存模組

**交接請先看 [FRONTEND_QUICKSTART.md](FRONTEND_QUICKSTART.md)**：照著複製指令，即可完成放入新 JSON、預覽、修改、確認存檔、讀取及下載。前端可直接複製 `examples/frontend-api.mjs` 使用。

目前完成的資料流程：**複製網頁全文 → 使用 Blue 的 Prompt 整理 → JSON → 預覽與修改草稿 → 確認匯入 SQLite → 前端讀取篩選／比較 → 匯出交接**。本模組提供後端與交接契約，可編輯表單與比較畫面由前端同學製作。

這個模組從 Blue 已產生的 JSON 開始接手；原文透過 `metadata` 逐筆對應。沒有 API 金鑰也能完整操作。AI 整理階段使用 Blue 的既有 Prompt，請手動將輸出貼入 API；不包含即時 AI 呼叫、爬蟲或正式前端。

## Windows 安裝與啟動

需要 Python 3.10 以上。下載或 clone 專案後，在專案資料夾開啟 PowerShell，再執行以下指令。不需要啟用虛擬環境，因此不受 Activate.ps1 執行原則影響。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn housing.api:app --host 127.0.0.1 --port 8000
```

啟動後開啟 [API 操作介面](http://127.0.0.1:8000/docs)，可直接呼叫各 endpoint。完整請求型別與回應範例見 [FRONTEND_HANDOFF.md](FRONTEND_HANDOFF.md)；Swagger 的通用 body 欄位請貼入該文件的完整請求。

只有執行需求時可安裝 `requirements.txt`。測試、HTTP 示範及文件範例產生器需要 `requirements-dev.txt`。

## 實際操作與交給同學

1. 將同一則刊登的整頁文字複製到 Blue 的既有 Prompt，產生 JSON；不要把不同房源的原文混在同一筆 `raw_text`。
2. 把 AI JSON 當成 `json_text` 字串，另附與房源等長的 `metadata` 陣列，呼叫 `POST /imports/preview`。如果整頁包含多個房型，請逐筆提供對應文字，或保留空字串並呈現缺原文提示。
3. 檢視 warnings、對照原文，讓使用者先修改表單。修正值放在逐筆 `edits`，保留原始 `json_text`，可再次預覽。存在 errors 時不可匯入。使用者按「確認並儲存」才呼叫 `POST /imports/commit`，附上這次操作固定的 `request_id`；明確核對可在 edits 中指定 reviewed=true。
4. 儲存後以 `PATCH /properties/{id}` 保存人工修改。再透過獨立的 `{"reviewed":true}` 操作標記已核對。
5. 前端隊友可直接使用 HTTP API、Python `HousingService`，或接收匯出的 UTF-8 JSON 檔。並排比較由前端勾選資料實作。

若還沒有前端，可直接用檔案匯入。以下先預覽虛構資料，檢視終端機的 errors／warnings 後，第二個指令才確認寫入：

```powershell
.\.venv\Scripts\python.exe -m scripts.import_json --json-file examples\demo_blue.json --metadata-file examples\demo_metadata.json
.\.venv\Scripts\python.exe -m scripts.import_json --json-file examples\demo_blue.json --metadata-file examples\demo_metadata.json --commit --request-id class-demo-001
```

換成自己的 Blue JSON 檔即可操作。單筆房源可用 `--raw-text-file 原文.txt` 保存複製的網頁全文；多筆請用 `--metadata-file` 提供逐筆對應。兩者不可同時提供。檔案接受 UTF-8（含 BOM），沒有原文也可匯入，但會提示缺少依據。

若在匯入前修正欄位，保留原 AI JSON 檔，另建立 `edits.json`（例如 `[{"fields":{"租金":"月租8500元"},"reviewed":true}]`，每筆對應一列），再加上 `--edits-file edits.json` 預覽／確認匯入。這樣資料庫可以同時保留 AI 原始值與使用者修正值。實際前端以相同 edits 契約實作可編輯表單。

匯出全部目前資料（包含尚未核對者，保留 `reviewed`）：

```powershell
.\.venv\Scripts\python.exe -m scripts.export_data --output exports\housing-export.json
```

只匯出明確核對的資料：

```powershell
.\.venv\Scripts\python.exe -m scripts.export_data --reviewed-only --output exports\reviewed.json
```

亦可下載 [JSON 匯出 API](http://127.0.0.1:8000/properties/export)；僅核對者為 `/properties/export?reviewed_only=true`。匯出是給前端使用的內部結構快照，不是 Blue 原始輸入格式；不可直接回灌 Blue 匯入 API。

## 測試與最小串接示範

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# 不需啟動伺服器，以獨立暫存 SQLite 跑完整 Python 流程
.\.venv\Scripts\python.exe -m scripts.demo
# 另開一個 PowerShell，伺服器啟動後跑真正 HTTP 流程
.\.venv\Scripts\python.exe -m scripts.demo --base-url http://127.0.0.1:8000
# 自動啟停暫存 Uvicorn，完整驗證 TCP HTTP 與匯出，不需先啟動伺服器
.\.venv\Scripts\python.exe -m scripts.smoke_http
```

HTTP 示範每次會新增兩筆明確標示的虛構房源；若要隔離正式課程資料，請用以下自訂資料庫啟動後再執行示範。Python 示範與 pytest 都使用獨立暫存資料庫。

## 資料庫與 CORS

預設位置為啟動工作目錄下的 `data\housing.sqlite3`，啟動及服務建立時自動初始化；重複初始化不清空資料。使用短 SQLite 連線、5 秒忙碌等待、交易及匯入識別碼避免同一請求重複新增。可複製 SQLite 檔交接保存；請先停止寫入再備份。

```powershell
# 請在啟動伺服器前設定；可改成絕對路徑
$env:HOUSING_DB_PATH = "data\demo.sqlite3"
# 以逗號分隔實際前端 origins，沒有固定前端連接埠；預設不允許跨來源
$env:HOUSING_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:8080"
.\.venv\Scripts\python.exe -m uvicorn housing.api:app --host 127.0.0.1 --port 8000
```

同源不需 CORS。跨來源請精確填入協定、主機、連接埠，`localhost` 與 `127.0.0.1` 是不同 origin。課程版本以本機操作為範圍，無登入功能。

## 檔案分工

| 路徑 | 用途 |
|---|---|
| `housing/adapter.py` | JSON 語法、外層結構、逐筆 metadata 適配與預覽 |
| `housing/domain.py` | 18 欄正規化、月租解析、警告 |
| `housing/storage.py` | SQLite schema、連線、交易與讀寫 |
| `housing/service.py` | Python 與 HTTP 共用的匯入、讀取、更新、篩選與匯出 |
| `housing/api.py` | FastAPI、錯誤格式、CORS、HTTP 輸入大小限制 |
| `examples/demo_blue.json`、`demo_metadata.json` | 完全虛構的操作示範，不含真實聯絡人或電話 |
| `tests/fixtures/claude_from_pdf.json` | 使用者提供之 Claude 附件的格式相容性測試資料，非虛構示範 |
| `scripts/demo.py` | 完整 Python／HTTP 串接示範 |
| `scripts/import_json.py` | 讀取 Blue JSON 檔，先預覽再透過明確旗標確認匯入 |
| `scripts/export_data.py` | 匯出 UTF-8 JSON 給最後一位同學 |
| `scripts/smoke_http.py` | 自動啟停伺服器並實際驗證 TCP HTTP 及兩種匯出 |
| `examples/demo_export.json` | 真實 HTTP 示範產生的虛構資料快照，可直接交給前端試讀 |
| `FRONTEND_HANDOFF.md` | 前端契約、完整 API 範例及 fetch／Python 程式 |
| `DEVELOPMENT_LOG.md` | 實際開發與驗證紀錄、未驗證事項 |

## 限制與 Blue 待確認事項

一批 1–100 筆，`json_text` 最多 1,048,576 字元，每筆原文及每個欄位文字最多 20,000 字元，metadata 網址最多 2,048 字元。HTTP body 最多 2,097,152 bytes（包含 UTF-8 中文與 JSON 跳脫）。月租最大 1,000,000,000，全部列表在記憶體篩選，適合短期課程資料量。

已檢查兩份 PDF；新提供的 Claude 版本是 5 筆陣列，每筆完整 18 欄且值均為字串。測試 fixture 是從 PDF 右欄重建，清除 PDF 字形拆分與排版換行，並目視核對三頁，不等同原始 JSON 的逐位元組檔案。未取得原始 JSON 檔及對應原始網頁全文，也未連線查核房源內容或出租現況。

請 Blue 確認後續是否持續輸出這 18 個欄名、純數字視為月租的約定、設備是否可能改成陣列，以及正式外層包裝鍵。現在明確允許 `properties`、`data`、`results`；附件 GPT 欄的「房源」不在允許清單，Claude 不需要它。若未來要支援，需明確加鍵並保留歧義檢查，不能猜測解包。

附件中的 Prompt、歷史規劃、爬蟲與通知需求僅作背景，沒有作為本次新功能指令。此版本不會自動判定 AI 內容正確，也不會因網址相同而合併房源。
