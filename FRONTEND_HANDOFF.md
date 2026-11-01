# 前端交接：中興 AI 租屋資訊助手

第一次串接請先使用 [FRONTEND_QUICKSTART.md](FRONTEND_QUICKSTART.md)，有可直接複製的操作順序與 JavaScript 小工具。本文件保留完整欄位規格，遇到細節再查即可。

## 先接起來的流程

使用者複製網頁全文，透過 Blue 的 Prompt 產生 JSON。前端收集兩個輸入：**AI JSON 文字**與**逐筆對應的原始刊登文字／來源網址**。

1. 按「預覽」送 `/imports/preview`；顯示每筆 `items[index].property.fields`、原文、warnings、errors。預覽不產生 ID、不寫入資料。
2. 有 errors 的列要顯示欄位與訊息，整批禁用匯入。`can_commit=true` 代表結構可保存，不代表內容已核對。
3. 將預覽結果做成可編輯表單；保留原始 `json_text`，使用者修正放在等長的 `edits` 陣列，修改後可再次呼叫 preview，仍不寫入資料庫。
4. 使用者按「確認並儲存」，以原始 json_text、metadata、edits 加上新 `request_id` 送 `/imports/commit`。如果這個按鈕代表明確核對，可在對應 edits 列送 `reviewed:true`。網路重試沿用同一 ID；修改匯入內容後使用新 ID。commit 重新驗證，不信任預覽回傳物件。
5. 將回傳 `properties` 放入列表。儲存後再修改用 ID 送 PATCH。保存成功後以伺服器回傳值更新畫面，不改前端暫存就當已保存。
6. 儲存後內容修改會重設 `reviewed=false`。提供另一個「我已對照原文確認」按鈕，單獨 PATCH `{"reviewed":true}`；沒有使用者動作不可自動確認。
7. GET 列表並篩選，前端以 ID 勾選並排比較。匯出 API 或腳本可將快照交給最後一位同學。

**匯入前修改請用 edits，不要改掉原始 json_text**，否則就無法保留修改前的 AI 輸出。前端可從 property.fields 初始化表單，將有修改的欄位放到 edits[i].fields；後端保存的是修正後 fields，original_ai_fields 仍是原始 AI 值。不要把預覽的 property 包回 json_text，它是內部結構。

## 匯入前可修改的完整契約

`preview` 與 `commit` 都接受可選 `edits`：與房源等長的陣列，沒修改的列可填 null 或 `{}`。每列只允許 `fields`（18 欄的部分修改）、`rent_monthly`（人工數字或 null）、`reviewed`（明確確認布林值）。省略 edits 仍沿用舊介面，reviewed 預設 false。修改可修正 AI 原值的型別錯誤，但 JSON 語法本身必須合法。

```json
{
  "json_text": "[{\"租金\":\"待確認：8000或8500\",\"房型\":\"待確認：套房或雅房\"}]",
  "metadata": [{"raw_text":"【虛構原文】8000或8500，套房或雅房待核對。"}],
  "edits": [{"fields":{"租金":"月租8500元","房型":"套房"},"rent_monthly":8500}]
}
```

先用這份請求 preview，使用者看過修改後內容並按「確認並儲存」才在該列加 `reviewed:true`，另加 request_id 呼叫 commit。`reviewed:true` 可以在首次匯入前的修改與明確確認同時送出；已存入的房源若再修改，仍需先 PATCH 保存、再獨立確認。匯入識別也包含 edits，相同 request_id 不同修改內容會回 409。

前端表單應並列顯示原文、原始 AI 值、可修改欄位與 warnings。使用者尚未按保存前，可在前端暫存草稿；本版不會把預覽草稿持久化。取消或關閉頁面不會新增房源。所有列重新驗證成功才整批保存，含錯誤的修改不會部分寫入。

## Blue → 內部欄位對照

18 個欄名原樣保留：租金、押金、付款方式、管理費、水費、電費、房型、坪數、樓層、地址、最短租期、可否開伙、可否養寵物、性別限制、設備、其他、來源網址、離中興距離。

| Blue 輸入 | 內部儲存與前端使用 |
|---|---|
| 每筆原物件（含額外欄） | `original_ai_fields` 不可變，保留匯入時數字／文字／陣列等原始 JSON 值 |
| 18 個已知欄位 | `fields`：除了設備，全部為字串；有限數字轉十進位文字，布林／物件／其他陣列為阻擋錯誤 |
| 設備為文字 | `fields.設備` 是單元素 `string[]`，不猜測標點切割；顯示可用 `.join('、')` |
| 設備為字串陣列 | `fields.設備` 保留陣列；空陣列可保存但會提示未揭露 |
| 缺欄、null、空白 | `fields` 補「未揭露」；設備補 `["未揭露"]`，`original_ai_fields` 不補值 |
| 額外未知欄位 | 同時保存在 `extra_fields` 與 `original_ai_fields`，可讀但本版不可 PATCH |
| 逐筆 `metadata[i].raw_text` | `raw_text`，預設 `""` 並提示缺少原文；可 PATCH |
| 逐筆 `metadata[i].source_url` | 保存在 `source_metadata`；只在 AI 網址未揭露時補進目前 `fields.來源網址` |
| 包裝其他非房源資訊 | 回傳 `wrapper_metadata`，也保存在匯入請求紀錄，不靜默丟棄 |
| 租金原值 | `fields.租金` 顯示文字；獨立的 `rent_monthly` 供篩選排序，不從其他費用推算 |

外層接受單筆物件、非空陣列、或單層 `properties/data/results` 包裝（值須為房源物件，或每筆至少含一個已知欄位的非空陣列）。有多個可能的房源集合即錯誤，即使其中一個鍵不在允許清單，也不任選。已包含契約欄位的單筆物件，其其他欄位視為額外資料並保留。空批次不匯入。

