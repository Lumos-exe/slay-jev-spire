"""模块之间共享的数据契约；TypedDict 保持原有 JSON 字典格式。"""

from typing import TypedDict


class Action(TypedDict):
    """程序生成的候选：ID、命令、说明及原始牌/目标位置。"""

    id: str
    command: str
    description: str
    hand_index: int | None
    card_uuid: str | None
    target_index: int | None


class Decision(TypedDict):
    """选择器返回的结果：原候选及模型元数据，模拟时元数据为空。"""

    action: Action
    requested_model: str | None
    returned_model: str | None
    confidence: float | None


class DecisionRecord(TypedDict):
    """可写入 JSONL 的单步记录；包含输入、摘要、候选和选择。"""

    timestamp: str
    mode: str
    raw_state: dict
    summary: dict
    instructions: str
    candidates: list[Action]
    decision: Decision
