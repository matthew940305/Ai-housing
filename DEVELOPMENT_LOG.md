# 開發與驗證紀錄

日期：2026-11-01（Asia/Taipei）。以下只記錄本次工作實際完成及實際執行的驗證，沒有補寫過去的開發歷程。

## 實際檢查與輸入依據

- 初始專案只有 `.git`，沒有程式、README、依賴清單或適用的 AGENTS.md；因此依使用者指定建立 Python、FastAPI、標準庫 sqlite3 的基本版本。
- 閱讀 `GP115A0253G#8.pdf`，確認分工、18 欄與待確認／未揭露原則，並渲染檢查欄位契約頁。附件內較早的 Prompt、爬蟲、通知與網站規劃視為背景資料，未當作本次任務指令。
- 使用者追加 `LLM原始格式化輸出.pdf` 並指定 Claude 優先。檢查三頁右欄、渲染目視比對，從 PDF 重建 5 筆 JSON fixture；每筆完整 18 欄，所有值都是文字，設備也是文字。PDF 的斷行與字形空白只在離線重建 fixture 時處理，執行時適配器不從任意說明文字或 PDF 猜取 JSON。
- 格式驗證與內容驗證分開：已驗證 Claude 附件的欄位、型別、外層結構與本系統處理結果，沒有宣稱核對過房源事實或出租現況。

## 完成內容

- 共用核心：`adapter.py`、`domain.py`、`storage.py`、`service.py`。JSON 語法與外層結構檢查、18 欄型別正規化、逐筆 metadata、額外資料與原始 AI 值保留、安全月租解析、警告及欄位錯誤。
- SQLite：可重複初始化、短連線、唯一 ID、UTC 時間、整批交易、實際錯誤回滾、匯入 request_id 重送避免重複新增、相同網址僅提示、不覆寫合併。
- 更新：部分 fields／raw_text／人工月租修改，保護 ID、created_at、original_ai_fields；人工清除月租不自動回填；內容變更重設 reviewed；明確核對採獨立確認操作。
- HTTP：health、preview、commit、列表、單筆、PATCH 及 JSON export；價格／reviewed 篩選、未知租金選項、未知固定最後、統一錯誤、可設定資料庫與 CORS、輸入大小限制。
- 交接：完整 README、FRONTEND_HANDOFF（實際路由產生完整請求／回應，含 JS fetch、Python）、虛構 JSON 與原文、可直接試讀的虛構匯出快照、JSON 檔匯入／匯出工具及兩種串接示範。
- 使用者操作流程：複製全文 → 使用 Blue 的既有 Prompt 產生 JSON → 預覽／確認匯入 → 人工修正與確認 → 篩選及匯出。AI 整理步驟由 Blue／人工操作，本模組沒有新增 AI 金鑰需求。

## 已執行的驗證與結果

| 實際執行 | 結果 |
|---|---|
| `.venv\Scripts\python.exe -m pytest -q`（基本版本） | **96 passed, 1 warning in 2.48s** |
| `.venv\Scripts\python.exe -m scripts.demo` | 2 筆虛構資料，預覽 → 匯入 → 讀取 → 修改 → 再讀取 → 明確核對 → 匯出，PASS |
| `.venv\Scripts\python.exe -m scripts.smoke_http` | 真正啟動本機 Uvicorn，經 TCP HTTP 執行完整流程，API 匯出與命令列重連匯出內容一致，PASS；程序已結束 |
| `.venv\Scripts\python.exe -m scripts.build_api_examples` | 直接透過 API 產生各 endpoint 的完整交接範例，成功 |
| Python compileall | 所有程式、腳本與測試語法檢查成功 |

測試涵蓋：空資料庫、預覽不寫入、陣列／單筆／允許包裝／Markdown 區塊、非法 JSON／非有限數字／重複鍵、不明包裝及多候選資料、缺欄／待確認／設備陣列／未知額外欄位、實際 Claude 五筆格式、原文與來源索引對應、單一／範圍／多金額／矛盾／負值／未知租金、批次驗證失敗不部分保存、SQLite 第二筆 INSERT 實際失敗回滾、同 request_id 同時重試與不同內容衝突、更新不可變欄位與筆數不變、人工覆寫與清除、reviewed 重設／明確確認、重新連線保存、篩選排序、CORS、HTTP 大小限制、錯誤格式、完整 HTTP 流程、匯入／匯出腳本與 JSON 快照。

