"""离线 CLI 控制层：解析参数、读取样本、协调模块、展示结果与错误。"""

import argparse
import json
from pathlib import Path
import sys
import subprocess
from getpass import getpass

from .models import Action, Decision
from .records import append_record, build_record, safe_text
from .selectors import INSTRUCTIONS, SelectionError, choose_jev, choose_mock
from .state import UnsupportedState, prepare_state
from .turn_planner import generate_plans, SearchConfig


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


def _command(argv):
    command, *remaining = argv
    if command == 'agent':
        from .transport.communication_mod import main as agent
        return agent(remaining)
    parser = argparse.ArgumentParser(prog='main.py ' + command)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'logs/live')
    if command == 'resume': parser.add_argument('--budget', type=int, default=500)
    if command == 'play':
        parser.add_argument('--new', action='store_true')
        parser.add_argument('--combat-only', action='store_true')
        parser.add_argument('--seed')
        parser.add_argument('--beam-width', type=int, default=32)
    if command == 'report':
        parser.add_argument('--run-id')
        parser.add_argument('--expected', type=int, default=10)
    args = parser.parse_args(remaining)
    live = args.output_dir
    if command == 'configure':
        from .config import save_jev_key
        save_jev_key(getpass('Jev API key (hidden): '))
        print('Key saved with Windows user encryption.')
    elif command == 'play':
        SearchConfig(beam_width=args.beam_width)
        invocation = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'tools/launch_jev.ps1'),
                      '-BeamWidth', str(args.beam_width)]
        if args.new: invocation += ['-StartNew']
        if args.combat_only: invocation += ['-CombatOnly']
        if args.seed: invocation += ['-Seed', args.seed]
        return subprocess.call(invocation)
    elif command in {'pause', 'resume'}:
        live.mkdir(parents=True, exist_ok=True)
        (live / 'pause.flag').write_text('pause', encoding='utf-8')
        if command == 'resume':
            if not 1 <= args.budget <= 2000: parser.error('budget must be 1–2000')
            (live / 'resume.flag').write_text(str(args.budget), encoding='utf-8')
        print(command + ' requested')
    elif command in {'status', 'report'}:
        from .records import battle_metrics
        path = live / 'runs.jsonl'
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        if command == 'report':
            if args.run_id: rows = [r for r in rows if r.get('run_id') == args.run_id]
            result = battle_metrics(rows, expected=args.expected)
        else:
            result = {k: rows[-1].get(k) for k in ('timestamp', 'run_id', 'status', 'reason', 'calls', 'actions')} if rows else {}
            result['is_snapshot'] = True
        print(safe_text(json.dumps(result, ensure_ascii=False, indent=2)))
    return 0


def main(argv: list[str] | None = None) -> int:
    """协调一次离线决策；成功返回 0，预期运行错误返回 1。

    顺序为读取 → 状态适配 → 展示候选 → 选择 → 保存 → 展示结果。
    CLI 不实现出牌规则、模型协议或记录格式。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == 'benchmark':
        return subprocess.call([sys.executable, str(ROOT / 'tools/benchmark.py'), *argv[1:]])
    if argv and argv[0] in {'configure', 'play', 'pause', 'resume', 'status', 'report', 'agent'}:
        try:
            return _command(argv)
        except (OSError, ValueError) as error:
            print(safe_text(str(error)), file=sys.stderr)
            return 1
    if argv and argv[0] == 'replay': argv.pop(0)
    args = _parse_args(argv)

    try:
        # A mistaken output path must never append logs to the input fixture.
        if args.state.resolve() == args.log.resolve():
            raise SelectionError("样本文件与记录文件不能使用同一路径。")
        raw = load_state(args.state)
        summary, candidates = prepare_state(raw)
        candidates, search = generate_plans(summary, candidates)
        if not candidates: raise UnsupportedState('No turn plans generated.')
        _print_candidates(summary, candidates)

        if args.mode == 'jev':
            from .config import load_jev_key
            load_jev_key()
        decision = (choose_mock if args.mode == "mock" else choose_jev)(summary, candidates)
        record = build_record(raw, summary, candidates, decision, args.mode, INSTRUCTIONS)
        record.update(schema_version=2, search=search)
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
