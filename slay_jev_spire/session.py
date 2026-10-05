"""一场战斗的有界决策循环；传输层只负责传递命令和游戏状态。"""

from datetime import datetime, timezone
from pathlib import Path
import time
from uuid import uuid4
from .config import load_jev_key
from .records import append_record, build_record, source_manifest
from .selectors import INSTRUCTIONS, SelectionError, choose_jev, choose_mock
from .state import UnsupportedState, prepare_state
from collections import Counter
from copy import deepcopy
import json
import os
from .screens import prepare_journey
from .records import append_record
from .selectors import INSTRUCTIONS, SelectionError, validate_choice, instructions_for
from .state import UnsupportedState
from .state import load_catalog, enrich_summary
from .screens import confirm_screen
from .turn_planner import generate_plans, bind_plan_step, SearchConfig, fingerprint, battle_projection
import importlib

LOADED_COMPONENTS = source_manifest()




class SessionRuntime:
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




def gameplay_state(value):
    """Ignore card highlighting and fully gone monsters' delayed power cleanup."""
    if isinstance(value, list):
        return [gameplay_state(item) for item in value]
    if isinstance(value, dict):
        result = {k: gameplay_state(v) for k, v in value.items()}
        native = result.get('native_values')
        if isinstance(native, dict):
            for flag in ('damage_modified', 'block_modified', 'magic_number_modified'):
                native.pop(flag, None)
        combat = result.get('combat_state')
        if isinstance(combat, dict):
            for monster in combat.get('monsters', []):
                if (monster.get('current_hp') == 0 and monster.get('is_gone') is True
                        and monster.get('half_dead') is False):
                    monster.pop('powers', None)
        return result
    return value


class DecisionMemory:
    def __init__(self):
        self.declined = set()
        self.recent = []
        self.visits = Counter()
        self.repeated_requests = 0
        self.opened_reward = None
        self.inspected_shops = set()

    @staticmethod
    def location(game):
        return (game.get('act'), game.get('floor'))

    def observe(self, before, after, decision):
        action = decision['action']
        game = before.get('game_state', {})
        for observed in (game, after.get('game_state', {})):
            if observed.get('screen_type') == 'SHOP_SCREEN':
                self.inspected_shops.add(self.location(observed))
        kind = action.get('kind')
        if kind == 'reward' and action.get('reward', {}).get('reward_type') == 'CARD':
            # Multiple anonymous CARD entries cannot safely be distinguished after removal.
            count = sum(r.get('reward_type') == 'CARD' for r in game.get('screen_state', {}).get('rewards', []))
            self.opened_reward = (self.location(game), count == 1)
        if kind in {'skip', 'card', 'bowl'}:
            if kind == 'skip' and self.opened_reward == (self.location(game), True):
                self.declined.add(self.location(game))
            self.opened_reward = None
        played = next((c for c in game.get('combat_state',{}).get('hand',[]) if c.get('uuid') == action.get('card_uuid')), {})
        self.recent.append({'floor': game.get('floor'), 'screen_type': game.get('screen_type'),
                            'command': action['command'], 'kind': kind,
                            'card_id': played.get('id'), 'potion_id': action.get('potion_id')})
        self.recent = self.recent[-8:]

    def filter(self, raw, actions):
        game = raw['game_state']
        if game.get('screen_type') != 'COMBAT_REWARD' or self.location(game) not in self.declined:
            return actions
        rewards = game.get('screen_state', {}).get('rewards', [])
        if sum(r.get('reward_type') == 'CARD' for r in rewards) != 1:
            return actions
        return [a for a in actions if not (a.get('kind') == 'reward' and a.get('reward', {}).get('reward_type') == 'CARD')]

    def visit(self, summary, actions):
        visible = {k: v for k, v in summary.items() if k not in {'decision_context', 'experience_context'}}
        key = json.dumps(gameplay_state([visible, actions]), sort_keys=True, ensure_ascii=False)
        self.visits[key] += 1
        if self.visits[key] > 1:
            self.repeated_requests += 1
        return self.visits[key] <= 2

    def context(self, summary, actions):
        return {'recent_actions': deepcopy(self.recent),
                'objective': 'Win the entire encounter while conserving health and consumables for the run. Compare offense, defense and setup over future turns, not only the next immediate hit.',
                'future_draw_order': 'unknown; draw-pile contents are available, but do not assume a favorable order',
                'declined_card_rewards': [list(x) for x in sorted(self.declined, key=str)],
                'remaining_energy': summary.get('player', {}).get('energy'),
                'playable_card_count': len({a.get('card_uuid') for a in actions if a.get('kind') == 'play'}),
                'enemy_intents': [{k: e.get(k) for k in ('name', 'intent', 'move_adjusted_damage', 'move_hits')}
                                  for e in summary.get('enemies', [])]}


