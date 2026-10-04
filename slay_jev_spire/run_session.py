"""Bounded run controller with action-specific observed outcomes."""
from copy import deepcopy
from datetime import datetime, timezone
import os
import json
from pathlib import Path
import time
from .session import CombatSession
from .journey import prepare_journey
from .records import append_record
from .selectors import INSTRUCTIONS, SelectionError, validate_choice
from .config import load_jev_key
from .state import UnsupportedState
from .catalog import load_catalog, enrich_summary
from .screens import confirm_screen
from .decision_memory import DecisionMemory, describe_candidates, gameplay_state
from .turn_planner import proven_lethal_plan, turn_plans, bind_plan_step
from .experience import applicable_experiences, review_and_store

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
        if old_screen == 'NONE' and screen in {'HAND_SELECT', 'GRID'}:
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
    if kind in {'card', 'bowl', 'skip'} and screen in {'COMBAT_REWARD', 'COMPLETE'}:
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
    if kind in {'map', 'boss'} and new.get('floor', 0) == old.get('floor', 0) + 1 and (screen != 'MAP'):
        return 'floor_advanced_destination_not_directly_reported'
    return None

class RunSession(CombatSession):
    """Reuse only common pause/timeout handling from the combat session."""

    def __init__(self, output_dir, mode='jev', max_decisions=500, selector=None, *, run_id=None, catalog=None, start_new=False, max_actions=2000, max_seconds=5400):
        self.memory = DecisionMemory()
        self.turn_queue = []
        self.plan_metadata = {}
        self._memory_restored = False
        self.max_actions, self.max_seconds = max_actions, max_seconds
        self.started_at = time.monotonic()
        self.run_id = run_id
        self.start_new = start_new
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
        append_record(self.output_dir / 'runs.jsonl', {'timestamp': datetime.now(timezone.utc).isoformat(), 'session_id': self.id, 'run_id': self.run_id or self.id, 'step_id': self.step_id, 'mode': self.mode, 'status': status, 'calls': self.calls, 'actions': self.actions, **fields})
        if status in {'stopped', 'complete', 'resumed'}:
            self._export_report()

    def _export_report(self):
        """结束或中断时输出可读时间线；导出失败不改变已记录的执行结果。"""
        from .run_report import render_run_report
        identifier = self.run_id or self.id
        try:
            rows = []
            with (self.output_dir / 'runs.jsonl').open(encoding='utf-8') as stream:
                for line in stream:
                    row = json.loads(line)
                    if row.get('run_id') == identifier:
                        rows.append(row)
            report = render_run_report(rows, identifier)
            try:
                findings = review_and_store(rows, self.output_dir / 'experience.json')
                review = {'run_id': identifier, 'source': 'verified_local_review',
                          'scope': 'final' if self.reason == 'game_over' else 'checkpoint', 'findings': findings}
                (self.output_dir / f'review-{identifier}.json').write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding='utf-8')
            except (OSError, ValueError, TypeError):
                append_record(self.output_dir / 'runs.jsonl', {'run_id': identifier, 'session_id': self.id,
                              'status': 'review_failed', 'step_id': self.step_id})
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
        self._record('request_started', before=raw, summary=summary, candidates=candidates,
                     loop_candidates=self._loop_candidates, instructions=INSTRUCTIONS)
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
            action = {'id': 'start_ironclad', 'command': 'START IRONCLAD 0',
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
        if self.run_identity is not None:
            if raw.get('in_game') is not True:
                return self._stop('left_game')
            if (game.get('seed'), game.get('class'), game.get('ascension_level')) != self.run_identity:
                return self._stop('run_changed')
        elif raw.get('in_game') is True:
            self.run_identity = (game.get('seed'), game.get('class'), game.get('ascension_level'))
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
        if game.get('screen_type') == 'GAME_OVER':
            state = game.get('screen_state', {})
            if type(state.get('victory')) is not bool or type(state.get('score')) is not int:
                return self._stop('unsupported_state')
            self.result = {k: state[k] for k in ('victory', 'score')}
            self.stopped = True
            self.reason = 'game_over'
            self._record('complete', after=raw, result=self.result)
            return []
        if raw.get('ready_for_command') is not True or (game.get('room_phase') == 'COMBAT' and game.get('screen_type') == 'NONE' and game.get('action_phase') != 'WAITING_ON_USER') or (not [c for c in raw.get('available_commands', []) if c not in {'state', 'wait'}]):
            if self.deadline is None:
                self.deadline = time.monotonic() + 15
            return []
        try:
            summary, candidates = prepare_journey(raw)
            summary = enrich_summary(summary, self.catalog)
            candidates = describe_candidates(summary, self.memory.filter(raw, candidates))
            summary['decision_context'] = self.memory.context(summary, candidates)
            summary['experience_context'] = applicable_experiences(summary, self.output_dir / 'experience.json')
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
        if self.calls >= self.max_decisions and not self.turn_queue:
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
            free_reward = next((a for a in candidates if a.get('kind') == 'reward'
                                and (a['reward']['reward_type'] in {'GOLD', 'STOLEN_GOLD'}
                                     or (a['reward']['reward_type'] == 'POTION'
                                         and not any(r.get('id') == 'Sozu' for r in summary.get('relics', []))))), None)
            action = bind_plan_step(self.turn_queue[0], summary, candidates) if self.turn_queue else None
            source = 'reused_turn_plan'
            if self.turn_queue and not action:
                self._record('plan_invalidated', before=raw, reason='observed_state_differs_from_turn_forecast')
                self.turn_queue = []
            if free_reward:
                decision = {'action': free_reward, 'requested_model': None, 'returned_model': None, 'confidence': None}
                self.turn_queue = []
                action = None
                source = 'local_free_reward'
            elif len(candidates) == 1 and candidates[0].get('kind') == 'end':
                decision = {'action': candidates[0], 'requested_model': None, 'returned_model': None, 'confidence': None}
                action = None
                self.turn_queue = []
                source = 'local_only_end'
            elif not action:
                plans = turn_plans(summary, candidates)
                if plans:
                    lethal = next((p for p in plans if p['outcome']['combat_won']), None)
                    if lethal:
                        selection = {'action': lethal, 'requested_model': None, 'returned_model': None, 'confidence': None}
                        source = 'local_verified_turn_plan'
                    else:
                        if self.calls >= self.max_decisions:
                            return self._stop('decision_limit')
                        selection = self._select_choice(raw, summary, plans + [a for a in candidates if a.get('kind') == 'potion'])
                        source = 'selected_turn_plan'
                    if selection['action']['kind'] == 'turn_plan':
                        self.turn_queue = deepcopy(selection['action']['steps'])
                        self.plan_metadata = {k: selection.get(k) for k in ('requested_model', 'returned_model', 'confidence')}
                        self._record('plan_selected', before=raw, decision=selection, source=source)
                        action = bind_plan_step(self.turn_queue[0], summary, candidates)
                        if not action:
                            return self._stop('invalid_turn_plan')
                    else:
                        decision = selection
                        source = 'selected_action'
                else:
                    plan = proven_lethal_plan(summary, candidates)
                    if plan:
                        decision = {'action': plan[0], 'requested_model': None, 'returned_model': None, 'confidence': None}
                        source = 'local_verified_lethal'
                    else:
                        if self.calls >= self.max_decisions:
                            return self._stop('decision_limit')
                        decision = self._select_choice(raw, summary, candidates)
                        source = 'selected_action'
            if action:
                self.turn_queue.pop(0)
                decision = {'action': action, **self.plan_metadata}
            self._record('decision', before=raw, summary=summary, candidates=candidates,
                         decision=decision, instructions=INSTRUCTIONS, source=source)
        except (SelectionError, KeyError, TypeError) as error:
            return self._stop('selection_error', message=str(error) if isinstance(error, SelectionError) else 'Invalid selector response.')
        self.pending = (deepcopy(raw), deepcopy(decision))
        self.tick()
        if self.stopped:
            return []
        self.phase = 'checking'
        self.deadline = time.monotonic() + 15
        return ['STATE']