接受完整包住 JSON 的 ```json 或未標語言程式碼區塊；開頭標記後及結尾標記前須換行。不會從任意說明文字中截 JSON。重複 JSON 鍵、NaN、Infinity、溢位浮點數會拒絕。任何內容都只當資料，不執行其中指令。

## 內部 Property 的型別與意義

| 欄位 | 型別／意義 |
|---|---|
| `id` | 系統 UUID 字串，PATCH 不可改 |
| `fields` | 18 欄物件；17 個 `string` 與 `設備: string[]`，沒有 null |
| `original_ai_fields` | 匯入時原物件；後續人工更新不覆寫 |
| `extra_fields` | 未識別的額外欄位物件，保留所有 JSON 型別 |
| `raw_text` | 原刊登全文或逐筆片段，字串，可空 |
| `source_metadata` | 匯入時對應的 metadata 物件，保留來源資訊，不跟隨人工修改 |
| `reviewed` | 布林，預設 false；首次匯入可透過 edits 中明確的 true 標記確認。即使 true 仍可有未揭露或警告 |
| `rent_monthly` | 有限且非負的 JSON number 或 null；0 是有效值，不能用 truthiness 當未知 |
| `rent_monthly_source` | `safe_parse`（安全解析）、`manual`（人工設定或清除）、`unknown`（未確定） |
| `warnings` | 目前問題清單；`{code,index,field,message}`，index 為匯入索引或 null |
| `import_warnings` | 匯入時的缺漏／型別正規化／來源衝突歷史提醒，後續不改寫 |
| `created_at`、`updated_at` | ISO 8601 UTC 帶 `+00:00`，可用 `new Date(...)`；created_at 不可改 |

預覽 `property` 尚未有 id、created_at、updated_at。每列另外有 `errors`、`warnings` 及 0 起算的 `index`。若不是房源物件，`property=null`。有錯誤的列可能只有部分可正規化欄位，請先呈現錯誤而不要作為可保存物件。

`warnings` 不阻擋保存：`MISSING_FIELD` 缺欄補值、`UNDISCLOSED` 未揭露、`NEEDS_CONFIRMATION` 含待確認、`MISSING_RAW_TEXT` 缺原文、`UNKNOWN_RENT` 未確定月租、`MANUAL_RENT` 人工月租、`INVALID_SOURCE_URL` 網址不是明確 HTTP(S)、`SOURCE_CONFLICT` 逐筆來源與 AI 來源不同、`POSSIBLE_DUPLICATE` 相同來源疑似重複。內容更新後重新計算目前 warnings，歷史提醒仍在 import_warnings；疑似重複提示會隨當前資料重新計算。

來源網址相同不覆寫、不合併；可能是同頁不同房型。不明網址保留「未揭露」，不編造。逐筆 metadata 的不合法網址會成為錯誤；AI 原欄位中的不明網址則保留文字並警告。前端只對有效 http/https 網址建立連結，外連加 `rel="noopener noreferrer"`，其餘文字使用 `textContent` 或框架預設的文字跳脫。

## 月租與人工修改

明確約定：Blue 的**數字或純數字字串視為每月租金**。接受 `8000`、`"8000"`、`"8,000元/月"`、`"月租8000元"`。只比對完整租金欄位；含範圍、多個金額、待確認、日租、年租或額外說明時不推論。`"8000元"` 亦保留 null，請 Blue 或人工補明週期。即使是 `"8000元/月（含水）"`，本版採保守規則保留 null。

Claude 附件前三筆月租是 5000、7500、8880；第四筆 `5700元/月（說明：租金範圍5700～7700元）` 及第五筆 `12000元/月（說明：依房間大小為10000元或12000元）` 都是 null。付款方式的年繳文字不會把明示月租當年租，亦不換算押金或水電費。

PATCH 只接受 `fields`（部分 18 欄）、`raw_text`、`rent_monthly`、`reviewed`。省略欄位代表保持目前值；不能整個 PUT 物件，也不能修改 ID、時間、原始 AI 資料等系統欄位。不存在的 ID 回 404，不新增。

```json
{"fields":{"租金":"月租8500元","設備":["冷氣","書桌"]},"rent_monthly":8500}
```

只修改 fields.租金 時，如果沒有人工月租設定紀錄，會重跑安全解析。送 `{"rent_monthly":8500}` 是人工指定；送 `{"rent_monthly":null}` 是人工清除，來源均為 manual。之後修改其他欄位或租金文字也**不會自動填回／覆寫人工月租**；要改數字請再次明確送出 rent_monthly。本版沒有切回自動解析的操作。

修改內容會重設 reviewed=false。若同一 PATCH 同時更改內容並送 reviewed=true，回 422 且整個更新不保存；先保存，再獨立確認。完全未變的更新不更動時間。多位同學同時編輯時本版採最後寫入者為準，前端宜單人編修，沒有版本衝突介面。

## endpoint 與錯誤規格

| 方法／路徑 | 輸入與行為 |
|---|---|
| `GET /health` | 檢查資料庫連線，`{"status":"ok"}` |
| `POST /imports/preview` | body：`json_text: string`，可選 `metadata: object[]`、`edits: (object或null)[]`；200 包含逐筆錯誤及警告，不寫入 |
| `POST /imports/commit` | 與 preview 相同，另必填 `request_id`；整批成功才寫入；新請求及成功重試皆 200 |
| `GET /properties` | 回傳 `{count,properties}`；可篩選與排序 |
| `GET /properties/{id}` | 回傳完整 Property |
| `PATCH /properties/{id}` | 回傳保存後完整 Property |
| `GET /properties/export` | JSON 下載，`Content-Disposition: attachment; filename="housing-export.json"`；可選 `reviewed_only=true` |

列表 query：`min_rent`、`max_rent` 是含邊界的非負數；`include_unknown=true/false` 預設 false；`reviewed=true/false` 省略則兩者皆含；`sort=rent_asc/rent_desc` 預設升冪。**只有套用價格上下限時才預設排除未知租金**，未套用價格區間時全部列出。未知值兩種排序皆固定最後。匯出同樣使用月租升冪。

匯入請求 ID 為 1–100 字元的英數、`_`、`-`，建議用 `crypto.randomUUID()`。相同 ID、相同解析內容會回 `replayed=true` 與原房源 ID 的**目前資料**（可能已人工修改），不重複新增；同 ID 不同內容回 409。識別內容包含逐筆 metadata 與包裝 metadata，忽略 JSON 排版差異。跨不同 ID 不自動去重。`HousingService.create()` 是單筆新增的 Python 捷徑，也走相同匯入驗證。

統一錯誤格式如下，HTTP body 語法與 json_text 內的語法都可區分。預覽列 errors 使用相同 detail 結構；JSON 語法或外層結構錯誤則直接回 HTTP 錯誤，不產生預覽列。

```json
{"error":{"code":"FIELD_VALIDATION_ERROR","message":"整批匯入取消，請先修正所有阻擋錯誤。","details":[{"code":"INVALID_TYPE","index":1,"field":"租金","message":"必須是文字或有限數字，不接受布林、物件或陣列。"}]}}
```

| code | HTTP 狀態 |
|---|---|
| `JSON_SYNTAX_ERROR` | 400 |
| `UNSUPPORTED_STRUCTURE` | 422 |
| `FIELD_VALIDATION_ERROR` | 422；HTTP body 超限為 413 |
| `PROPERTY_NOT_FOUND` | 404 |
| `DATABASE_ERROR` | 500，交易回滾，不提供內部 SQL |
| `IMPORT_REQUEST_CONFLICT` | 409 |
| `HTTP_ERROR` | 對應路由不存在／方法不符等 HTTP 狀態 |

一批 1–100 筆；json_text 最多 1,048,576 字元；原文每筆及欄位字串／設備每個項目最多 20,000 字元；source_url 最多 2,048 字元；HTTP body 最多 2,097,152 bytes（UTF-8 實際大小）。不要把多筆原文以單一字串共用：metadata 若有提供，其長度必須等於解析後的房源數，依索引對應，只允許 raw_text 與 source_url。省略 metadata 等同每筆空物件；缺原文有警告。

## 可直接使用的 JavaScript

`apiFetch` 會解析統一錯誤並拋出含 details 的 Error；前端可將 details 對應至列與欄位。base 改成實際後端 origin，並依 README 設定 CORS。

```javascript
const base = 'http://127.0.0.1:8000';
async function apiFetch(path, method = 'GET', body) {
  const response = await fetch(base + path, {
    method,
    headers: body === undefined ? {} : {'Content-Type': 'application/json'},
    ...(body === undefined ? {} : {body: JSON.stringify(body)})
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error?.message ?? `HTTP ${response.status}`);
    error.code = data.error?.code;
    error.details = data.error?.details ?? [];
    throw error;
  }
  return data;
}