def describe_candidates(summary, actions):
    """Expose available descriptions without resolving unknown dynamic templates."""
    actions = deepcopy(actions)
    cards = {c.get('card_uuid', c.get('uuid')): c for c in summary.get('hand', [])}
    for action in actions:
        card = cards.get(action.get('card_uuid')) if action.get('kind') == 'play' else action.get('card')
        if action.get('kind') == 'card':
            card = next((c for c in summary.get('screen_state', {}).get('cards', [])
                         if c.get('uuid', c.get('id')) == action['card'].get('uuid', action['card'].get('id'))), card)
        if card and card.get('description') and card['description'] != 'unknown':
            action['description'] += ' | Effect: ' + card['description']
            if card.get('dynamic_values_unknown'):
                action['description'] += ' (template values unknown; do not infer current numbers)'
        if card:
            preview = next((p for p in card.get('target_damage_previews', [])
                            if p.get('target_index') == action.get('target_index')
                            and p.get('source') == 'game_calculateCardDamage'
                            and type(p.get('damage_before_block')) is int and p['damage_before_block'] >= 0), None)
            if preview:
                action['damage_preview'] = deepcopy(preview)
                action['description'] += f" | Game target damage calculation before block: {preview['damage_before_block']}; not final HP loss or a full multi-hit simulation."
        if action['command'] == 'END':
            energy = summary.get('player', {}).get('energy')
            playable = len({a.get('card_uuid') for a in actions if a.get('kind') == 'play'})
            action['description'] += f'; remaining energy={energy}, playable cards={playable}. Consider unused attacks, setup and incoming damage; waiting may be appropriate for sleeping enemies.'
    return actions




