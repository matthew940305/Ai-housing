import pytest

from housing.errors import HousingError
from test_imports import payload


def test_edit_before_import_keeps_original_and_preview_does_not_save(service):
    original = {"租金": "待確認：8000或8500", "設備": "冷氣", "未知額外欄": [1, 2]}
    request = payload(original, edits=[{"fields": {"租金": "月租8500元", "設備": ["冷氣", "書桌"]}}])
    preview = service.preview(request)
    assert preview["can_commit"]
    prop = preview["items"][0]["property"]
    assert prop["original_ai_fields"] == original
    assert prop["fields"]["租金"] == "月租8500元"
    assert prop["rent_monthly"] == 8500
    assert prop["fields"]["設備"] == ["冷氣", "書桌"]
    assert prop["reviewed"] is False
    assert service.list_properties() == []
    # 「確認並儲存」按鈕才加入明確確認旗標。
    request["edits"][0]["reviewed"] = True
    saved = service.commit({**request, "request_id": "edited-import"})["properties"][0]
    assert saved["reviewed"] is True
    assert saved["original_ai_fields"] == original
    assert saved["extra_fields"] == {"未知額外欄": [1, 2]}
    assert service.get_property(saved["id"])["fields"]["租金"] == "月租8500元"
    assert len(service.list_properties()) == 1


def test_edits_can_correct_invalid_ai_field_without_losing_evidence(service):
    request = payload({"租金": True}, edits=[{"fields": {"租金": 8000}}])
    assert service.preview(request)["can_commit"]
    saved = service.commit({**request, "request_id": "fix-type"})["properties"][0]
    assert saved["fields"]["租金"] == "8000"
    assert saved["original_ai_fields"]["租金"] is True


@pytest.mark.parametrize("rent", [None, 8500])
def test_manual_pre_import_rent_stays_manual_after_later_edits(service, rent):
    request = payload({"租金": 8000}, edits=[{"rent_monthly": rent, "reviewed": True}])
    saved = service.commit({**request, "request_id": "manual-pre-import"})["properties"][0]
    assert saved["rent_monthly"] == rent
    assert saved["rent_monthly_source"] == "manual"
    updated = service.update_property(saved["id"], {"fields": {"租金": "月租9000元"}})
    assert updated["rent_monthly"] == rent and updated["reviewed"] is False


def test_batch_edits_are_index_aligned_and_invalid_edit_is_atomic(service):
    records = [{"租金": 8000}, {"租金": "範圍5700～7700"}]
    request = payload(records, edits=[None, {"rent_monthly": -1}])
    preview = service.preview(request)
    assert not preview["can_commit"]
    assert preview["items"][1]["errors"][0]["index"] == 1
    assert preview["items"][1]["errors"][0]["field"] == "rent_monthly"
    with pytest.raises(HousingError):
        service.commit({**request, "request_id": "bad-edit"})
    assert service.list_properties() == []
    request["edits"][1] = {"rent_monthly": 7000}
    saved = service.commit({**request, "request_id": "good-edit"})["properties"]
    assert [p["rent_monthly"] for p in saved] == [8000, 7000]
    assert [p["original_ai_fields"] for p in saved] == records


@pytest.mark.parametrize("edits", [[{"fields": {"id": "new"}}], [{"original_ai_fields": {}}],
                                  [{"reviewed": "true"}], [{"fields": {"設備": [1]}}],
                                  [{"rent_monthly": True}], ["bad"]])
def test_invalid_draft_is_reported_per_row(service, edits):
    result = service.preview(payload({"租金": 8000}, edits=edits))
    assert not result["can_commit"]
    assert result["items"][0]["errors"][0]["index"] == 0
    assert service.list_properties() == []


def test_edit_alignment_and_replay_identity(service):
    with pytest.raises(HousingError) as exc:
        service.preview(payload([{"租金": 8000}, {"租金": 9000}], edits=[{}]))
    assert exc.value.details[0]["field"] == "edits"
    request = payload({"租金": 8000}, edits=[{"fields": {"房型": "套房"}}], request_id="draft-retry")
    first = service.commit(request)
    assert service.commit(request)["replayed"] is True
    request["edits"][0]["fields"]["房型"] = "雅房"
    with pytest.raises(HousingError) as exc:
        service.commit(request)
    assert exc.value.code == "IMPORT_REQUEST_CONFLICT"
    assert service.get_property(first["properties"][0]["id"])["fields"]["房型"] == "套房"
