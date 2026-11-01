// 前端可直接複製使用：全部資料透過既有 HTTP API，不直接開啟 SQLite。
export function createHousingApi(baseUrl = 'http://127.0.0.1:8000') {
  const base = baseUrl.replace(/\/$/, '');

  async function request(path, method = 'GET', body) {
    const response = await fetch(base + path, {
      method,
      ...(body === undefined ? {} : {
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
      })
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

  return {
    // requestData = {json_text: 原始AI字串, metadata: [{raw_text: 原文}], edits?: [...]}
    // 初次預覽與修改後預覽都呼叫這個函式，均不存檔。
    preview: requestData => request('/imports/preview', 'POST', requestData),

    // 只有使用者按「確認並儲存」才呼叫；重試沿用相同 requestId。
    commit: (requestData, requestId) => request('/imports/commit', 'POST', {
      ...requestData, request_id: requestId
    }),

    // 讀取已保存的房源，可傳 min_rent/max_rent/include_unknown/reviewed/sort。
    list: (filters = {}) => {
      const query = new URLSearchParams();
      for (const [key, value] of Object.entries(filters)) {
        if (value !== undefined && value !== null) query.set(key, String(value));
      }
      return request('/properties' + (query.size ? '?' + query : ''));
    },

    get: id => request('/properties/' + encodeURIComponent(id)),

    // 儲存後再修改，使用 id；內容變更後 reviewed 會重設 false。
    update: (id, changes) => request('/properties/' + encodeURIComponent(id), 'PATCH', changes)
  };
}
