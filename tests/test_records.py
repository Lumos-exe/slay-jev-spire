"""记录模块的独立测试：构造记录、脱敏与追加写入。"""

import json


def test_build_and_append_record_with_redaction(tmp_path, monkeypatch):
    from slay_jev_spire.records import append_record, build_record

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-secret")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-secret")
    action = {"id": "end", "command": "END", "description": "结束回合",
              "hand_index": None, "card_uuid": None, "target_index": None}
    decision = {"action": action, "requested_model": None,
                "returned_model": None, "confidence": None}
    raw = {"name": "test-secret", "other": "deepseek-test-secret"}
    record = build_record(raw, {"turn": 1}, [action], decision, "mock", "选择候选")
    assert record["raw_state"] is raw
    assert record["decision"] is decision
    assert record["instructions"] == "选择候选"
    assert record["timestamp"]
    path = tmp_path / "logs" / "decisions.jsonl"
    append_record(path, record)
    append_record(path, record)
    text = path.read_text(encoding="utf-8")
    assert "test-secret" not in text
    assert "deepseek-test-secret" not in text
    rows = [json.loads(line) for line in text.splitlines()]
    assert len(rows) == 2
    assert rows[0]["raw_state"] == {"name": "[REDACTED]", "other": "[REDACTED]"}
    assert rows[0]["decision"]["action"] in rows[0]["candidates"]