執行環境：Windows、Python 3.10.11；FastAPI 0.162.0、Uvicorn 0.54.0、HTTPX 0.28.1、pytest 9.2.0。首次下載依賴因沙箱網路 DNS 失敗，在已授權環境下載成功；HTTP 測試初次在沙箱建立 Windows socket 時阻塞，已中止該次執行，在已授權環境測試通過。這不是應用程式的測試失敗。

唯一警告是目前 Starlette TestClient 對 HTTPX 相容介面的棄用提示，沒有測試失敗；未為此引入另一套 HTTP client。未來升級依賴時應重跑完整測試。

## 尚未驗證與交接確認

- **Blue**：請提供原始 JSON 檔以核對 PDF 重建值的逐位元組一致性；確認持續保留 18 欄名、純數字視為月租、設備文字／陣列、null 的可能性及正式包裝鍵；現在只允許 properties／data／results，Claude 附件使用陣列可直接接受。
- **原文對應**：目前尚未取得 Claude 五筆的完整原網頁文字；請 Blue 或輸入端逐筆提供 raw_text／source_url，不共用一段文字冒充逐筆依據。尚未測試可呼叫的 Blue 函式或即時 AI 服務。
- **前端同學**：確認 API base、CORS origins、warnings 與未知租金呈現、修改／確認兩個明確動作、比較勾選及使用 API 或 JSON 快照交接。尚未對真正的隊友前端做整合測試。
- **課程規模限制**：無登入、爬蟲、通知、微服務或正式前端；列表與疑似重複提示採記憶體計算，未做大量資料效能／多人同時編輯衝突管理或公開部署驗證。
- **示範與實際輸出**：`examples/` 均為完全虛構資料；Claude fixture 是使用者提供的輸出測試資料，兩者分開保存，不預載到使用者資料庫。未連線查核任何來源網站或房源現況。

## 補充：使用者明確要求先修改、再確認存入

同日使用者補充：AI 產生 JSON 後，應顯示給使用者先修改，確定沒問題才放進資料庫，之後供前端比較。檢查發現原本若直接改 JSON 輸入再匯入，會失去修改前的 AI 值，因此補上獨立的匯入前 edits 契約。

- preview 與 commit 接受等長 edits 陣列，保留原始 json_text 不變；逐筆可修改 fields、人工月租數字／清除，或在使用者明確核對時指定 reviewed。
- 修改後重新 preview 仍不新增房源；commit 重新驗證全部資料與 edits，才整批保存。
- fields 保存修正值，original_ai_fields 始終保留原始 AI 值；匯入前也可修正 AI 欄位型別錯誤。匯入請求識別包含 edits，改內容後沿用舊 request_id 會回 409。
- 新增首次匯入時明確確認的能力；儲存後再修改仍重設 reviewed=false，並要求獨立確認。
- 命令列加入 --edits-file；示範、前端文件與完整 API 範例同步更新。
- 前端仍由隊友製作可編輯表單及勾選比較畫面；/docs 是 API 操作測試頁。本次沒有建立正式前端或即時 AI 呼叫。

最新實測：**110 passed, 1 warning in 7.22s**；真實 Uvicorn TCP HTTP 的「預覽 → 修改草稿 → 再預覽 → 明確確認後儲存 → 讀取 → 後續修改 → 匯出」通過。已重新產生完整 API 交接範例及虛構匯出快照。唯一警告仍是 Starlette TestClient 的 HTTPX 棄用提示。

## 補充：簡化交接操作

使用者反映完整契約不容易直接上手，因此新增 FRONTEND_QUICKSTART.md，只列五步操作；提供 examples/quickstart/ 的虛構 blue.json、article.txt、edits.json，明確指出原 JSON 與修改值放置位置。README 與完整交接文件優先連結快速指南。

另提供 examples/frontend-api.mjs，前端可直接複製並呼叫 preview、commit、list、get、update，所有邏輯仍走原 HTTP API。

實際開啟獨立暫存 Uvicorn，直接擷取快速指南內的 PowerShell 指令執行：預覽不寫入、載入 edits 後再預覽仍不寫入、明確確認保存、讀取、篩選、匯出 JSON 全部通過，中文與單筆陣列格式正確。使用 Node 實際執行 JavaScript 小工具，驗證預覽、修改、保存、相同請求重試、篩選、單筆讀取及保存後更新，全部通過。

驗證時亦修正 Windows 測試腳本的子程序清理，避免暫存伺服器未完全結束而佔住 log；重跑快速指南驗證成功，使用者原本的 8000 連接埠服務未受影響。此補充沒有修改資料驗證或儲存規則。