def confirmation(before: dict, after: dict, action: dict) -> str | None:
    """Return evidence only for the selected action's expected effect."""
    if action.get('kind') == 'start':
        game = after.get('game_state', {})
        if after.get('in_game') is True and game.get('class') == 'IRONCLAD' and game.get('ascension_level') == 0:
            return 'requested_run_entered'
        return None
    old = before['game_state']
    new = after.get('game_state', {})
    screen = new.get('screen_type')
    kind = action.get('kind')
    old_screen = old.get('screen_type')
    if kind and kind.startswith('screen_'):
        return confirm_screen(before, after, action)
    if kind == 'potion':
        index = action['potion_index']
        previous = old.get('potions', [])
        current = new.get('potions', [])
        if index < len(previous) and index < len(current) and previous[index].get('id') == action['potion_id']:
            if current[index].get('id') == 'Potion Slot':
                return 'potion_slot_consumed'
            # Entropic Brew等会把刚清空的槽位补上；需要明确的替换证据。
            if action.get('subaction') == 'use' and current[index].get('id') != action['potion_id']:
                return 'potion_slot_replaced'
    if action['command'].startswith('PLAY'):
        if old.get('room_phase') == 'COMBAT' and screen in {'COMBAT_REWARD', 'GAME_OVER', 'COMPLETE'}:
            return 'combat_ended'
        if old_screen == 'NONE' and screen in {'HAND_SELECT', 'GRID', 'CARD_REWARD'}:
            return 'play_opened_selection'
        hand = new.get('combat_state', {}).get('hand')
        if after.get('ready_for_command') is True and isinstance(hand, list) and all((isinstance(c, dict) and ('uuid' in c or 'card_uuid' in c) for c in hand)) and (new.get('room_phase') == 'COMBAT') and (action['card_uuid'] not in {c.get('uuid', c.get('card_uuid')) for c in hand}):
            return 'played_card_left_hand'
    if action['command'] == 'END':
        if screen in {'COMBAT_REWARD', 'GAME_OVER', 'COMPLETE'}:
            return 'combat_ended'
        if old_screen == 'NONE' and screen in {'HAND_SELECT', 'GRID'}:
            return 'turn_end_opened_selection'
        if new.get('combat_state', {}).get('turn', 0) > old['combat_state']['turn']:
            return 'turn_advanced'
    if kind == 'reward':
        reward = action['reward']
        reward_type = reward['reward_type']
        if reward_type in {'SAPPHIRE_KEY', 'EMERALD_KEY'}:
            key = 'sapphire' if reward_type == 'SAPPHIRE_KEY' else 'emerald'
            if old.get('keys', {}).get(key) is False and new.get('keys', {}).get(key) is True:
                return 'key_collected'
        if reward_type == 'CARD' and screen == 'CARD_REWARD':
            return 'card_reward_opened'
        if reward_type == 'RELIC':
            relic_id = reward['relic']['id']
            if sum(r.get('id') == relic_id for r in new.get('relics', [])) > sum(r.get('id') == relic_id for r in old.get('relics', [])):
                return 'relic_reward_collected'
        remaining = new.get('screen_state', {}).get('rewards', [])
        expected = deepcopy(old['screen_state']['rewards'])
        expected.pop(action['choice_index'])
        if screen == old_screen and remaining == expected:
            if reward_type in {'GOLD', 'STOLEN_GOLD'} and new.get('gold', 0) >= old.get('gold', 0) + reward.get('gold', 0):
                return 'gold_reward_collected'
            if reward_type == 'POTION' and new.get('potions') != old.get('potions') and any((p.get('id') == reward['potion'].get('id') for p in new.get('potions', []))):
                return 'potion_reward_collected'
            if reward_type == 'RELIC' and new.get('relics') != old.get('relics') and any((r.get('id') == reward['relic'].get('id') for r in new.get('relics', []))):
                return 'relic_reward_collected'
    if kind == 'card' and old.get('room_phase') == 'COMBAT' and new.get('room_phase') == 'COMBAT':
        old_combat, new_combat = old.get('combat_state',{}), new.get('combat_state',{})
        old_ids = {c.get('uuid') for group in ('hand','draw_pile','discard_pile','exhaust_pile','limbo') for c in old_combat.get(group,[])}
        if any(c.get('id') == action['card']['id'] and c.get('uuid') and c['uuid'] not in old_ids
               for group in ('hand','discard_pile') for c in new_combat.get(group,[])):
            return 'temporary_card_added'
    if kind in {'card', 'bowl', 'skip'} and screen in {'COMBAT_REWARD', 'COMPLETE', 'EVENT'}:
        if kind == 'skip' and new.get('deck') == old.get('deck'):
            return 'card_reward_skipped'
        if kind == 'bowl' and new.get('max_hp', 0) == old.get('max_hp', 0) + 2:
            return 'bowl_hp_increased'
        if kind == 'card':
            card_id = action['card']['id']
            count = lambda g: sum((c.get('id') == card_id for c in g.get('deck', [])))
            if count(new) == count(old) + 1:
                return 'card_added_to_deck'
    if kind == 'proceed' and screen == 'MAP':
        return 'map_opened'
    if (kind == 'proceed' and old_screen == 'COMBAT_REWARD' and screen == 'EVENT'
            and old.get('room_phase') == 'COMPLETE' and new.get('room_phase') in {'EVENT','COMPLETE'}
            and all(old.get(k) == new.get(k) for k in ('act','floor'))
            and new.get('screen_state',{}).get('event_id')):
        return 'reward_overlay_closed_to_event'
    if kind in {'map', 'boss'} and new.get('floor', 0) == old.get('floor', 0) + 1 and (screen != 'MAP'):
        return 'floor_advanced_destination_not_directly_reported'
    return None

