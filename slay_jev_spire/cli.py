"""离线 CLI 控制层：解析参数、读取样本、协调模块、展示结果与错误。"""

import argparse
import json
from pathlib import Path
import sys

from .models import Action, Decision
from .records import append_record, build_record, safe_text
from .selectors import INSTRUCTIONS, SelectionError, choose_jev, choose_mock
from .state import UnsupportedState, prepare_state


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "samples" / "communication_mod_combat.json"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """解析模式、样本和记录路径；非法命令行参数由 argparse 提示。"""
    parser = argparse.ArgumentParser(description="Slay Jev Spire：离线单步选择（不执行游戏命令）")
    parser.add_argument("--mode", choices=("mock", "jev"), default="mock")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="CommunicationMod JSON 样本")
    parser.add_argument("--log", type=Path, default=Path("logs/decisions.jsonl"), help="追加写入的 JSONL")
    return parser.parse_args(argv)


def load_state(path: Path) -> dict:
    """读取 UTF-8 JSON 样本；协议结构校验交给 state.prepare_state。"""
    return json.loads(path.read_text(encoding="utf-8"))


def _print_candidates(summary: dict, candidates: list[Action]) -> None:
    """向终端展示脱敏摘要、候选 ID、命令与说明。"""
    print("示例局面（CommunicationMod 离线快照）：")
    print(safe_text(json.dumps(summary, ensure_ascii=False, indent=2)))
    print("\n候选动作（仅展示，不执行）：")
    for action in candidates:
        print(safe_text(f"  {action['id']}: {action['command']} — {action['description']}"))


def _print_decision(mode: str, decision: Decision, log_path: Path) -> None:
    """记录写入成功后，向终端展示选择、模型信息与记录路径。"""
    action = decision["action"]
    print(safe_text(f"\n选择 [{mode}]: {action['id']} → {action['command']}"))
    if mode == "jev":
        print(safe_text(f"返回模型: {decision['returned_model']}；置信度: {decision['confidence']}"))
    print(safe_text(f"记录文件: {log_path.resolve()}"))


def main(argv: list[str] | None = None) -> int:
    """协调一次离线决策；成功返回 0，预期运行错误返回 1。

    顺序为读取 → 状态适配 → 展示候选 → 选择 → 保存 → 展示结果。
    CLI 不实现出牌规则、模型协议或记录格式。
    """
    args = _parse_args(argv)

    try:
        # A mistaken output path must never append logs to the input fixture.
        if args.state.resolve() == args.log.resolve():
            raise SelectionError("样本文件与记录文件不能使用同一路径。")
        raw = load_state(args.state)
        summary, candidates = prepare_state(raw)
        _print_candidates(summary, candidates)

        decision = (choose_mock if args.mode == "mock" else choose_jev)(summary, candidates)
        record = build_record(raw, summary, candidates, decision, args.mode, INSTRUCTIONS)
        append_record(args.log, record)
        _print_decision(args.mode, decision, args.log)
        return 0
    except (UnsupportedState, SelectionError) as error:
        print(safe_text(f"错误：{error}"), file=sys.stderr)
    except (json.JSONDecodeError, UnicodeError):
        print("错误：样本必须是 UTF-8 编码的有效 JSON。", file=sys.stderr)
    except OSError:
        print("错误：无法读取样本或写入记录；请检查路径和权限。", file=sys.stderr)
    return 1