// 這裡使用完全虛構資料；實際操作時換成 Blue 回傳的完整 JSON 字串。
const input = {
  json_text: JSON.stringify([{租金: '8,000元/月', 設備: ['冷氣'],
    其他: '完全虛構示範，非真實房源'}]),
  metadata: [{raw_text: '【完全虛構】月租8000元，附冷氣。'}]
};
const preview = await apiFetch('/imports/preview', 'POST', input);
console.log(preview.items); // 先顯示逐筆 errors、warnings 及原文給使用者
if (!preview.can_commit) throw new Error('請先修正 errors');

// 使用者在表單修改時：保留 input.json_text，只提交修改過的欄位。
const draft = {...input, edits: [{fields: {租金: '月租8500元'}, rent_monthly: 8500}]};
const editedPreview = await apiFetch('/imports/preview', 'POST', draft);
console.log(editedPreview.items); // 顯示修正後結果，仍未保存
if (!editedPreview.can_commit) throw new Error('請修正草稿 errors');

// 使用者按「確認並儲存」時才執行；重試保存同一個 requestId。
// 若按鈕代表使用者已明確核對，再設定 reviewed:true。
const requestId = crypto.randomUUID();
const commitInput = {...draft, request_id: requestId,
  edits: draft.edits.map(edit => ({...edit, reviewed: true}))};
const imported = await apiFetch('/imports/commit', 'POST', commitInput);
const id = imported.properties[0].id;
const read = await apiFetch(`/properties/${encodeURIComponent(id)}`);
const saved = await apiFetch(`/properties/${encodeURIComponent(id)}`, 'PATCH', {
  fields: {租金: '月租8600元'}, rent_monthly: 8600
});
console.log(saved.reviewed); // false；重新渲染 saved

// 另一個明確確認按鈕才呼叫這一步。
const confirmed = await apiFetch(`/properties/${encodeURIComponent(id)}`, 'PATCH', {reviewed: true});
const query = new URLSearchParams({min_rent: '6000', max_rent: '9000',
  include_unknown: 'true', reviewed: 'true', sort: 'rent_asc'});
const list = await apiFetch('/properties?' + query);
console.log(list.properties, confirmed);

// 人工清除數值，保留租金文字，之後不會被自動填回。
const cleared = await apiFetch(`/properties/${encodeURIComponent(id)}`, 'PATCH', {rent_monthly: null});
console.log(cleared.rent_monthly_source); // manual；reviewed 重設 false