class RunSession(SessionRuntime):
    """Reuse only common pause/timeout handling from the combat session."""

    def __init__(self, output_dir, mode='jev', max_decisions=500, selector=None, *, run_id=None, catalog=None, start_new=False, max_actions=2000, max_seconds=5400, search_config=None, stop_after_combat=False, seed=None):
        self.memory = DecisionMemory()
        self.turn_queue = []
        self.plan_metadata = {}
        self.search_config = search_config or SearchConfig()
        self.stop_after_combat = stop_after_combat
        self.battle_identity = None
        self.battle_start_hp = None
        self.planned_selection = None
        self.checkpoint_pending = None
        self.decision_id = None
        self.seed = seed
        self._memory_restored = False
        self.max_actions, self.max_seconds = max_actions, max_seconds
        self.started_at = time.monotonic()
        self.run_id = run_id
        self.start_new = start_new
        self.started_new_game = bool(start_new)
        game_dir = Path(os.environ.get('STS_GAME_DIRECTORY', r'C:\Program Files (x86)\Steam\steamapps\common\SlayTheSpire'))
        self.catalog = catalog if catalog is not None else load_catalog(game_dir / 'desktop-1.0.jar')
        self.step_id = 0
        self.run_identity = None
        self.last_raw = None
        self.result = None
        self.sent_ack = False
        super().__init__(output_dir, mode, max_decisions, selector)
        self.run_id = self.run_id or self.id
        self.phase = 'ready'

    def _record(self, status, **fields):
        if status == 'action_confirmed':
            self.memory.observe(fields['before'], fields['after'], fields['decision'])
        if status == 'created': fields['components'] = LOADED_COMPONENTS['components']
        append_record(self.output_dir / 'runs.jsonl', {'schema_version': 2, 'policy_version': 'generate-rank-1', 'code_version': LOADED_COMPONENTS['code_version'], 'timestamp': datetime.now(timezone.utc).isoformat(), 'session_id': self.id, 'run_id': self.run_id or self.id, 'battle_id': self.battle_identity, 'decision_id': self.decision_id, 'step_id': self.step_id, 'mode': self.mode, 'status': status, 'calls': self.calls, 'actions': self.actions, **fields})

    def _export_report(self):
        """结束或中断时输出可读时间线；导出失败不改变已记录的执行结果。"""
        from .records import render_run_report
        identifier = self.run_id or self.id
        try:
            rows = []
            with (self.output_dir / 'runs.jsonl').open(encoding='utf-8') as stream:
                for line in stream:
                    row = json.loads(line)
                    if row.get('run_id') == identifier:
                        rows.append(row)
            report = render_run_report(rows, identifier)
            for name in (f'run-{identifier}.md', 'run-report.md'):
                path = self.output_dir / name
                temporary = path.with_suffix('.md.tmp')
                temporary.write_text(report, encoding='utf-8')
                temporary.replace(path)
        except (OSError, ValueError):
            append_record(self.output_dir / 'runs.jsonl', {
                'run_id': identifier, 'session_id': self.id,
                'status': 'report_export_failed', 'step_id': self.step_id})

    def _restore_memory(self):
        if self._memory_restored:
            return
        self._memory_restored = True
        if self.started_new_game:
            return
        path = self.output_dir / 'runs.jsonl'
        try:
            with path.open(encoding='utf-8') as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                        game = (row.get('before') or {}).get('game_state', {})
                        identity = (game.get('seed'), game.get('class'), game.get('ascension_level'))
                        if identity == self.run_identity and row.get('mode') == self.mode:
                            if row.get('status') == 'action_confirmed':
                                self.memory.observe(row['before'], row['after'], row['decision'])
                            elif row.get('status') == 'request_started':
                                self.memory.visit(row['summary'], row.get('loop_candidates', row['candidates']))
                    except (ValueError, KeyError, TypeError, AttributeError):
                        continue
        except OSError:
            pass

    def tick(self):
        super().tick()
        if not self.stopped and self.run_identity is not None and time.monotonic() - self.started_at >= self.max_seconds:
            return self._stop('time_limit')
        return []

    def _select_choice(self, raw, summary, candidates):
        if self.mode == 'jev':
            load_jev_key()
        self.calls += 1
        self.decision_id = f'{self.run_id}:{self.calls}'
        self._record('request_started', before=raw, summary=summary, candidates=candidates,
                     loop_candidates=self._loop_candidates, instructions=instructions_for(summary))
        decision = self.selector(summary, candidates)
        action = validate_choice(decision['action']['id'], candidates)
        if decision['action'] != action:
            raise SelectionError('Selector changed native action.')
        return decision

    def _stop(self, reason, **fields):
        if self.pending:
            fields.setdefault('before', self.pending[0])
            fields.setdefault('decision', self.pending[1])
        fields.setdefault('after', self.last_raw)
        return super()._stop(reason, **fields)

    def command_sent(self, command: str) -> None:
        """Record transport acknowledgement separately from observed execution."""
        if self.phase != 'confirming' or command != self.sent[1]['action']['command']:
            self._stop('unexpected_command')
            return
        self.sent_ack = True
        self._record('command_sent', command=command, before=self.sent[0], decision=self.sent[1])

    def _receive_menu(self, raw):
        if self.phase == 'confirming' or raw.get('ready_for_command') is not True:
            return []
        if self.phase == 'checking_start':
            if raw != self.pending[0]:
                return self._stop('state_changed')
            self.sent = self.pending
            self.sent_ack = False
            self.phase = 'confirming'
            self.deadline = time.monotonic() + 30
            self.start_new = False
            self.actions += 1
            command = self.sent[1]['action']['command']
            self._record('command_prepared', before=raw, decision=self.sent[1], command=command)
            return [command]
        if self.start_new and 'start' in raw.get('available_commands', []):
            action = {'id': 'start_ironclad', 'command': 'START IRONCLAD 0' + (f' {self.seed}' if self.seed else ''),
                      'description': '按启动选项开始铁甲战士 A0 新局', 'kind': 'start',
                      'hand_index': None, 'card_uuid': None, 'target_index': None}
            decision = {'action': action, 'requested_model': None,
                        'returned_model': None, 'confidence': None}
            self.step_id += 1
            self.pending = (deepcopy(raw), decision)
            self.phase = 'checking_start'
            self.deadline = time.monotonic() + 15
            self._record('decision', before=raw, summary={'screen_type': 'MAIN_MENU'},
                         candidates=[action], decision=decision, source='explicit_launch_option')
            return ['STATE']
        if self.phase != 'waiting_run':
            self._record('waiting_for_run')
            self.phase = 'waiting_run'
        return []

    def receive(self, raw: dict) -> list[str]:
        """Refresh before sending and await action-specific authoritative evidence."""
        self.last_raw = deepcopy(raw)
        # 主菜单等待用户进入对局；这个等待不占局内过渡超时或请求预算。
        if self.run_identity is None and raw.get('in_game') is False and self.phase not in {'checking_start', 'confirming'}:
            self.deadline = None
        self.tick()
        if self.stopped:
            return []
        if raw.get('error'):
            return self._stop('game_error')
        if self.run_identity is None and raw.get('in_game') is False:
            return self._receive_menu(raw)
        if raw.get('ready_for_command') is not True:
            # 章节切换时原生地牢/角色字段可暂时缺失，稳定以后再核对身份。
            if self.deadline is None:
                self.deadline = time.monotonic() + 15
            return []
        game = raw.get('game_state', {})
        if self.battle_identity is None and game.get('room_phase') == 'COMBAT':
            self.battle_identity = (game.get('seed'), game.get('act'), game.get('floor'))
            self.battle_start_hp = game.get('current_hp')
            self._record('battle_started', before=raw, start_hp=self.battle_start_hp)
        if self.run_identity is not None:
            if raw.get('in_game') is not True:
                return self._stop('left_game')
            if (game.get('seed'), game.get('class'), game.get('ascension_level')) != self.run_identity:
                return self._stop('run_changed')
        elif raw.get('in_game') is True:
            self.run_identity = (game.get('seed'), game.get('class'), game.get('ascension_level'))
            if game.get('floor') == 0:
                self.started_new_game = True
            self.started_at = time.monotonic()
        self._restore_memory()
        if self.phase == 'confirming':
            if not self.sent_ack:
                return self._stop('send_not_acknowledged')
            evidence = confirmation(self.sent[0], raw, self.sent[1]['action'])
            if evidence:
                self._record('action_confirmed', before=self.sent[0], after=raw, decision=self.sent[1], command=self.sent[1]['action']['command'], evidence=evidence)
                self.phase = 'ready'
                self.deadline = None
                self.pending = None
                self.sent = None
                if self.checkpoint_pending:
                    self._record('checkpoint_reached', after=raw, reason=self.checkpoint_pending)
                    self.checkpoint_pending = None
            elif game.get('screen_type') == 'GAME_OVER':
                self._record('action_unconfirmed', before=self.sent[0], after=raw, decision=self.sent[1], reason='game_over_before_action_confirmation')
                self.pending = None
                self.sent = None
                self.phase = 'ready'
            elif raw.get('ready_for_command') is True:
                time.sleep(0.2)
                return ['STATE']
            else:
                return []
        if self.battle_identity and game.get('screen_type') in {'COMBAT_REWARD', 'GAME_OVER'}:
            won = game.get('screen_type') == 'COMBAT_REWARD'
            self._record('battle_complete', after=raw, result={'victory': won, 'start_hp': self.battle_start_hp, 'end_hp': game.get('current_hp', 0) if won else 0})
            self.battle_identity = None
            self.turn_queue = []
            if self.stop_after_combat:
                return self._stop('battle_finished')
        if game.get('screen_type') == 'GAME_OVER':
            state = game.get('screen_state', {})
            if type(state.get('victory')) is not bool or type(state.get('score')) is not int:
                return self._stop('unsupported_state')
            self.result = {k: state[k] for k in ('victory', 'score')}
            self.stopped = True
            self.reason = 'game_over'
            self._record('complete', after=raw, result=self.result)
            return []
        if game.get('screen_type') == 'NONE' and game.get('room_phase') == 'COMPLETE':
            # CommunicationMod can be ready for generic key/potion commands
            # while a reward overlay is closing; its next native choice screen
            # (CHEST/COMPLETE/MAP) has not settled yet.
            if self.deadline is None:
                self.deadline = time.monotonic() + 15
                self._record('awaiting_transition', before=raw, reason='completed_room_screen_closing')
            time.sleep(0.1)
            return ['STATE']
        if raw.get('ready_for_command') is not True or (game.get('room_phase') == 'COMBAT' and game.get('screen_type') == 'NONE' and game.get('action_phase') != 'WAITING_ON_USER') or (not [c for c in raw.get('available_commands', []) if c not in {'state', 'wait'}]):
            if self.deadline is None:
                self.deadline = time.monotonic() + 15
            return []
        try:
            summary, candidates = prepare_journey(raw)
            summary = enrich_summary(summary, self.catalog)
            candidates = describe_candidates(summary, self.memory.filter(raw, candidates))
            summary['decision_context'] = self.memory.context(summary, candidates)
        except UnsupportedState as error:
            return self._stop('unsupported_state', message=str(error))
        if self.phase == 'checking':
            if gameplay_state(raw) != gameplay_state(self.pending[0]):
                return self._stop('state_changed')
            self.tick()
            if self.stopped:
                return []
            self.sent = self.pending
            self.sent_ack = False
            self.phase = 'confirming'
            self.deadline = time.monotonic() + 30
            self.actions += 1
            command = self.sent[1]['action']['command']
            self._record('command_prepared', before=raw, decision=self.sent[1], command=command)
            return [command]
        if any((e['intent'] == 'DEBUG' and e['current_hp'] > 0 for e in summary.get('enemies', []))):
            if self.deadline is None:
                self.deadline = time.monotonic() + 15
            time.sleep(0.2)
            return ['STATE']
        self.deadline = None
        if self.actions >= self.max_actions:
            return self._stop('action_limit')
        if self.calls >= self.max_decisions and not self.turn_queue and not self.planned_selection:
            return self._stop('decision_limit')
        self.tick()
        if self.stopped:
            return []
        if not candidates:
            return self._stop('no_unvisited_actions')
        if not self.memory.visit(summary, candidates):
            return self._stop('decision_loop', repeated_requests=self.memory.repeated_requests)
        self.step_id += 1
        self._loop_candidates = candidates
        try:
            selection_action = None
            if self.planned_selection and game.get('screen_type') in {'HAND_SELECT', 'GRID'}:
                selection_action = next((a for a in candidates if a.get('card_uuid') == self.planned_selection), None)
                if selection_action is None:
                    selection_action = next((a for a in candidates if a['command'] == 'CONFIRM'), None)
                if selection_action is None:
                    return self._stop('planned_selection_unavailable')
            elif self.planned_selection and game.get('screen_type') == 'NONE':
                self.planned_selection = None
            free_reward = next((a for a in candidates if a.get('kind') == 'reward'
                                and (a['reward']['reward_type'] in {'GOLD', 'STOLEN_GOLD', 'RELIC'}
                                     or (a['reward']['reward_type'] == 'CARD'
                                         and sum(x.get('kind') == 'reward' and x.get('reward',{}).get('reward_type') == 'CARD' for x in candidates) == 1)
                                     or (a['reward']['reward_type'] == 'POTION'
                                         and not any(r.get('id') == 'Sozu' for r in summary.get('relics', []))))), None)
            action = bind_plan_step(self.turn_queue[0], summary, candidates) if self.turn_queue and 'player' in summary else None
            inspect_shop = next((a for a in candidates if a.get('kind') == 'screen_shop_room'
                                 and self.memory.location(game) not in self.memory.inspected_shops), None)
            source = 'reused_turn_plan'
            if self.turn_queue and not action and not selection_action:
                self._record('plan_invalidated', before=raw, reason='observed_state_differs_from_turn_forecast', expected=self.turn_queue[0]['expected_before'], observed=battle_projection(summary) if 'player' in summary else summary)
                self.turn_queue = []
            if selection_action:
                decision = {'action': selection_action, **self.plan_metadata}
                source = 'planned_card_selection'
                action = None
                if selection_action['command'] == 'CONFIRM': self.planned_selection = None
            elif inspect_shop:
                decision = {'action': inspect_shop, 'requested_model': None, 'returned_model': None, 'confidence': None}
                self.turn_queue = []
                action = None
                source = 'local_inspect_shop'
            elif free_reward:
                decision = {'action': free_reward, 'requested_model': None, 'returned_model': None, 'confidence': None}
                self.turn_queue = []
                action = None
                source = 'local_free_reward'
                if free_reward['reward']['reward_type'] == 'CARD':
                    source = 'local_inspect_card_reward'
            elif len(candidates) == 1 and candidates[0].get('kind') == 'end':
                decision = {'action': candidates[0], 'requested_model': None, 'returned_model': None, 'confidence': None}
                action = None
                self.turn_queue = []
                source = 'local_only_end'
            elif not action:
                plans, search = generate_plans(summary, candidates, self.search_config)
                if 'player' in summary:
                    self._record('search_completed', decision_id=f'{self.run_id}:{self.calls + 1}', state_hash=fingerprint(summary), search=search, candidates=plans)
                if plans:
                    if self.calls >= self.max_decisions:
                        return self._stop('decision_limit')
                    planned_potions = set(search.get('planned_potion_uses', []))
                    standalone_potions = [a for a in candidates if a.get('kind') == 'potion'
                                          and a['id'] not in planned_potions]
                    selection = self._select_choice(raw, summary, plans + standalone_potions)
                    source = 'selected_turn_plan'
                    if selection['action']['kind'] == 'turn_plan':
                        self.turn_queue = deepcopy(selection['action']['steps'])
                        self.plan_metadata = {k: deepcopy(v) for k, v in selection.items() if k != 'action'}
                        self.plan_metadata['plan_id'] = selection['action']['id']
                        self._record('plan_selected', before=raw, decision=selection, source=source)
                        action = bind_plan_step(self.turn_queue[0], summary, candidates)
                        if not action:
                            return self._stop('invalid_turn_plan')
                    else:
                        decision = selection
                        source = 'selected_action'
                else:
                    if 'player' in summary:
                        return self._stop('no_turn_plans', search=search)
                    if self.calls >= self.max_decisions:
                        return self._stop('decision_limit')
                    decision = self._select_choice(raw, summary, candidates)
                    source = 'selected_action'
            if action:
                step = self.turn_queue.pop(0)
                self.planned_selection = action.get('planned_selection_uuid', step.get('selection_uuid'))
                self.checkpoint_pending = step.get('checkpoint')
                decision = {'action': action, **self.plan_metadata}
            self._record('decision', before=raw, summary=summary, candidates=candidates,
                         decision=decision, instructions=instructions_for(summary), source=source)
        except (SelectionError, KeyError, TypeError) as error:
            return self._stop('selection_error', message=str(error) if isinstance(error, SelectionError) else 'Invalid selector response.')
        self.pending = (deepcopy(raw), deepcopy(decision))
        self.tick()
        if self.stopped:
            return []
        self.phase = 'checking'
        self.deadline = time.monotonic() + 15
        return ['STATE']




