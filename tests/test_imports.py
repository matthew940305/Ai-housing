import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from housing.adapter import MAX_BATCH, MAX_JSON_CHARS
from housing.domain import FIELDS
from housing.errors import HousingError


def payload(data, **kwargs):
    return {"json_text": json.dumps(data, ensure_ascii=False), **kwargs}


def test_initial_empty_and_preview_does_not_write(service):
    assert service.health() == {"status": "ok"}
    assert service.list_properties() == []
    result = service.preview(payload({"租金": 8000}))
    assert result["can_commit"]
    assert result["items"][0]["property"]["reviewed"] is False
    assert "id" not in result["items"][0]["property"]
    assert service.list_properties() == []


@pytest.mark.parametrize("structure", [
    {"租金": 8000}, [{"租金": 8000}], {"properties": [{"租金": 8000}]},
    {"data": {"租金": 8000}}, {"results": [{"租金": 8000}]},
])
def test_supported_shapes(service, structure):
    assert service.preview(payload(structure))["items"][0]["property"]["rent_monthly"] == 8000


@pytest.mark.parametrize("fence", ["```json\n{}\n```", "```\r\n{}\r\n```"])
def test_complete_markdown_fence(service, fence):
    assert service.preview({"json_text": fence.format('[{"租金": 8000}]')})["can_commit"]


@pytest.mark.parametrize("text", ["{bad}", '說明：[{"租金": 8000}]', '```json\n{"租金":8000}\n```還有說明',
                                    '{"租金":NaN}', '{"租金":Infinity}', '{"租金":1e999}', '{"租金":8000,"租金":9000}'])
def test_invalid_json(service, text):
    with pytest.raises(HousingError) as exc:
        service.preview({"json_text": text})
    assert exc.value.code == "JSON_SYNTAX_ERROR"


@pytest.mark.parametrize("data", [
    {"unknown": [{"租金": 8000}]}, {"data": [{"abc": 1}]},
    {"data": [{"租金": 8000}], "results": [{"租金": 9000}]},
    {"data": [{"租金": 8000}], "unknown": [{"租金": 9000}]},
    [], {}, "hello", {"data": []},
])
def test_unsupported_or_ambiguous_structure(service, data):
    with pytest.raises(HousingError) as exc:
        service.preview(payload(data))
    assert exc.value.code == "UNSUPPORTED_STRUCTURE"


def test_missing_pending_equipment_and_extras(service):
    original = {"租金": 8000, "設備": ["冷氣", "洗衣機"], "水費": "待確認：含租金或另計", "新欄位": {"保留": [1, True]}}
    item = service.preview(payload(original))["items"][0]
    prop = item["property"]
    assert set(prop["fields"]) == set(FIELDS)
    assert prop["fields"]["租金"] == "8000"
    assert prop["fields"]["押金"] == "未揭露"
    assert prop["fields"]["設備"] == original["設備"]
    assert prop["fields"]["水費"] == original["水費"]
    assert prop["extra_fields"] == {"新欄位": original["新欄位"]}
    assert prop["original_ai_fields"] == original
    assert {w["code"] for w in item["warnings"]} >= {"MISSING_FIELD", "NEEDS_CONFIRMATION", "MISSING_RAW_TEXT"}
    assert all(w["index"] == 0 for w in item["warnings"])


def test_single_record_nested_extra_fields_not_mistaken_for_wrapper(service):
    original = {"租金": 8000, "data": [{"租金": "保留額外內容"}]}
    prop = service.preview(payload(original))["items"][0]["property"]
    assert prop["extra_fields"] == {"data": original["data"]}


@pytest.mark.parametrize("value,expected", [(8000, 8000), ("8000", 8000), ("8,000元/月", 8000),
    ("月租8000元", 8000), ("7500 元 / 月", 7500), (0, 0), (0.00001, 0.00001),
    ("5700～7700", None), ("10000或12000", None), ("待確認：8000", None),
    ("500元/日", None), ("96000元/年", None), ("8000元/月+管理費500元", None),
    ("8000元/月（含水）", None), ("未揭露", None), ("8000元", None)])
def test_rent_parsing(service, value, expected):
    result = service.preview(payload({"租金": value, "押金": 24000, "管理費": 500, "電費": 5}))
    assert result["can_commit"]
    assert result["items"][0]["property"]["rent_monthly"] == expected


@pytest.mark.parametrize("value", [-1, True, "-8000", "月租-8000元", "NaN", 10**400, {"value": 8000}])
def test_bad_rent_is_blocking(service, value):
    result = service.preview(payload({"租金": value}))
    assert not result["can_commit"]
    assert result["items"][0]["errors"][0]["field"] == "租金"


