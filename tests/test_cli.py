import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples/communication_mod_combat.json"


def test_mock_cli_without_keys_or_network_appends_records(tmp_path):
    # Fresh interpreter: importing an SDK OR opening a socket fails the test.
    script = '''
import sys
def deny(event, args):
    if event.startswith("socket."):
        raise AssertionError("mock attempted network access")
    if event == "import" and args[0].split(".")[0] in {"typesafe_sdk", "httpx2"}:
        raise AssertionError("mock imported a network SDK")
sys.addaudithook(deny)
from slay_jev_spire.cli import main
raise SystemExit(main(sys.argv[1:]))
'''
    env = {k: v for k, v in os.environ.items() if k not in {"TYPESAFE_API_KEY", "DEEPSEEK_API_KEY"}}
    env["PYTHONIOENCODING"] = "utf-8"
    log = tmp_path / "decisions.jsonl"
    for _ in range(2):
        result = subprocess.run(
            [sys.executable, "-c", script, "--mode", "mock", "--log", str(log)],
            cwd=ROOT, env=env, encoding="utf-8", capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        assert "PLAN" in result.stdout
        assert "mock" in result.stdout
        assert str(log) in result.stdout
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    for record in records:
        assert record["raw_state"] == json.loads(SAMPLE.read_text(encoding="utf-8"))
        assert record["mode"] == "mock"
        assert record["decision"]["action"] in record["candidates"]
        assert record["decision"]["action"]["command"] == "PLAN"
        assert record['schema_version'] == 2 and record['search']['beam_width'] == 32
        assert "map" not in record["summary"]
        assert record["instructions"]
        assert record["decision"]["returned_model"] is None


def test_jev_missing_key_does_not_write_record(monkeypatch, tmp_path, capsys):
    from slay_jev_spire.cli import main

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    from slay_jev_spire import config
    from slay_jev_spire.selectors import SelectionError
    def no_key():
        raise SelectionError('Missing TYPESAFE_API_KEY')
    monkeypatch.setattr(config, 'load_jev_key', no_key)
    log = tmp_path / "missing.jsonl"
    assert main(["--mode", "jev", "--log", str(log)]) == 1
    assert "TYPESAFE_API_KEY" in capsys.readouterr().err
    assert not log.exists()
