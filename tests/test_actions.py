"""候选生成模块的独立测试：只消费摘要，不接触原始协议或 I/O。"""

import copy
import json
from pathlib import Path


def test_generate_actions_preserves_inputs_and_original_indices():
    from slay_jev_spire.actions import generate_actions
    from slay_jev_spire.state import prepare_state

    sample = Path(__file__).resolve().parents[1] / "samples/communication_mod_combat.json"
    raw = json.loads(sample.read_text(encoding="utf-8"))
    summary, expected = prepare_state(raw)
    original = copy.deepcopy(summary)
    assert generate_actions(summary, ["play", "end"]) == expected
    assert summary == original
    assert generate_actions(summary, []) == []