def test_multiple_row_errors_and_atomic_validation(service):
    data = [{"租金": 8000}, {"租金": True, "設備": ["冷氣", 1]}, "bad"]
    req = payload(data)
    result = service.preview(req)
    assert not result["can_commit"]
    assert {(e["index"], e["field"]) for i in result["items"] for e in i["errors"]} == {(1, "租金"), (1, "設備"), (2, None)}
    with pytest.raises(HousingError):
        service.commit({**req, "request_id": "bad-batch"})
    assert service.list_properties() == []


def test_aligned_metadata_and_wrapper_metadata_preserved(service):
    data = {"data": [{"租金": 8000}, {"租金": "未揭露"}], "version": {"blue": 3}}
    req = payload(data, metadata=[{"raw_text": "虛構原文 A", "source_url": "https://example.com/a"}, {"raw_text": "虛構原文 B"}])
    result = service.commit({**req, "request_id": "meta"})
    assert result["wrapper_metadata"] == {"version": {"blue": 3}}
    assert [p["raw_text"] for p in result["properties"]] == ["虛構原文 A", "虛構原文 B"]
    assert result["properties"][0]["fields"]["來源網址"] == "https://example.com/a"
    assert "來源網址" not in result["properties"][0]["original_ai_fields"]
    with pytest.raises(HousingError):
        service.preview(payload(data, metadata=[{"raw_text": "不可共用整批原文"}]))


def test_source_conflict_and_invalid_source(service):
    result = service.preview(payload({"租金": 8000, "來源網址": "https://example.com/a"},
                                    metadata=[{"source_url": "https://example.com/b"}]))
    prop = result["items"][0]["property"]
    assert prop["fields"]["來源網址"] == "https://example.com/a"
    assert prop["source_metadata"]["source_url"] == "https://example.com/b"
    assert any(w["code"] == "SOURCE_CONFLICT" for w in prop["warnings"])
    result = service.preview(payload({"來源網址": "javascript:alert(1)"}))
    assert any(w["code"] == "INVALID_SOURCE_URL" for w in result["items"][0]["warnings"])


def test_request_replay_conflict_and_concurrent_retry(service):
    req = payload({"租金": 8000}, request_id="retry")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(service.commit, [req, req]))
    assert sorted(r["replayed"] for r in results) == [False, True]
    assert results[0]["properties"][0]["id"] == results[1]["properties"][0]["id"]
    assert len(service.list_properties()) == 1
    with pytest.raises(HousingError) as exc:
        service.commit(payload({"租金": 9000}, request_id="retry"))
    assert exc.value.code == "IMPORT_REQUEST_CONFLICT"


def test_same_url_is_only_warning(service):
    records = [{"租金": 8000, "來源網址": "https://example.com/a"}, {"租金": 9000, "來源網址": "https://example.com/a"}]
    preview = service.preview(payload(records))
    assert all(any(w["code"] == "POSSIBLE_DUPLICATE" for w in i["warnings"]) for i in preview["items"])
    service.commit(payload(records, request_id="same-url"))
    assert len(service.list_properties()) == 2
    assert all(any(w["code"] == "POSSIBLE_DUPLICATE" for w in p["warnings"]) for p in service.list_properties())


def test_limits(service):
    for req in (payload([{"租金": 1}] * (MAX_BATCH + 1)), {"json_text": " " * (MAX_JSON_CHARS + 1)}):
        with pytest.raises(HousingError) as exc:
            service.preview(req)
        assert exc.value.code == "FIELD_VALIDATION_ERROR"


def test_actual_claude_pdf_fixture(service):
    """真實 AI 輸出格式回歸；不表示房源事實或現況已驗證。"""
    records = json.loads((Path(__file__).parent / "fixtures/claude_from_pdf.json").read_text(encoding="utf-8"))
    assert len(records) == 5
    assert all(set(row) == set(FIELDS) and all(isinstance(v, str) for v in row.values()) for row in records)
    result = service.preview(payload(records))
    assert result["can_commit"]
    props = [i["property"] for i in result["items"]]
    assert [p["rent_monthly"] for p in props] == [5000, 7500, 8880, None, None]
    assert all(p["original_ai_fields"] == row for p, row in zip(props, records))
    assert all(p["fields"]["設備"] == [row["設備"]] for p, row in zip(props, records))
    assert all(not p["reviewed"] for p in props)
