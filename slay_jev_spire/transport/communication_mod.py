"""接收逐行 JSON，默认仅采集；可选单步或一场战斗执行。"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from queue import Queue, Empty
from threading import Thread

from ..records import append_record, build_record, safe_text
from ..config import load_jev_key
from ..selectors import INSTRUCTIONS, SelectionError, choose_jev, choose_mock
from ..state import UnsupportedState, prepare_state
from ..session import CombatSession
from ..session import RunSession
from ..session import handle_resume_request
from ..turn_planner import SearchConfig


ROOT = Path(__file__).resolve().parents[2]


class _InputMessages:
    """后台管道读者；恢复时显式排空缓存，再请求新的 STATE。"""

    def __init__(self):
        self.incoming = Queue()
        self.finished = object()
        stream = sys.stdin

        def read():
            try:
                for line in stream:
                    self.incoming.put(line)
            except (OSError, UnicodeError) as error:
                self.incoming.put(error)
            finally:
                self.incoming.put(self.finished)
        Thread(target=read, daemon=True).start()

    def __iter__(self):
        while True:
            try:
                message = self.incoming.get(timeout=0.25)
            except Empty:
                yield None
                continue
            if message is self.finished:
                return
            if isinstance(message, Exception):
                raise message
            yield message

    def discard_pending(self):
        # 短暂安静窗口让读线程也排空操作系统管道；不依赖“下一行即响应”。
        deadline = time.monotonic() + 5
        while True:
            if time.monotonic() >= deadline:
                raise OSError('Input backlog did not become quiet.')
            try:
                message = self.incoming.get(timeout=0.25)
            except Empty:
                return
            if message is self.finished:
                self.incoming.put(message)
                return
            if isinstance(message, Exception):
                raise message


def _input_messages():
    return _InputMessages()


def _publish_snapshot(output_dir, snapshot):
    temporary = output_dir / 'latest_state.json.tmp'
    temporary.write_text(snapshot + '\n', encoding='utf-8')
    for attempt in range(8):
        try:
            temporary.replace(output_dir / 'latest_state.json')
            return
        except PermissionError:
            # Windows readers can briefly prevent replacing an open file.
            if attempt == 7: raise
            time.sleep(0.02)


def main(argv: list[str] | None = None) -> int:
    """刷新握手与一次 STATE 请求，保存后续状态直到游戏关闭输入管道。

    使用项目绝对路径定位日志，不依赖游戏的工作目录。stdout 只输出
    协议；初始化或解析失败时退出，避免向游戏发送无效文本。
    """
    parser = argparse.ArgumentParser(description='CommunicationMod 状态采集')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'logs' / 'live')
    parser.add_argument('--input-encoding', choices=('utf-8', 'gbk'), default='utf-8',
                        help='必须匹配游戏 Java 的 file.encoding；日志仍保存为 UTF-8')
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument('--execute-once', choices=('mock', 'jev'),
                        help='在首次支持的稳定战斗状态选择并执行一次，随后继续采集')
    mode_group.add_argument('--combat', choices=('mock', 'jev'), help='仅自动完成第一场支持的战斗')
    mode_group.add_argument('--run', choices=('mock', 'jev'), help='跨支持战斗、奖励与地图的有界执行')
    parser.add_argument('--start-new', action='store_true', help='明确开始铁甲战士 A0 新局，仅配合 --run')
    parser.add_argument('--max-decisions', type=int, default=None, help='API 请求预算：整局默认 500，单场默认 20')
    parser.add_argument('--beam-width', type=int, default=32)
    parser.add_argument('--seed', help='新局固定种子')
    args = parser.parse_args(argv)
    if args.start_new and not (args.run or args.combat):
        parser.error('--start-new 必须配合 --run 或 --combat')
    if args.max_decisions is None:
        args.max_decisions = 500 if args.run else 20
    maximum = 2000
    if not 1 <= args.max_decisions <= maximum:
        parser.error(f'--max-decisions 必须为 1–{maximum}')
    sys.stdin.reconfigure(encoding=args.input_encoding, errors='strict')
    attempted = False
    awaiting_response = False
    pending = None
    initially_refreshed = False
    refresh_started = None
    session = None
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        if args.run:
            session = RunSession(args.output_dir, args.run, args.max_decisions, start_new=args.start_new, seed=args.seed, search_config=SearchConfig(beam_width=args.beam_width))
        elif args.combat:
            session = RunSession(args.output_dir, args.combat, args.max_decisions, start_new=args.start_new, seed=args.seed, stop_after_combat=True, search_config=SearchConfig(beam_width=args.beam_width))
        # 在握手前验证输出权限；状态日志采用追加方式保留历次采集。
        with (args.output_dir / 'states.jsonl').open('a', encoding='utf-8') as stream:
            print('ready', flush=True)
            print('STATE', flush=True)
            messages = _input_messages() if session else sys.stdin
            for line in messages:
                if args.run or args.combat:
                    try:
                        session, resumed = handle_resume_request(session, args.max_decisions)
                    except Exception:
                        print('恢复失败：仍然暂停，请检查代码或状态。', file=sys.stderr, flush=True)
                        resumed = False
                    if resumed:
                        messages.discard_pending()
                        print('STATE', flush=True)
                        # 丢弃可能来自旧控制器的缓存消息，先获取新的状态。
                        continue
                    if getattr(session, 'resume_query_pending', False):
                        session.resume_query_pending = False
                        print('STATE', flush=True)
                if line is None:
                    session.tick()
                    continue
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    raise ValueError('协议状态必须是 JSON 对象。')
                snapshot = safe_text(json.dumps(raw, ensure_ascii=False, allow_nan=False))
                record = {'timestamp': datetime.now(timezone.utc).isoformat(), 'raw_state': raw}
                stream.write(safe_text(json.dumps(record, ensure_ascii=False, allow_nan=False)) + '\n')
                stream.flush()
                _publish_snapshot(args.output_dir, snapshot)
                if session:
                    for command in session.receive(raw):
                        print(command, flush=True)
                        if command != 'STATE':
                            session.command_sent(command)
                    continue
                if pending is not None:
                    original, decision = pending
                    pending = None
                    if raw != original:
                        append_record(args.output_dir / 'executions.jsonl', {
                            'timestamp': datetime.now(timezone.utc).isoformat(),
                            'status': 'cancelled_state_changed',
                        })
                        continue
                    print(decision['action']['command'], flush=True)
                    append_record(args.output_dir / 'executions.jsonl', {
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'status': 'sent', 'command': decision['action']['command'],
                    })
                    awaiting_response = True
                    continue
                if awaiting_response and (raw.get('error') or raw.get('ready_for_command') is True):
                    append_record(args.output_dir / 'executions.jsonl', {
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'status': 'error' if raw.get('error') else 'response_received',
                        'raw_state': raw,
                    })
                    awaiting_response = False
                if args.execute_once and not attempted:
                    try:
                        summary, candidates = prepare_state(raw)
                    except UnsupportedState:
                        continue
                    if args.execute_once == 'jev' and not initially_refreshed:
                        initially_refreshed = True
                        refresh_started = time.monotonic()
                        print('STATE', flush=True)
                        continue
                    if args.execute_once == 'jev' and any(e['intent'] == 'DEBUG' for e in summary['enemies']):
                        if time.monotonic() - refresh_started >= 15:
                            raise SelectionError('怪物意图仍为加载占位 DEBUG；等待超时，未请求 Jev。')
                        time.sleep(0.2)
                        print('STATE', flush=True)
                        continue
                    attempted = True
                    if args.execute_once == 'jev':
                        load_jev_key()
                    decision = (choose_jev if args.execute_once == 'jev' else choose_mock)(summary, candidates)
                    append_record(args.output_dir / 'decisions.jsonl',
                                  build_record(raw, summary, candidates, decision, args.execute_once, INSTRUCTIONS))
                    if args.execute_once == 'jev':
                        pending = (raw, decision)
                        print('STATE', flush=True)
                        continue
                    # 执行之前保存决策；仅发送程序生成的候选，不接收任意命令文本。
                    print(decision['action']['command'], flush=True)
                    append_record(args.output_dir / 'executions.jsonl', {
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'status': 'sent', 'command': decision['action']['command'],
                    })
                    awaiting_response = True
        return 0
    except SelectionError as error:
        print(safe_text(f'决策停止：{error}'), file=sys.stderr, flush=True)
    except (ValueError, UnicodeError):
        print('采集停止：收到无效 JSON 状态。', file=sys.stderr, flush=True)
    except OSError as error:
        if session is not None:
            try:
                session._stop('transport_error', message=safe_text(str(error)))
            except OSError:
                pass
        print(safe_text(f'采集停止：无法读写协议管道或状态文件：{error}'), file=sys.stderr, flush=True)
    return 1