// 匯出完整快照給同學：亦可單純用 <a href=".../properties/export"> 下載。
const snapshot = await apiFetch('/properties/export');
const url = URL.createObjectURL(new Blob([JSON.stringify(snapshot, null, 2)], {type:'application/json'}));
const link = document.createElement('a');
link.href = url;
link.download = 'housing-export.json';
document.body.append(link);
link.click();
link.remove();
setTimeout(() => URL.revokeObjectURL(url), 1000);
```

資料展示：`p.rent_monthly === null ? '月租待確認' : p.rent_monthly.toLocaleString()`；租金原文字仍顯示 `p.fields.租金`。其他欄位使用文字方式渲染，不執行 HTML。warning 使用 message 顯示，index=null 時代表房源整體或讀取時計算的提醒。

## 可直接使用的 Python

在專案根目錄執行，與 HTTP 共用同一個 HousingService，沒有第二套業務邏輯。

```python
import json
from pathlib import Path
from uuid import uuid4
from housing import HousingService
from housing.errors import HousingError

service = HousingService('data/team-demo.sqlite3')
request = {
    'json_text': Path('examples/demo_blue.json').read_text(encoding='utf-8'),
    'metadata': json.loads(Path('examples/demo_metadata.json').read_text(encoding='utf-8')),
}
try:
    preview = service.preview(request)
    if not preview['can_commit']:
        raise ValueError(preview['items'])
    # 使用者修改表單時獨立保存 edits，原始 json_text 不變。
    request['edits'] = [{'fields': {'房型': '人工確認獨立套房'}}, None]
    edited_preview = service.preview(request)
    if not edited_preview['can_commit']:
        raise ValueError(edited_preview['items'])
    # 實際 UI 應等待使用者按「確認並儲存」，重試沿用這個 ID。
    request['edits'][0]['reviewed'] = True
    request_id = str(uuid4())
    result = service.commit({**request, 'request_id': request_id})
    prop = result['properties'][0]
    saved = service.update_property(prop['id'], {'fields': {'房型': '人工修正套房'}})
    # 實際 UI 再等待獨立的使用者確認動作。
    service.update_property(prop['id'], {'reviewed': True})
    print(service.get_property(prop['id']))
    print(service.list_properties(min_rent=6000, max_rent=9000, include_unknown=True,
                                  reviewed=True, sort='rent_asc'))
    snapshot = service.export_properties(reviewed_only=False)
    Path('team-export.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
except HousingError as error:
    print(error.as_dict())
```

匯出 JSON 格式為 `{schema_version:"1.0",exported_at,count,properties:[Property...]}`。最後一位同學可 `JSON.parse`／`json.loads` 後讀 `properties`，保留 id、reviewed、null 及來源，不要只取 fields 而遺失核對狀態。這是目前快照；不會隨資料庫更新自動刷新。含原文及原始 AI 值，請在小組內交接；公開展示可由前端挑選需要欄位。

## 與 Blue、前端同學確認

以使用者提供的新 PDF 的 Claude 右欄為主要相容性依據：5 筆陣列、18 欄、全部文字。fixture 從 PDF 重建，未取得原始 JSON 檔，尚未驗證逐位元組一致性。未取得對應完整原文，所以不能把「格式通過」當成「內容正確」。目前測試沒有呼叫 AI 或網站。

Blue 請確認後續外層包裝鍵、設備陣列及 null 的可能性、純數字預設月租，以及多筆房型與原文的索引關係。前端請確認 base URL、CORS origins、warnings 呈現、未知租金篩選、修改後重新核對，以及要使用 API 還是 JSON 快照交接。

以下每個 endpoint 的完整 JSON 範例由實作直接產生，使用完全虛構資料。UUID 與 UTC 時間僅代表這次範例生成，實際呼叫請使用自己的回傳值。重新生成：`python -m scripts.build_api_examples`（需開發依賴）。

<!-- GENERATED_API_EXAMPLES -->
## 完整 HTTP 請求與回應範例

### GET /health

```http
GET /health HTTP/1.1
Host: 127.0.0.1:8000
```

回應 HTTP 200：

```json
{
  "status": "ok"
}
```

### POST /imports/preview

```http
POST /imports/preview HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json
```

請求 body：

```json
{
  "json_text": "[{\"租金\": \"8,000元/月\", \"押金\": \"2個月\", \"付款方式\": \"每月繳\", \"管理費\": \"0元\", \"水費\": \"包含於租金\", \"電費\": \"依獨立電錶帳單\", \"房型\": \"獨立套房\", \"坪數\": \"6坪\", \"樓層\": \"3/5\", \"地址\": \"虛構示範市示範路A棟（非真實地址）\", \"最短租期\": \"1年\", \"可否開伙\": \"不可\", \"可否養寵物\": \"不可\", \"性別限制\": \"不限\", \"設備\": [\"冷氣\", \"書桌\"], \"其他\": \"完全虛構示範，無真實聯絡人或電話\", \"來源網址\": \"https://example.com/fake-property-a\", \"離中興距離\": \"原文自述步行10分鐘（虛構）\", \"示範說明\": \"此為虛構資料，非實際擷取或 Claude 附件房源\"}]",
  "metadata": [
    {
      "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
      "source_url": "https://example.com/fake-property-a"
    }
  ]
}
```

回應 HTTP 200：

```json
{
  "can_commit": true,
  "count": 1,
  "items": [
    {
      "index": 0,
      "property": {
        "fields": {
          "租金": "8,000元/月",
          "押金": "2個月",
          "付款方式": "每月繳",
          "管理費": "0元",
          "水費": "包含於租金",
          "電費": "依獨立電錶帳單",
          "房型": "獨立套房",
          "坪數": "6坪",
          "樓層": "3/5",
          "地址": "虛構示範市示範路A棟（非真實地址）",
          "最短租期": "1年",
          "可否開伙": "不可",
          "可否養寵物": "不可",
          "性別限制": "不限",
          "設備": [
            "冷氣",
            "書桌"
          ],
          "其他": "完全虛構示範，無真實聯絡人或電話",
          "來源網址": "https://example.com/fake-property-a",
          "離中興距離": "原文自述步行10分鐘（虛構）"
        },
        "original_ai_fields": {
          "租金": "8,000元/月",
          "押金": "2個月",
          "付款方式": "每月繳",
          "管理費": "0元",
          "水費": "包含於租金",
          "電費": "依獨立電錶帳單",
          "房型": "獨立套房",
          "坪數": "6坪",
          "樓層": "3/5",
          "地址": "虛構示範市示範路A棟（非真實地址）",
          "最短租期": "1年",
          "可否開伙": "不可",
          "可否養寵物": "不可",
          "性別限制": "不限",
          "設備": [
            "冷氣",
            "書桌"
          ],
          "其他": "完全虛構示範，無真實聯絡人或電話",
          "來源網址": "https://example.com/fake-property-a",
          "離中興距離": "原文自述步行10分鐘（虛構）",
          "示範說明": "此為虛構資料，非實際擷取或 Claude 附件房源"
        },
        "extra_fields": {
          "示範說明": "此為虛構資料，非實際擷取或 Claude 附件房源"
        },
        "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
        "source_metadata": {
          "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
          "source_url": "https://example.com/fake-property-a"
        },
        "reviewed": false,
        "rent_monthly": 8000.0,
        "rent_monthly_source": "safe_parse",
        "import_warnings": [],
        "warnings": []
      },
      "errors": [],
      "warnings": []
    }
  ],
  "wrapper_metadata": {}
}
```

### POST /imports/preview 使用者修改後再預覽（未儲存）

```http
POST /imports/preview HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json
```

請求 body：

```json
{
  "json_text": "[{\"租金\": \"8,000元/月\", \"押金\": \"2個月\", \"付款方式\": \"每月繳\", \"管理費\": \"0元\", \"水費\": \"包含於租金\", \"電費\": \"依獨立電錶帳單\", \"房型\": \"獨立套房\", \"坪數\": \"6坪\", \"樓層\": \"3/5\", \"地址\": \"虛構示範市示範路A棟（非真實地址）\", \"最短租期\": \"1年\", \"可否開伙\": \"不可\", \"可否養寵物\": \"不可\", \"性別限制\": \"不限\", \"設備\": [\"冷氣\", \"書桌\"], \"其他\": \"完全虛構示範，無真實聯絡人或電話\", \"來源網址\": \"https://example.com/fake-property-a\", \"離中興距離\": \"原文自述步行10分鐘（虛構）\", \"示範說明\": \"此為虛構資料，非實際擷取或 Claude 附件房源\"}]",
  "metadata": [
    {
      "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
      "source_url": "https://example.com/fake-property-a"
    }
  ],
  "edits": [
    {
      "fields": {
        "租金": "月租8300元"
      },
      "rent_monthly": 8300
    }
  ]
}
```

回應 HTTP 200：

```json
{
  "can_commit": true,
  "count": 1,
  "items": [
    {
      "index": 0,
      "property": {
        "fields": {
          "租金": "月租8300元",
          "押金": "2個月",
          "付款方式": "每月繳",
          "管理費": "0元",
          "水費": "包含於租金",
          "電費": "依獨立電錶帳單",
          "房型": "獨立套房",
          "坪數": "6坪",
          "樓層": "3/5",
          "地址": "虛構示範市示範路A棟（非真實地址）",
          "最短租期": "1年",
          "可否開伙": "不可",
          "可否養寵物": "不可",
          "性別限制": "不限",
          "設備": [
            "冷氣",
            "書桌"
          ],
          "其他": "完全虛構示範，無真實聯絡人或電話",
          "來源網址": "https://example.com/fake-property-a",
          "離中興距離": "原文自述步行10分鐘（虛構）"
        },
        "original_ai_fields": {
          "租金": "8,000元/月",
          "押金": "2個月",
          "付款方式": "每月繳",
          "管理費": "0元",
          "水費": "包含於租金",
          "電費": "依獨立電錶帳單",
          "房型": "獨立套房",
          "坪數": "6坪",
          "樓層": "3/5",
          "地址": "虛構示範市示範路A棟（非真實地址）",
          "最短租期": "1年",
          "可否開伙": "不可",
          "可否養寵物": "不可",
          "性別限制": "不限",
          "設備": [
            "冷氣",
            "書桌"
          ],
          "其他": "完全虛構示範，無真實聯絡人或電話",
          "來源網址": "https://example.com/fake-property-a",
          "離中興距離": "原文自述步行10分鐘（虛構）",
          "示範說明": "此為虛構資料，非實際擷取或 Claude 附件房源"
        },
        "extra_fields": {
          "示範說明": "此為虛構資料，非實際擷取或 Claude 附件房源"
        },
        "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
        "source_metadata": {
          "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
          "source_url": "https://example.com/fake-property-a"
        },
        "reviewed": false,
        "rent_monthly": 8300,
        "rent_monthly_source": "manual",
        "import_warnings": [],
        "warnings": [
          {
            "code": "MANUAL_RENT",
            "index": 0,
            "field": "rent_monthly",
            "message": "月租由人工指定或清除；請核對租金文字。"
          }
        ]
      },
      "errors": [],
      "warnings": [
        {
          "code": "MANUAL_RENT",
          "index": 0,
          "field": "rent_monthly",
          "message": "月租由人工指定或清除；請核對租金文字。"
        }
      ]
    }
  ],
  "wrapper_metadata": {}
}
```

### POST /imports/commit

```http
POST /imports/commit HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json
```

請求 body：

```json
{
  "json_text": "[{\"租金\": \"8,000元/月\", \"押金\": \"2個月\", \"付款方式\": \"每月繳\", \"管理費\": \"0元\", \"水費\": \"包含於租金\", \"電費\": \"依獨立電錶帳單\", \"房型\": \"獨立套房\", \"坪數\": \"6坪\", \"樓層\": \"3/5\", \"地址\": \"虛構示範市示範路A棟（非真實地址）\", \"最短租期\": \"1年\", \"可否開伙\": \"不可\", \"可否養寵物\": \"不可\", \"性別限制\": \"不限\", \"設備\": [\"冷氣\", \"書桌\"], \"其他\": \"完全虛構示範，無真實聯絡人或電話\", \"來源網址\": \"https://example.com/fake-property-a\", \"離中興距離\": \"原文自述步行10分鐘（虛構）\", \"示範說明\": \"此為虛構資料，非實際擷取或 Claude 附件房源\"}]",
  "metadata": [
    {
      "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
      "source_url": "https://example.com/fake-property-a"
    }
  ],
  "edits": [
    {
      "fields": {
        "租金": "月租8300元"
      },
      "rent_monthly": 8300,
      "reviewed": true
    }
  ],
  "request_id": "frontend-doc-example"
}
```

回應 HTTP 200：

```json
{
  "request_id": "frontend-doc-example",
  "replayed": false,
  "count": 1,
  "properties": [
    {
      "fields": {
        "租金": "月租8300元",
        "押金": "2個月",
        "付款方式": "每月繳",
        "管理費": "0元",
        "水費": "包含於租金",
        "電費": "依獨立電錶帳單",
        "房型": "獨立套房",
        "坪數": "6坪",
        "樓層": "3/5",
        "地址": "虛構示範市示範路A棟（非真實地址）",
        "最短租期": "1年",
        "可否開伙": "不可",
        "可否養寵物": "不可",
        "性別限制": "不限",
        "設備": [
          "冷氣",
          "書桌"
        ],
        "其他": "完全虛構示範，無真實聯絡人或電話",
        "來源網址": "https://example.com/fake-property-a",
        "離中興距離": "原文自述步行10分鐘（虛構）"
      },
      "original_ai_fields": {
        "租金": "8,000元/月",
        "押金": "2個月",
        "付款方式": "每月繳",
        "管理費": "0元",
        "水費": "包含於租金",
        "電費": "依獨立電錶帳單",
        "房型": "獨立套房",
        "坪數": "6坪",
        "樓層": "3/5",
        "地址": "虛構示範市示範路A棟（非真實地址）",
        "最短租期": "1年",
        "可否開伙": "不可",
        "可否養寵物": "不可",
        "性別限制": "不限",
        "設備": [
          "冷氣",
          "書桌"
        ],
        "其他": "完全虛構示範，無真實聯絡人或電話",
        "來源網址": "https://example.com/fake-property-a",
        "離中興距離": "原文自述步行10分鐘（虛構）",
        "示範說明": "此為虛構資料，非實際擷取或 Claude 附件房源"
      },
      "extra_fields": {
        "示範說明": "此為虛構資料，非實際擷取或 Claude 附件房源"
      },
      "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
      "source_metadata": {
        "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
        "source_url": "https://example.com/fake-property-a"
      },
      "reviewed": true,
      "rent_monthly": 8300,
      "rent_monthly_source": "manual",
      "import_warnings": [],
      "warnings": [
        {
          "code": "MANUAL_RENT",
          "index": 0,
          "field": "rent_monthly",
          "message": "月租由人工指定或清除；請核對租金文字。"
        }
      ],
      "id": "ffe235ff-fbfa-4ccf-a5d9-61c2535f35f7",
      "created_at": "2026-11-01T13:00:22.894663+00:00",
      "updated_at": "2026-11-01T13:00:22.894663+00:00"
    }
  ],
  "wrapper_metadata": {}
}
```

### GET /properties?min_rent=6000&max_rent=9000&include_unknown=true&reviewed=true&sort=rent_asc

```http
GET /properties?min_rent=6000&max_rent=9000&include_unknown=true&reviewed=true&sort=rent_asc HTTP/1.1
Host: 127.0.0.1:8000
```

回應 HTTP 200：

```json
{
  "count": 1,
  "properties": [
    {
      "created_at": "2026-11-01T13:00:22.894663+00:00",
      "extra_fields": {
        "示範說明": "此為虛構資料，非實際擷取或 Claude 附件房源"
      },
      "fields": {
        "付款方式": "每月繳",
        "來源網址": "https://example.com/fake-property-a",
        "其他": "完全虛構示範，無真實聯絡人或電話",
        "可否開伙": "不可",
        "可否養寵物": "不可",
        "地址": "虛構示範市示範路A棟（非真實地址）",
        "坪數": "6坪",
        "性別限制": "不限",
        "房型": "獨立套房",
        "押金": "2個月",
        "最短租期": "1年",
        "樓層": "3/5",
        "水費": "包含於租金",
        "租金": "月租8300元",
        "管理費": "0元",
        "設備": [
          "冷氣",
          "書桌"
        ],
        "離中興距離": "原文自述步行10分鐘（虛構）",
        "電費": "依獨立電錶帳單"
      },
      "id": "ffe235ff-fbfa-4ccf-a5d9-61c2535f35f7",
      "import_warnings": [],
      "original_ai_fields": {
        "付款方式": "每月繳",
        "來源網址": "https://example.com/fake-property-a",
        "其他": "完全虛構示範，無真實聯絡人或電話",
        "可否開伙": "不可",
        "可否養寵物": "不可",
        "地址": "虛構示範市示範路A棟（非真實地址）",
        "坪數": "6坪",
        "性別限制": "不限",
        "房型": "獨立套房",
        "押金": "2個月",
        "最短租期": "1年",
        "樓層": "3/5",
        "水費": "包含於租金",
        "示範說明": "此為虛構資料，非實際擷取或 Claude 附件房源",
        "租金": "8,000元/月",
        "管理費": "0元",
        "設備": [
          "冷氣",
          "書桌"
        ],
        "離中興距離": "原文自述步行10分鐘（虛構）",
        "電費": "依獨立電錶帳單"
      },
      "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
      "rent_monthly": 8300,
      "rent_monthly_source": "manual",
      "reviewed": true,
      "source_metadata": {
        "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
        "source_url": "https://example.com/fake-property-a"
      },
      "updated_at": "2026-11-01T13:00:22.894663+00:00",
      "warnings": [
        {
          "code": "MANUAL_RENT",
          "field": "rent_monthly",
          "index": 0,
          "message": "月租由人工指定或清除；請核對租金文字。"
        }
      ]
    }
  ]
}
```

### GET /properties/ffe235ff-fbfa-4ccf-a5d9-61c2535f35f7

```http
GET /properties/ffe235ff-fbfa-4ccf-a5d9-61c2535f35f7 HTTP/1.1
Host: 127.0.0.1:8000
```

回應 HTTP 200：

```json
{
  "created_at": "2026-11-01T13:00:22.894663+00:00",
  "extra_fields": {
    "示範說明": "此為虛構資料，非實際擷取或 Claude 附件房源"
  },
  "fields": {
    "付款方式": "每月繳",
    "來源網址": "https://example.com/fake-property-a",
    "其他": "完全虛構示範，無真實聯絡人或電話",
    "可否開伙": "不可",
    "可否養寵物": "不可",
    "地址": "虛構示範市示範路A棟（非真實地址）",
    "坪數": "6坪",
    "性別限制": "不限",
    "房型": "獨立套房",
    "押金": "2個月",
    "最短租期": "1年",
    "樓層": "3/5",
    "水費": "包含於租金",
    "租金": "月租8300元",
    "管理費": "0元",
    "設備": [
      "冷氣",
      "書桌"
    ],
    "離中興距離": "原文自述步行10分鐘（虛構）",
    "電費": "依獨立電錶帳單"
  },
  "id": "ffe235ff-fbfa-4ccf-a5d9-61c2535f35f7",
  "import_warnings": [],
  "original_ai_fields": {
    "付款方式": "每月繳",
    "來源網址": "https://example.com/fake-property-a",
    "其他": "完全虛構示範，無真實聯絡人或電話",
    "可否開伙": "不可",
    "可否養寵物": "不可",
    "地址": "虛構示範市示範路A棟（非真實地址）",
    "坪數": "6坪",
    "性別限制": "不限",
    "房型": "獨立套房",
    "押金": "2個月",
    "最短租期": "1年",
    "樓層": "3/5",
    "水費": "包含於租金",
    "示範說明": "此為虛構資料，非實際擷取或 Claude 附件房源",
    "租金": "8,000元/月",
    "管理費": "0元",
    "設備": [
      "冷氣",
      "書桌"
    ],
    "離中興距離": "原文自述步行10分鐘（虛構）",
    "電費": "依獨立電錶帳單"
  },
  "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
  "rent_monthly": 8300,
  "rent_monthly_source": "manual",
  "reviewed": true,
  "source_metadata": {
    "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
    "source_url": "https://example.com/fake-property-a"
  },
  "updated_at": "2026-11-01T13:00:22.894663+00:00",
  "warnings": [
    {
      "code": "MANUAL_RENT",
      "field": "rent_monthly",
      "index": 0,
      "message": "月租由人工指定或清除；請核對租金文字。"
    }
  ]
}
```

### PATCH 保存人工修改

```http
PATCH /properties/ffe235ff-fbfa-4ccf-a5d9-61c2535f35f7 HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json
```

請求 body：

```json
{
  "fields": {
    "房型": "人工確認獨立套房"
  }
}
```

回應 HTTP 200：

```json
{
  "created_at": "2026-11-01T13:00:22.894663+00:00",
  "extra_fields": {
    "示範說明": "此為虛構資料，非實際擷取或 Claude 附件房源"
  },
  "fields": {
    "租金": "月租8300元",
    "押金": "2個月",
    "付款方式": "每月繳",
    "管理費": "0元",
    "水費": "包含於租金",
    "電費": "依獨立電錶帳單",
    "房型": "人工確認獨立套房",
    "坪數": "6坪",
    "樓層": "3/5",
    "地址": "虛構示範市示範路A棟（非真實地址）",
    "最短租期": "1年",
    "可否開伙": "不可",
    "可否養寵物": "不可",
    "性別限制": "不限",
    "設備": [
      "冷氣",
      "書桌"
    ],
    "其他": "完全虛構示範，無真實聯絡人或電話",
    "來源網址": "https://example.com/fake-property-a",
    "離中興距離": "原文自述步行10分鐘（虛構）"
  },
  "id": "ffe235ff-fbfa-4ccf-a5d9-61c2535f35f7",
  "import_warnings": [],
  "original_ai_fields": {
    "付款方式": "每月繳",
    "來源網址": "https://example.com/fake-property-a",
    "其他": "完全虛構示範，無真實聯絡人或電話",
    "可否開伙": "不可",
    "可否養寵物": "不可",
    "地址": "虛構示範市示範路A棟（非真實地址）",
    "坪數": "6坪",
    "性別限制": "不限",
    "房型": "獨立套房",
    "押金": "2個月",
    "最短租期": "1年",
    "樓層": "3/5",
    "水費": "包含於租金",
    "示範說明": "此為虛構資料，非實際擷取或 Claude 附件房源",
    "租金": "8,000元/月",
    "管理費": "0元",
    "設備": [
      "冷氣",
      "書桌"
    ],
    "離中興距離": "原文自述步行10分鐘（虛構）",
    "電費": "依獨立電錶帳單"
  },
  "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
  "rent_monthly": 8300,
  "rent_monthly_source": "manual",
  "reviewed": false,
  "source_metadata": {
    "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
    "source_url": "https://example.com/fake-property-a"
  },
  "updated_at": "2026-11-01T13:00:22.912192+00:00",
  "warnings": [
    {
      "code": "MANUAL_RENT",
      "index": null,
      "field": "rent_monthly",
      "message": "月租由人工指定或清除；請核對租金文字。"
    }
  ]
}
```

### PATCH 獨立明確確認

```http
PATCH /properties/ffe235ff-fbfa-4ccf-a5d9-61c2535f35f7 HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json
```

請求 body：

```json
{
  "reviewed": true
}
```

回應 HTTP 200：

```json
{
  "created_at": "2026-11-01T13:00:22.894663+00:00",
  "extra_fields": {
    "示範說明": "此為虛構資料，非實際擷取或 Claude 附件房源"
  },
  "fields": {
    "付款方式": "每月繳",
    "來源網址": "https://example.com/fake-property-a",
    "其他": "完全虛構示範，無真實聯絡人或電話",
    "可否開伙": "不可",
    "可否養寵物": "不可",
    "地址": "虛構示範市示範路A棟（非真實地址）",
    "坪數": "6坪",
    "性別限制": "不限",
    "房型": "人工確認獨立套房",
    "押金": "2個月",
    "最短租期": "1年",
    "樓層": "3/5",
    "水費": "包含於租金",
    "租金": "月租8300元",
    "管理費": "0元",
    "設備": [
      "冷氣",
      "書桌"
    ],
    "離中興距離": "原文自述步行10分鐘（虛構）",
    "電費": "依獨立電錶帳單"
  },
  "id": "ffe235ff-fbfa-4ccf-a5d9-61c2535f35f7",
  "import_warnings": [],
  "original_ai_fields": {
    "付款方式": "每月繳",
    "來源網址": "https://example.com/fake-property-a",
    "其他": "完全虛構示範，無真實聯絡人或電話",
    "可否開伙": "不可",
    "可否養寵物": "不可",
    "地址": "虛構示範市示範路A棟（非真實地址）",
    "坪數": "6坪",
    "性別限制": "不限",
    "房型": "獨立套房",
    "押金": "2個月",
    "最短租期": "1年",
    "樓層": "3/5",
    "水費": "包含於租金",
    "示範說明": "此為虛構資料，非實際擷取或 Claude 附件房源",
    "租金": "8,000元/月",
    "管理費": "0元",
    "設備": [
      "冷氣",
      "書桌"
    ],
    "離中興距離": "原文自述步行10分鐘（虛構）",
    "電費": "依獨立電錶帳單"
  },
  "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
  "rent_monthly": 8300,
  "rent_monthly_source": "manual",
  "reviewed": true,
  "source_metadata": {
    "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
    "source_url": "https://example.com/fake-property-a"
  },
  "updated_at": "2026-11-01T13:00:22.918210+00:00",
  "warnings": [
    {
      "code": "MANUAL_RENT",
      "index": null,
      "field": "rent_monthly",
      "message": "月租由人工指定或清除；請核對租金文字。"
    }
  ]
}
```

### GET /properties/export?reviewed_only=true

```http
GET /properties/export?reviewed_only=true HTTP/1.1
Host: 127.0.0.1:8000
```

回應 HTTP 200：

```json
{
  "schema_version": "1.0",
  "exported_at": "2026-11-01T13:00:22.928736+00:00",
  "count": 1,
  "properties": [
    {
      "created_at": "2026-11-01T13:00:22.894663+00:00",
      "extra_fields": {
        "示範說明": "此為虛構資料，非實際擷取或 Claude 附件房源"
      },
      "fields": {
        "付款方式": "每月繳",
        "來源網址": "https://example.com/fake-property-a",
        "其他": "完全虛構示範，無真實聯絡人或電話",
        "可否開伙": "不可",
        "可否養寵物": "不可",
        "地址": "虛構示範市示範路A棟（非真實地址）",
        "坪數": "6坪",
        "性別限制": "不限",
        "房型": "人工確認獨立套房",
        "押金": "2個月",
        "最短租期": "1年",
        "樓層": "3/5",
        "水費": "包含於租金",
        "租金": "月租8300元",
        "管理費": "0元",
        "設備": [
          "冷氣",
          "書桌"
        ],
        "離中興距離": "原文自述步行10分鐘（虛構）",
        "電費": "依獨立電錶帳單"
      },
      "id": "ffe235ff-fbfa-4ccf-a5d9-61c2535f35f7",
      "import_warnings": [],
      "original_ai_fields": {
        "付款方式": "每月繳",
        "來源網址": "https://example.com/fake-property-a",
        "其他": "完全虛構示範，無真實聯絡人或電話",
        "可否開伙": "不可",
        "可否養寵物": "不可",
        "地址": "虛構示範市示範路A棟（非真實地址）",
        "坪數": "6坪",
        "性別限制": "不限",
        "房型": "獨立套房",
        "押金": "2個月",
        "最短租期": "1年",
        "樓層": "3/5",
        "水費": "包含於租金",
        "示範說明": "此為虛構資料，非實際擷取或 Claude 附件房源",
        "租金": "8,000元/月",
        "管理費": "0元",
        "設備": [
          "冷氣",
          "書桌"
        ],
        "離中興距離": "原文自述步行10分鐘（虛構）",
        "電費": "依獨立電錶帳單"
      },
      "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
      "rent_monthly": 8300,
      "rent_monthly_source": "manual",
      "reviewed": true,
      "source_metadata": {
        "raw_text": "【完全虛構示範 A】月租8000元，押金2個月，每月繳，管理費0元，含水，電費依獨立電錶帳單。獨立套房6坪，3/5樓，虛構示範市示範路A棟，最短租1年，不可開伙、不可養寵物，性別不限，附冷氣、書桌。原文自述離中興步行10分鐘（虛構）。",
        "source_url": "https://example.com/fake-property-a"
      },
      "updated_at": "2026-11-01T13:00:22.918210+00:00",
      "warnings": [
        {
          "code": "MANUAL_RENT",
          "field": "rent_monthly",
          "index": null,
          "message": "月租由人工指定或清除；請核對租金文字。"
        }
      ]
    }
  ]
}
```
