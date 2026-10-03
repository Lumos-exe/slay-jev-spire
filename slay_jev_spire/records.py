"""构造与追加单步记录，并提供终端和 JSONL 共用的密钥脱敏。"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from .models import Action, Decision, DecisionRecord


def safe_text(text: str) -> str:
    """替换文本中的已配置密钥及其 JSON 转义形式；不修改环境。"""
    secrets = set()
    for variable in ("TYPESAFE_API_KEY", "DEEPSEEK_API_KEY"):
        secret = os.environ.get(variable, "").strip()
        if secret:
            secrets.update((secret, json.dumps(secret, ensure_ascii=False)[1:-1]))
    # 先替换长密钥，避免一个密钥恰好包含另一个时只被部分遮盖。
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def build_record(
    raw_state: dict,
    summary: dict,
    candidates: list[Action],
    decision: Decision,
    mode: str,
    instructions: str,
) -> DecisionRecord:
    """组合单步输入输出并添加 UTC 时间；不写文件、不拷贝或修改输入。"""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(), "mode": mode,
        "raw_state": raw_state, "summary": summary, "instructions": instructions,
        "candidates": candidates, "decision": decision,
    }


def append_record(path: Path, record: DecisionRecord) -> None:
    """创建父目录并追加一行脱敏 JSON；序列化或文件错误由调用者处理。"""
    line = safe_text(json.dumps(record, ensure_ascii=False, allow_nan=False))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