def resume_session(old, budget: int, *, session_factory=None):
    if not old.stopped or old.reason in {'game_over', 'left_game', 'run_changed'}:
        raise ValueError('此运行不能恢复。')
    if type(budget) is not int or not 1 <= budget <= 2000:
        raise ValueError('恢复预算必须为 1–2000。')
    if session_factory is None:
        # Resume reuses this controller with a fresh state.
        session_factory = RunSession
    new = session_factory(old.output_dir, mode=old.mode,
                          max_decisions=old.calls + budget, run_id=old.run_id)
    new.calls, new.actions, new.step_id = old.calls, old.actions, old.step_id
    new.run_identity = old.run_identity
    if hasattr(old, 'memory'):
        new.memory = deepcopy(old.memory)
        new._memory_restored = True
    for name in ('started_at', 'max_actions', 'max_seconds', 'search_config', 'stop_after_combat', 'battle_identity', 'battle_start_hp', 'seed'):
        if hasattr(old, name):
            setattr(new, name, getattr(old, name))
    new.planned_selection = old.planned_selection
    new.plan_metadata = deepcopy(old.plan_metadata)
    new.decision_id = old.decision_id
    new.checkpoint_pending = old.checkpoint_pending
    new._record('resumed', previous_session_id=old.id, additional_budget=budget,
                prior_stop_reason=old.reason)
    return new


