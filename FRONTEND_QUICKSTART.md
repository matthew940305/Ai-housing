# 給前端同學：照這份操作即可

先照五步完成：**啟動 → 放入 JSON → 修改及預覽 → 確認存檔 → 讀取列表**。本文件提供可直接複製的指令；詳細型別有需要再看 FRONTEND_HANDOFF.md。

## 1. 啟動後端

在專案資料夾開 PowerShell，執行下面這行並保持視窗開著：

```powershell
.\.venv\Scripts\python.exe -m uvicorn housing.api:app --host 127.0.0.1 --port 8000
```

換到同學電腦時，先在專案資料夾執行一次 `python -m venv .venv` 和 `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`。

以下指令在**第二個 PowerShell 視窗**執行，同樣先進入專案資料夾。

## 2. 新 JSON 放哪裡？怎麼預覽？

把 AI 產生的完整 JSON 貼進 `examples\quickstart\blue.json`；原始租屋文章貼進同資料夾的 `article.txt`。這兩個檔案已放好一筆完全虛構的資料，可先直接測試。

```powershell
$api = "http://127.0.0.1:8000"
$request = @{
    json_text = Get-Content -Raw -Encoding UTF8 .\examples\quickstart\blue.json
    metadata = @(@{ raw_text = Get-Content -Raw -Encoding UTF8 .\examples\quickstart\article.txt })
}
$preview = Invoke-RestMethod -Method Post -Uri "$api/imports/preview" -ContentType "application/json; charset=utf-8" -Body ($request | ConvertTo-Json -Depth 30)
$preview.items[0].property.fields
```

**這時沒有存進資料庫。** `items[0].property.fields` 就是第一筆要顯示給使用者看的欄位。`items[0].warnings` 是提醒，`items[0].errors` 是必須修正的錯誤。`$preview.can_commit` 為 true 才可以存檔。

## 3. 使用者怎麼先修改？

保留 blue.json，將使用者修正值放進 `examples\quickstart\edits.json`。例如範例是選擇大房，將月租確認為 8500：

```json
[
  {
    "fields": {"租金": "月租8500元", "房型": "大套房"},
    "rent_monthly": 8500,
    "reviewed": false
  }
]
```

`fields` 是使用者可編輯的顯示內容；`rent_monthly` 是用來篩選比較的月租數字。修改後再執行：

```powershell
$request.edits = @(Get-Content -Raw -Encoding UTF8 .\examples\quickstart\edits.json | ConvertFrom-Json)
$preview = Invoke-RestMethod -Method Post -Uri "$api/imports/preview" -ContentType "application/json; charset=utf-8" -Body ($request | ConvertTo-Json -Depth 30)
$preview.items[0].property.fields
```

**仍然沒有存檔。** 可以反覆修改 edits.json、重跑這段，直到使用者確定。前端正式串接時，表單修改值直接放 `$request.edits` 對應的 JavaScript 物件，不需要真的產生檔案。

## 4. 使用者按「確認並儲存」時，怎麼存進資料庫？

確認畫面無誤後才執行：

```powershell
if (-not $preview.can_commit) { throw "還有 errors，請先修正" }
$request.edits[0].reviewed = $true
$request.request_id = [guid]::NewGuid().ToString()
$saved = Invoke-RestMethod -Method Post -Uri "$api/imports/commit" -ContentType "application/json; charset=utf-8" -Body ($request | ConvertTo-Json -Depth 30)
$id = $saved.properties[0].id
$saved.properties[0]
```

這時才真正存進 `data\housing.sqlite3`。`id` 是房源的唯一編號；`fields` 是修正結果；`original_ai_fields` 仍保留修改前的 AI 值。

如果網路失敗要重試，只重跑 Invoke-RestMethod 那一行，沿用同一個 request_id；不要重新產生 GUID。換新文章時重新從第 2 步開始，前端每次新匯入也使用新的 request_id。

## 5. 從哪個指令把資料庫裡的房源抓出來？

```powershell
$result = Invoke-RestMethod -Uri "$api/properties"
$result.properties
```

前端就用回傳的 `properties` 做列表、勾選及並排比較，不需要自己讀 SQLite。也可以直接用瀏覽器開 [全部房源](http://127.0.0.1:8000/properties)。

要篩選 6000–9000 元：

```powershell
$result = Invoke-RestMethod -Uri "$api/properties?min_rent=6000&max_rent=9000"
$result.properties
```

要下載整份 JSON 檔交給別人：

```powershell
Invoke-WebRequest -Uri "$api/properties/export" -OutFile .\housing-export.json
```

## 前端程式直接用這個檔案

將 `examples/frontend-api.mjs` 複製進前端專案，import 後就能呼叫。下列變數 `aiJsonText` 代表 AI 回傳的 JSON 字串，`articleText` 代表使用者貼上的文章。

```javascript
import {createHousingApi} from './frontend-api.mjs';
const api = createHousingApi('http://127.0.0.1:8000');
const draft = {json_text: aiJsonText, metadata: [{raw_text: articleText}]};

// A. AI 產生 JSON 後，顯示欄位給使用者。
const preview = await api.preview(draft);
console.log(preview.items[0].property.fields); // 用這個初始化表單

// B. 使用者改表單時，把修改填進 edits；原始 draft.json_text 保持不變。
draft.edits = [{fields: {租金: '月租8500元', 房型: '大套房'}, rent_monthly: 8500}];
const edited = await api.preview(draft); // 仍不存檔，顯示 edited.items 的 errors/warnings

// C. 只有使用者按「確認並儲存」的事件處理函式，才執行以下三行。
if (!edited.can_commit) throw new Error('請先修正 errors');
draft.edits[0].reviewed = true;
const requestId = crypto.randomUUID(); // 保留此 ID，網路重試時沿用
const saved = await api.commit(draft, requestId);

// D. 列表／比較頁面從這裡讀資料。
const result = await api.list();
console.log(result.properties);
```

以上是四個操作時機的範例；請分別放在對應的畫面事件，不要載入頁面就連續自動執行到儲存。真正表單的欄位值請取代範例中的 8500 與大套房。

前端獨立啟動時，在後端啟動前將 `$env:HOUSING_CORS_ORIGINS` 設為實際前端 origin，例如 `http://localhost:5173`；不同連接埠請填實際值，然後重新啟動後端。

## 已經存好的房源，之後還要再改？

前端可直接呼叫：

```javascript
await api.update(id, {fields: {租金: '月租9000元'}, rent_monthly: 9000});
// 修改後會變成未核對；使用者再次按下確認按鈕時再呼叫：
await api.update(id, {reviewed: true});
```

本指南先以一則文章／一筆房源示範。多筆時 metadata 與 edits 都需與 AI 陣列等長、同索引對應，不能把同一段原文錯配給所有房源。未修改的 edits 列可用 null；只有使用者確定核對過的列才送 reviewed=true。
