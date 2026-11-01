import pytest

from housing.errors import HousingError
from housing.service import HousingService
from test_imports import payload


def test_update_immutability_review_and_persistence(service):
    original = {"租金": 8000, "設備": "冷氣", "額外": {"a": 1}}
    prop = service.create(original, raw_text="虛構原文", request_id="create")
    key = prop["id"]
    confirmed = service.update_property(key, {"reviewed": True})
    assert confirmed["reviewed"] is True
    updated = service.update_property(key, {"fields": {"租金": "月租9000元", "設備": ["冷氣", "洗衣機"]}})
    assert updated["id"] == key
    assert updated["created_at"] == prop["created_at"]
    assert updated["updated_at"] > prop["updated_at"]
    assert updated["original_ai_fields"] == original
    assert updated["extra_fields"] == {"額外": {"a": 1}}
    assert updated["rent_monthly"] == 9000
    assert updated["reviewed"] is False
    assert len(service.list_properties()) == 1
    # 初始化可重複、每個方法皆重新建立連線。
    reopened = HousingService(service.store.path)
    assert reopened.get_property(key) == updated
    assert len(reopened.list_properties()) == 1
    replay = reopened.commit(payload(original, metadata=[{"raw_text": "虛構原文", "source_url": None}], request_id="create"))
    assert replay["replayed"] is True
    assert replay["properties"][0]["rent_monthly"] == 9000


def test_manual_override_clear_is_sticky(service):
    prop = service.create({"租金": 8000}, request_id="manual")
    key = prop["id"]
    for value in (8500, None, 0):
        result = service.update_property(key, {"rent_monthly": value})
        assert result["rent_monthly"] == value
        assert result["rent_monthly_source"] == "manual"
        result = service.update_property(key, {"fields": {"租金": "月租9000元" if value != 0 else "月租10000元"}})
        assert result["rent_monthly"] == value
        assert result["rent_monthly_source"] == "manual"


@pytest.mark.parametrize("value", [-1, True, float("nan"), float("inf"), -float("inf"), "8000", 10**400])
def test_invalid_manual_rent_does_not_mutate(service, value):
    prop = service.create({"租金": 8000}, request_id="bad-manual")
    with pytest.raises(HousingError):
        service.update_property(prop["id"], {"rent_monthly": value})
    assert service.get_property(prop["id"]) == prop


def test_review_requires_distinct_confirmation(service):
    prop = service.create({"租金": 8000}, request_id="review")
    key = prop["id"]
    with pytest.raises(HousingError):
        service.update_property(key, {"fields": {"房型": "套房"}, "reviewed": True})
    assert service.get_property(key) == prop
    prop = service.update_property(key, {"fields": {"房型": "套房"}})
    assert prop["reviewed"] is False
    assert service.update_property(key, {"reviewed": True})["reviewed"] is True
    assert service.update_property(key, {"raw_text": "虛構補充原文"})["reviewed"] is False
    service.update_property(key, {"reviewed": True})
    assert service.update_property(key, {"rent_monthly": None})["reviewed"] is False


@pytest.mark.parametrize("patch", [{"id": "new"}, {"created_at": "now"}, {"original_ai_fields": {}},
                                  {"extra_fields": {}}, {"fields": {"new": 1}}, {"reviewed": "true"},
                                  {"fields": {"設備": [1]}}, {"fields": {"租金": "-1"}}, {}])
def test_bad_patch(service, patch):
    prop = service.create({"租金": 8000}, request_id="bad-patch")
    with pytest.raises(HousingError) as exc:
        service.update_property(prop["id"], patch)
    assert exc.value.code == "FIELD_VALIDATION_ERROR"
    assert service.get_property(prop["id"]) == prop


def test_unknown_id_does_not_create(service):
    for method in (lambda: service.get_property("missing"), lambda: service.update_property("missing", {"reviewed": True})):
        with pytest.raises(HousingError) as exc:
            method()
        assert exc.value.code == "PROPERTY_NOT_FOUND"
    assert service.list_properties() == []


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_create_nonfinite_uses_domain_error(service, value):
    with pytest.raises(HousingError) as exc:
        service.create({"租金": value}, request_id="nonfinite-create")
    assert exc.value.code == "FIELD_VALIDATION_ERROR"
    assert service.list_properties() == []


def test_db_transaction_rolls_back_after_second_insert_failure(service):
    # 真正觸發 SQLite 第二筆 INSERT 失敗，驗證非僅輸入驗證的回滾。
    with service.store.connection(write=True) as conn:
        conn.execute("CREATE TRIGGER fail_second BEFORE INSERT ON properties WHEN (SELECT COUNT(*) FROM properties) >= 1 BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    req = payload([{"租金": 8000}, {"租金": 9000}], request_id="rollback")
    with pytest.raises(HousingError) as exc:
        service.commit(req)
    assert exc.value.code == "DATABASE_ERROR"
    assert service.list_properties() == []
    with service.store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM import_requests").fetchone()[0] == 0
    with service.store.connection(write=True) as conn:
        conn.execute("DROP TRIGGER fail_second")
    assert service.commit(req)["count"] == 2


def test_filter_and_unknown_last_in_both_directions(service):
    props = service.commit(payload([{"租金": 9000}, {"租金": "未揭露"}, {"租金": 8000}, {"租金": 0}], request_id="filter"))["properties"]
    assert [p["rent_monthly"] for p in service.list_properties()] == [0, 8000, 9000, None]
    assert [p["rent_monthly"] for p in service.list_properties(sort="rent_desc")] == [9000, 8000, 0, None]
    assert [p["rent_monthly"] for p in service.list_properties(min_rent=8000, max_rent=8500)] == [8000]
    assert [p["rent_monthly"] for p in service.list_properties(min_rent=8000, max_rent=8500, include_unknown=True)] == [8000, None]
    service.update_property(props[0]["id"], {"reviewed": True})
    assert len(service.list_properties(reviewed=True)) == 1
    assert len(service.list_properties(reviewed=False)) == 3
    for kwargs in ({"min_rent": 9000, "max_rent": 8000}, {"min_rent": -1}, {"max_rent": float("nan")}, {"sort": "invalid"}):
        with pytest.raises(HousingError):
            service.list_properties(**kwargs)
