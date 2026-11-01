import json

from scripts import demo, export_data, import_json


def test_python_demo(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["demo"])
    demo.main()
    assert "完整流程 PASS" in capsys.readouterr().out


def test_export_script(service, tmp_path, monkeypatch, capsys):
    prop = service.create({"租金": 8000}, request_id="script-export")
    service.update_property(prop["id"], {"reviewed": True})
    target = tmp_path / "output/houses.json"
    monkeypatch.setattr("sys.argv", ["export_data", "--db-path", str(service.store.path), "--output", str(target), "--reviewed-only"])
    export_data.main()
    result = json.loads(target.read_text(encoding="utf-8"))
    assert result["count"] == 1
    assert result["properties"][0]["id"] == prop["id"]


def test_import_cli_preview_commit_and_replay(service, tmp_path, monkeypatch, capsys):
    source = tmp_path / "blue.json"
    source.write_text('[{"租金":8000}]', encoding="utf-8")
    args = ["import_json", "--json-file", str(source), "--db-path", str(service.store.path)]
    monkeypatch.setattr("sys.argv", args)
    import_json.main()
    assert json.loads(capsys.readouterr().out)["can_commit"]
    assert service.list_properties() == []
    monkeypatch.setattr("sys.argv", args + ["--commit", "--request-id", "cli-import"])
    import_json.main()
    assert json.loads(capsys.readouterr().out)["replayed"] is False
    import_json.main()
    assert json.loads(capsys.readouterr().out)["replayed"] is True
    assert len(service.list_properties()) == 1


def test_import_cli_separate_edits_preserve_original(service, tmp_path, monkeypatch, capsys):
    source, edits = tmp_path / "blue.json", tmp_path / "edits.json"
    source.write_text('[{"租金":8000}]', encoding="utf-8")
    edits.write_text('[{"fields":{"租金":"月租8500元"},"reviewed":true}]', encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["import_json", "--json-file", str(source), "--edits-file", str(edits),
                                    "--db-path", str(service.store.path), "--commit", "--request-id", "cli-draft"])
    import_json.main()
    result = json.loads(capsys.readouterr().out)["properties"][0]
    assert result["rent_monthly"] == 8500 and result["reviewed"] is True
    assert result["original_ai_fields"] == {"租金": 8000}