def handle_resume_request(old, budget: int, *, session_factory=None):
    """只响应显式标志；暂停完成之后才创建新控制器。"""
    flag = old.output_dir / 'resume.flag'
    if not flag.exists():
        return old, False
    old.tick()
    if not old.stopped:
        return old, False
    requested = flag.read_text(encoding='utf-8').strip()
    if requested.isdecimal():
        budget = int(requested)
    if type(budget) is not int or not 1 <= budget <= 2000:
        flag.unlink()
        old._record('resume_failed', reason='invalid_request_budget')
        return old, False
    if old.sent is not None and old.sent_ack:
        from .session import confirmation
        raw = old.last_raw
        evidence = None
        if raw and raw.get('ready_for_command') is True and raw.get('in_game') is True:
            game = raw.get('game_state', {})
            identity = (game.get('seed'), game.get('class'), game.get('ascension_level'))
            if old.run_identity is None and old.sent[1]['action'].get('kind') == 'start':
                evidence = confirmation(old.sent[0], raw, old.sent[1]['action'])
                if evidence:
                    old.run_identity = identity
            elif identity == old.run_identity:
                evidence = confirmation(old.sent[0], raw, old.sent[1]['action'])
        if not evidence:
            if not getattr(old, 'resume_waiting', False):
                old._record('resume_waiting_confirmation', reason='outstanding_action_unconfirmed')
                old.resume_waiting = True
                old.resume_query_pending = True
            return old, False
        old._record('action_confirmed', before=old.sent[0], after=raw,
                    decision=old.sent[1], command=old.sent[1]['action']['command'], evidence=evidence)
        old.sent = old.pending = None
    flag.unlink()
    pause = old.output_dir / 'pause.flag'
    if pause.exists():
        pause.unlink()
    try:
        new = resume_session(old, budget, session_factory=session_factory)
    except Exception:
        # 重载失败时保持暂停，不进入自动请求或重发循环。
        pause.write_text('resume failed', encoding='utf-8')
        old._record('resume_failed')
        raise
    return new, True


CombatSession = RunSession
