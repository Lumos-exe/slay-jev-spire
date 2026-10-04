"""一场战斗的有界决策循环；传输层只负责传递命令和游戏状态。"""

from datetime import datetime, timezone
from pathlib import Path
import time
from uuid import uuid4

from .config import load_jev_key
from .records import append_record, build_record
from .selectors import INSTRUCTIONS, SelectionError, choose_jev, choose_mock
from .state import UnsupportedState, prepare_state


class CombatSession:
    """刷新、选择、校验、发送、确认循环；停止后持续仅采集。"""

    def __init__(self, output_dir: Path, mode: str = 'jev', max_decisions: int = 20, selector=None):
        self.output_dir = output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        self.selector = selector or (choose_jev if mode == 'jev' else choose_mock)
        self.max_decisions = max_decisions
        self.calls = self.actions = 0
        self.stopped = False
        self.reason = None
        self.phase = 'waiting_battle'
        self.battle = None
        self.pending = None
        self.sent = None
        self.deadline = None
        self.id = str(uuid4())
        self._record('created')

    def _record(self, status: str, **fields) -> None:
        """保存会话状态和动作计数；密钥脱敏复用记录边界。"""
        append_record(self.output_dir / 'sessions.jsonl', {
            'timestamp': datetime.now(timezone.utc).isoformat(), 'session_id': self.id,
            'mode': self.mode, 'status': status, 'calls': self.calls, 'actions': self.actions,
            **fields,
        })

    def _stop(self, reason: str, **fields) -> list[str]:
        """停止自动操作，不阻止传输入口继续采集。"""
        self.stopped = True
        self.reason = reason
        self._record('stopped', reason=reason, **fields)
        return []

    def command_sent(self, command: str) -> None:
        """由传输层在刷新命令到 stdout 后确认发送，不视为执行成功。"""
        self._record('command_sent', command=command)

    def tick(self) -> list[str]:
        """在等待输入时检查暂停文件和状态/回传超时。"""
        if self.stopped:
            return []
        if (self.output_dir / 'pause.flag').exists():
            return self._stop('paused')
        if self.deadline is not None and time.monotonic() >= self.deadline:
            return self._stop('state_timeout')
        return []

    def receive(self, raw: dict) -> list[str]:
        """处理一条游戏消息；只返回程序生成的协议命令。"""
        self.tick()
        if self.stopped:
            return []
        if raw.get('error'):
            return self._stop('game_error')
        game = raw.get('game_state', {})
        if self.battle is not None:
            identity = (game.get('seed'), game.get('floor'), game.get('room_type'))
            if raw.get('in_game') is not True:
                return self._stop('left_game')
            if identity != self.battle:
                return self._stop('battle_changed')
            player_hp = game.get('current_hp')
            if game.get('room_phase') == 'COMPLETE' or game.get('screen_type') in {'COMBAT_REWARD', 'GAME_OVER'} or player_hp == 0:
                return self._stop('battle_finished')
        if raw.get('ready_for_command') is not True:
            return []
        if self.battle is None and game.get('room_phase') != 'COMBAT':
            return []
        if game.get('action_phase') != 'WAITING_ON_USER':
            return []
        try:
            summary, candidates = prepare_state(raw)
        except UnsupportedState as error:
            return self._stop('unsupported_state', message=str(error))
        if self.battle is None:
            self.battle = (game.get('seed'), game.get('floor'), game.get('room_type'))
            self.phase = 'refreshing'
            self.deadline = time.monotonic() + 15
            self._record('battle_started', battle=self.battle)
            return ['STATE']
        if self.phase == 'confirming':
            before, decision = self.sent
            if raw == before:
                time.sleep(0.2)
                return ['STATE']
            action = decision['action']
            if action['command'] == 'END':
                confirmed = summary['turn'] > before['game_state']['combat_state']['turn']
            else:
                confirmed = action['card_uuid'] not in {c['card_uuid'] for c in summary['hand']}
            if not confirmed:
                return self._stop('unconfirmed_execution')
            self._record('action_confirmed', command=action['command'])
            self.phase = 'ready'
            self.deadline = None
        if self.phase == 'checking':
            before, decision = self.pending
            if raw != before:
                return self._stop('state_changed')
            self.tick()
            if self.stopped:
                return []
            self.sent = (raw, decision)
            self.phase = 'confirming'
            self.deadline = time.monotonic() + 30
            self.actions += 1
            self._record('command_prepared', command=decision['action']['command'])
            return [decision['action']['command']]
        if any(e['intent'] == 'DEBUG' and e['current_hp'] > 0 for e in summary['enemies']):
            if self.deadline is None:
                self.deadline = time.monotonic() + 15
            time.sleep(0.2)
            return ['STATE']
        self.deadline = None
        if self.calls >= self.max_decisions:
            return self._stop('decision_limit')
        try:
            if self.mode == 'jev':
                load_jev_key()
            self.calls += 1
            self._record('request_started')
            decision = self.selector(summary, candidates)
            append_record(self.output_dir / 'decisions.jsonl',
                          build_record(raw, summary, candidates, decision, self.mode, INSTRUCTIONS))
        except SelectionError as error:
            return self._stop('selection_error', message=str(error))
        self.tick()
        if self.stopped:
            return []
        self.pending = (raw, decision)
        self.phase = 'checking'
        self.deadline = time.monotonic() + 15
        return ['STATE']
