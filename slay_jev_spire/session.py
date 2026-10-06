"""一场战斗的有界决策循环；传输层只负责传递命令和游戏状态。"""

from datetime import datetime, timezone
from pathlib import Path
import time
from uuid import uuid4
from .config import load_jev_key
from .records import append_record, build_record, source_manifest
from .selectors import SelectionError, choose_jev, choose_mock, validate_choice, instructions_for
from .state import UnsupportedState, prepare_state
from collections import Counter
from copy import deepcopy
import json
import os
from .screens import prepare_journey
from .state import load_catalog, enrich_summary
from .effects import effect_evidence
from .planning_config import SearchConfig
from .shopping import generate_shop_plans,bind_shop_queue,identity as shop_identity
from .transactions import PendingAction,ProtocolError,protocol
from .identity import GameIdentity, reward_key, recovery_path
from .jev_provider import capture_http
from .selection_intent import SelectionIntent
from .navigation_intent import NavigationIntent
from .native_catalog import NativeCatalogStore
from .event_observation import augment_event
import importlib

LOADED_COMPONENTS = source_manifest()


def experimental_planner():
    # The production native path must not import the handwritten rule engine.
    from . import turn_planner
    return turn_planner




class SessionRuntime:
    """刷新、选择、校验、发送、确认循环；停止后持续仅采集。"""

    def __init__(self, output_dir: Path, mode: str = 'jev', max_decisions: int = 20, selector=None):
        self.output_dir = output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        self.mode = mode
        if selector is None and mode=='external':
            from .external_decision import ExternalSelector
            selector=ExternalSelector(output_dir)
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
        result = {k: gameplay_state(v) for k, v in value.items() if k!='jev_protocol'}
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
        self.selection_origin = None

    @staticmethod
    def location(game):
        identity = GameIdentity.from_game(game)
        return ((identity.run_id, identity.room_id) if identity and identity.room_id
                else (game.get('act'), game.get('floor')))

    def observe(self, before, after, decision):
        action = decision['action']
        game = before.get('game_state', {})
        for observed in (game, after.get('game_state', {})):
            if observed.get('screen_type') == 'SHOP_SCREEN':
                self.inspected_shops.add(self.location(observed))
        kind = action.get('kind')
        if kind == 'reward' and action.get('reward', {}).get('reward_type') == 'CARD':
            self.opened_reward = reward_key(game, action['reward'].get('reward_source_id'))
        if kind in {'skip', 'card', 'bowl'}:
            source = reward_key(game, game.get('screen_state', {}).get('reward_source_id'))
            if kind == 'skip' and source and self.opened_reward == source:
                self.declined.add(source)
            self.opened_reward = None
        played = next((c for c in game.get('combat_state',{}).get('hand',[]) if c.get('uuid') == action.get('card_uuid')), {})
        next_game=after.get('game_state',{})
        selection_open=(next_game.get('room_phase')=='COMBAT'
                        and next_game.get('screen_type') not in {None,'NONE'})
        if not selection_open:
            self.selection_origin=None
        elif game.get('screen_type')=='NONE':
            # Preserve observed source data before a consumed potion disappears
            # or a played card leaves hand. Never infer effects from its ID.
            self.selection_origin={'command':action['command'],'kind':kind,
                'turn':game.get('combat_state',{}).get('turn'),
                'scope':'Observed action before this combat selection opened; source fields are from before execution, not the generated card current cost.'}
            if played:self.selection_origin['card']=deepcopy(played)
            if kind=='potion':
                index=action.get('potion_index');potions=game.get('potions',[])
                if type(index) is int and 0<=index<len(potions):
                    self.selection_origin['potion']=deepcopy(potions[index])
        self.recent.append({'floor': game.get('floor'), 'screen_type': game.get('screen_type'),
                            'command': action['command'], 'kind': kind,
                            'card_id': played.get('id'), 'potion_id': action.get('potion_id')})
        self.recent = self.recent[-8:]

    def filter(self, raw, actions):
        game = raw['game_state']
        if game.get('screen_type') != 'COMBAT_REWARD':
            return actions
        return [a for a in actions if not (a.get('kind') == 'reward'
            and a.get('reward', {}).get('reward_type') == 'CARD'
            and reward_key(game, a['reward'].get('reward_source_id')) in self.declined)]

    def visit(self, summary, actions):
        visible = {k: v for k, v in summary.items() if k not in {'decision_context', 'experience_context'}}
        key = json.dumps(gameplay_state([visible, actions]), sort_keys=True, ensure_ascii=False)
        self.visits[key] += 1
        if self.visits[key] > 1:
            self.repeated_requests += 1
        return self.visits[key] <= 2

    def context(self, summary, actions):
        result={'recent_actions': deepcopy(self.recent),
                'objective': 'Win the entire encounter while conserving health and consumables for the run. Compare offense, defense and setup over future turns, not only the next immediate hit.',
                'future_draw_order': 'unknown; draw-pile contents are available, but do not assume a favorable order',
                'declined_card_rewards': [list(x) for x in sorted(self.declined, key=str)],
                'remaining_energy': summary.get('player', {}).get('energy'),
                'playable_card_count': len({a.get('card_uuid') for a in actions if a.get('kind') == 'play'}),
                'enemy_intents': [{k: e.get(k) for k in ('name', 'intent', 'move_adjusted_damage', 'move_hits')}
                                  for e in summary.get('enemies', [])]}
        if summary.get('combat_context') is not None and self.selection_origin:
            result['selection_origin']=deepcopy(self.selection_origin)
        return result


def describe_candidates(summary, actions):
    """Expose available descriptions without resolving unknown dynamic templates."""
    actions = deepcopy(actions)
    cards = {c.get('card_uuid', c.get('uuid')): c for c in summary.get('hand', [])}
    for action in actions:
        if summary.get('screen_type')=='SHOP_SCREEN' and action.get('command')=='LEAVE':
            action['description']='结束购物并离开商店房间。'
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




confirmation = effect_evidence  # Compatibility for old offline replay fixtures.

class RunSession(SessionRuntime):
    """Reuse only common pause/timeout handling from the combat session."""

    def __init__(self, output_dir, mode='jev', max_decisions=500, selector=None, *, run_id=None, catalog=None, start_new=False, max_actions=2000, max_seconds=5400, search_config=None, stop_after_combat=False, seed=None, require_native_receipts=False, planning_mode=None):
        self.memory = DecisionMemory()
        self.turn_queue = []
        self.shop_queue = []
        self.shop_location = None
        self.shop_metadata = {}
        self.require_native_receipts=require_native_receipts
        self.transaction=None
        self._journal_restored=False
        self.native_rejections=0
        self.stale_decisions=0
        self.plan_metadata = {}
        self.search_config = search_config or SearchConfig()
        self.planning_mode = planning_mode or os.environ.get('JEV_PLANNING_MODE','native')
        if self.planning_mode not in {'enumerate','native'}:
            raise ValueError('Unknown planning mode')
        self.stop_after_combat = stop_after_combat
        self.battle_identity = None
        self.battle_start_hp = None
        self.planned_selection = None
        self.native_selection_intent = None
        self.native_navigation_intent = None
        self.checkpoint_pending = None
        self.decision_id = None
        self.seed = seed
        self._memory_restored = False
        self.max_actions, self.max_seconds = max_actions, max_seconds
        self.started_at = time.monotonic()
        self.run_id = run_id
        self.native_run_id = None
        self.start_new = start_new
        self.started_new_game = bool(start_new)
        game_dir = Path(os.environ.get('STS_GAME_DIRECTORY', r'C:\Program Files (x86)\Steam\steamapps\common\SlayTheSpire'))
        self.catalog = catalog if catalog is not None else load_catalog(game_dir / 'desktop-1.0.jar')
        self.native_catalog = (NativeCatalogStore(Path(__file__).resolve().parents[1]/'data/native-catalog.json')
                               if catalog is None else None)
        self.step_id = 0
        self.run_identity = None
        self.last_raw = None
        self.result = None
        self.sent_ack = False
        super().__init__(output_dir, mode, max_decisions, selector)
        self.run_id = self.run_id or self.id
        self.phase = 'ready'

    def _combat_planner(self):
        if self.planning_mode == 'native':
            from . import native_sequences
            return native_sequences
        return experimental_planner()

    def _record(self, status, **fields):
        if status == 'action_confirmed':
            if self.planning_mode=='native':
                self.native_selection_intent=SelectionIntent.after_choice(fields['decision']['action'],fields['after'],self.step_id)
                self.native_navigation_intent=NavigationIntent.after_action(fields['decision']['action'],fields['before'],fields['after'],self.step_id)
            try:
                self.memory.observe(fields['before'], fields['after'], fields['decision'])
            except Exception as error:
                fields['decision_memory_warning']=type(error).__name__
            self._confirm_shop_step(fields['decision']['action'])
        if status == 'created':
            fields['components'] = LOADED_COMPONENTS['components']
            fields['execution_limits']=dict(max_seconds=self.max_seconds,max_actions=self.max_actions,max_decisions=self.max_decisions)
            fields['runtime_policy'] = dict(planning=self.planning_mode,
                combat_comparison_limit=32,
                decision_protocol='local-shortlist32-one-choice-v1' if self.planning_mode=='native' else os.environ.get('JEV_COMBAT_PROTOCOL','temporal'))
        row = {'schema_version': 3, 'policy_version': 'native-broad-shortlist32-v1' if self.planning_mode=='native' else 'enumerate-simple-b1', 'code_version': LOADED_COMPONENTS['code_version'], 'timestamp': datetime.now(timezone.utc).isoformat(), 'session_id': self.id, 'run_id': self.run_id or self.id, 'battle_id': self.battle_identity, 'decision_id': self.decision_id, 'step_id': self.step_id, 'mode': self.mode, 'status': status, 'calls': self.calls, 'actions': self.actions, **fields}
        append_record(self.output_dir / 'runs.jsonl', row)
        if self.native_run_id and status in {'action_confirmed', 'shop_plan_selected', 'shop_plan_invalidated', 'request_started'}:
            append_record(recovery_path(self.output_dir, self.run_id), row)

    def _confirm_shop_step(self,action):
        if self.shop_queue and action.get('kind','').startswith('screen_shop_'):
            if shop_identity(action)==shop_identity(self.shop_queue[0]): self.shop_queue.pop(0)

    def _remember_shop_plan(self,raw,decision):
        self.shop_queue=deepcopy(decision['action']['steps'])
        self.shop_location=self.memory.location(raw['game_state'])
        self.shop_metadata={k:deepcopy(v) for k,v in decision.items() if k!='action'}
        self.shop_metadata['shop_plan_id']=decision['action']['id']

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
        if self.native_run_id is None:
            return
        path = recovery_path(self.output_dir, self.run_id)
        try:
            with path.open(encoding='utf-8') as stream:
                for line in stream:
                    try:
                        row = json.loads(line)
                        if row.get('run_id') == self.run_id and row.get('mode') == self.mode:
                            for name in ('calls', 'actions', 'step_id'):
                                value = row.get(name, 0)
                                if type(value) is int:
                                    setattr(self, name, max(getattr(self, name), value))
                            if row.get('status') == 'action_confirmed':
                                self.memory.observe(row['before'], row['after'], row['decision'])
                                if self.planning_mode=='native':
                                    self.native_selection_intent=SelectionIntent.after_choice(row['decision']['action'],row['after'],row.get('step_id',0))
                                    self.native_navigation_intent=NavigationIntent.after_action(row['decision']['action'],row['before'],row['after'],row.get('step_id',0))
                                self._confirm_shop_step(row['decision']['action'])
                            elif row.get('status') == 'shop_plan_selected':
                                self._remember_shop_plan(row['before'],row['decision'])
                            elif row.get('status') == 'shop_plan_invalidated':
                                self.shop_queue=[]
                            elif (row.get('status') == 'request_started'
                                  and row.get('code_version')==LOADED_COMPONENTS['code_version']):
                                self.memory.visit(row['summary'], row.get('loop_candidates', row['candidates']))
                    except (ValueError, KeyError, TypeError, AttributeError):
                        continue
        except OSError:
            pass

    def tick(self):
        super().tick()
        if not self.stopped and self.run_identity is not None and time.monotonic() - self.started_at >= self.max_seconds:
            return self._stop('time_limit')
        if not self.stopped and self.transaction:
            reason=self.transaction.timeout_reason()
            if reason:return self._stop(reason,transaction_id=self.transaction.data['id'])
        return []

    def idle_commands(self):
        self.tick()
        if not self.stopped and self.transaction:
            command=self.transaction.poll()
            if command:return [command]
        return []

    def _prepare_wire(self,raw):
        if protocol(raw) is None:
            return self.sent[1]['action']['command']
        context={k:deepcopy(getattr(self,k)) for k in ('run_id','native_run_id','calls','actions','step_id','run_identity',
            'planned_selection','plan_metadata','checkpoint_pending','shop_queue','shop_location','shop_metadata',
            'battle_identity','battle_start_hp')}
        context['native_selection_intent']=self.native_selection_intent.to_record() if self.native_selection_intent else None
        context['native_navigation_intent']=self.native_navigation_intent.to_record() if self.native_navigation_intent else None
        self.transaction=PendingAction.create(self.output_dir/'pending-action.json',raw,self.sent[1],context)
        self.deadline=None
        self._record('transaction_prepared',transaction_id=self.transaction.data['id'],
                     epoch=self.transaction.data['epoch'],expected_revision=self.transaction.data['revision'])
        return self.transaction.wire

    def _restore_transaction(self,raw):
        if self._journal_restored:return
        self._journal_restored=True
        if protocol(raw) is None:return
        pending=PendingAction.load(self.output_dir/'pending-action.json')
        if pending is None:return
        for key,value in pending.data['context'].items():
            if key=='native_selection_intent':value=SelectionIntent.from_record(value)
            if key=='native_navigation_intent':value=NavigationIntent.from_record(value)
            if key in {'run_identity','shop_location','battle_identity'} and value is not None:value=tuple(value)
            setattr(self,key,value)
        self.transaction=pending
        self.sent=(pending.data['before'],pending.data['decision'])
        self.pending=self.sent;self.sent_ack=True;self.phase='confirming';self.deadline=None
        self.start_new=False
        self._record('transaction_recovered',transaction_id=pending.data['id'])

    def _reconcile_native(self,raw):
        if not self.transaction:return
        status,receipt=self.transaction.observe(raw)
        if status=='waiting':return
        if status not in {'settled','rejected'}:
            self._stop('native_'+status,transaction_id=self.transaction.data['id']);return
        before,decision=self.sent
        if status=='settled':
            effect=None;warning=None
            try:
                effect=effect_evidence(before,raw,decision['action'])
            except Exception as error:
                warning=type(error).__name__
            self._record('action_confirmed',before=before,after=raw,decision=decision,
                command=decision['action']['command'],transaction_id=self.transaction.data['id'],
                native_receipt=receipt,evidence='Matching native command accepted and settled at a new decision boundary.',
                effect_evidence=effect,effect_audit_warning=warning)
            self.native_rejections=0
            self.stale_decisions=0
        else:
            self._record('action_rejected',before=before,after=raw,decision=decision,
                         transaction_id=self.transaction.data['id'],native_receipt=receipt)
            self.native_rejections+=1
            self.turn_queue=[]
            self.memory.visits.clear()
            if decision['action'].get('kind')=='start':self.start_new=True
        self.transaction.finish();self.transaction=None
        self.sent=self.pending=None;self.phase='ready';self.deadline=None
        if status=='settled' and self.checkpoint_pending:
            self._record('checkpoint_reached',after=raw,reason=self.checkpoint_pending)
            self.checkpoint_pending=None
        if status=='rejected' and (receipt.get('error') not in {'stale_revision','busy'} or self.native_rejections>=3):
            self._stop('native_action_rejected',native_receipt=receipt)

    def _select_choice(self, raw, summary, candidates):
        if self.mode == 'jev':
            load_jev_key()
        self.calls += 1
        self.decision_id = f'{self.run_id}:{self.calls}'
        if summary.get('screen_type')=='SHOP_SCREEN' and self.planning_mode=='enumerate':
            candidates,shopping=generate_shop_plans(summary,candidates)
            summary=dict(summary,shop_search=shopping)
            self._record('shop_search_completed',before=raw,search=shopping)
        self._record('request_started', before=raw, summary=summary, candidates=candidates,
                     loop_candidates=self._loop_candidates, instructions=instructions_for(summary))
        with capture_http(self.output_dir, self.decision_id):
            decision = self.selector(summary, candidates)
        requests=decision.get('model_requests',1)
        if self.mode=='jev' and type(requests) is int and requests>1:self.calls+=requests-1
        action = validate_choice(decision['action']['id'], candidates)
        if decision['action'] != action:
            raise SelectionError('Selector changed native action.')
        if action.get('kind')=='shop_plan':
            self._remember_shop_plan(raw,decision)
            self._record('shop_plan_selected',before=raw,decision=decision)
            actual=bind_shop_queue(self.shop_queue,summary,self._loop_candidates)
            if actual is None: raise SelectionError('Selected shop package no longer matches native stock.')
            return dict(decision,action=actual,shop_plan_id=action['id'])
        return decision

    def _stop(self, reason, **fields):
        if self.pending:
            fields.setdefault('before', self.pending[0])
            fields.setdefault('decision', self.pending[1])
        fields.setdefault('after', self.last_raw)
        return super()._stop(reason, **fields)

    def command_sent(self, command: str) -> None:
        """Record transport acknowledgement separately from observed execution."""
        expected=self.transaction.wire if self.transaction else self.sent[1]['action']['command'] if self.sent else None
        if self.phase != 'confirming' or command != expected:
            self._stop('unexpected_command')
            return
        self.sent_ack = True
        if self.transaction:self.transaction.sent()
        self._record('command_sent',command=self.sent[1]['action']['command'],wire_command=command,
                     transaction_id=self.transaction.data['id'] if self.transaction else None,
                     before=self.sent[0],decision=self.sent[1])

    def _receive_menu(self, raw):
        if self.phase == 'confirming' or raw.get('ready_for_command') is not True:
            return []
        if self.phase == 'checking_start':
            if gameplay_state(raw) != gameplay_state(self.pending[0]):
                return self._stop('state_changed')
            self.sent = self.pending
            self.sent_ack = False
            self.phase = 'confirming'
            self.deadline = time.monotonic() + 30
            self.start_new = False
            self.actions += 1
            command = self.sent[1]['action']['command']
            self._record('command_prepared', before=raw, decision=self.sent[1], command=command)
            return [self._prepare_wire(raw)]
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
        try:raw=augment_event(raw,self.output_dir)
        except ValueError as error:return self._stop('native_event_observation_error',message=str(error))
        self.last_raw = deepcopy(raw)
        try:
            if self.require_native_receipts and protocol(raw) is None:
                return self._stop('native_protocol_required')
            self._restore_transaction(raw)
            if raw.get('in_game') is True and raw.get('ready_for_command') is True:
                game = raw.get('game_state', {})
                identity = GameIdentity.from_game(game)
                if self.require_native_receipts and identity is None:
                    return self._stop('native_identity_required')
                if self.native_run_id and (identity is None or identity.run_id != self.native_run_id):
                    return self._stop('run_changed')
                if identity and self.native_run_id is None:
                    if self.run_identity is not None:
                        return self._stop('run_identity_changed')
                    previous_id = self.run_id
                    self.run_id = self.native_run_id = identity.run_id
                    self._record('run_bound', previous_run_id=previous_id)
                # Restore before recording a recovered settled receipt, so the
                # just-confirmed event is not applied twice to live memory.
                self._restore_memory()
            self._reconcile_native(raw)
        except (ProtocolError,OSError,ValueError) as error:
            return self._stop('transaction_protocol_error',message=str(error))
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
            if self.transaction:
                return []  # Native acceptance/settlement clocks own this wait.
            if self.deadline is None:
                self.deadline = time.monotonic() + 15
            if raw.get('_native_event_waiting'):
                time.sleep(0.1)
                return ['STATE']
            return []
        game = raw.get('game_state', {})
        try:
            identity = GameIdentity.from_game(game)
        except ValueError as error:
            return self._stop('invalid_run_identity', message=str(error))
        if self.battle_identity is None and game.get('room_phase') == 'COMBAT':
            self.battle_identity = ((identity.run_id, identity.encounter_id) if identity and identity.encounter_id
                                    else (self.run_id, str(uuid4())))
            self.battle_start_hp = game.get('current_hp')
            self._record('battle_started', before=raw, start_hp=self.battle_start_hp)
        if self.run_identity is not None:
            if raw.get('in_game') is not True:
                return self._stop('left_game')
            if (game.get('seed'), game.get('class'), game.get('ascension_level')) != self.run_identity:
                return self._stop('run_changed')
        elif raw.get('in_game') is True:
            self.run_identity = (game.get('seed'), game.get('class'), game.get('ascension_level'))
            if game.get('floor') == 0 and identity is None:
                self.started_new_game = True
            self.started_at = time.monotonic()
        self._restore_memory()
        if self.phase == 'confirming':
            if not self.sent_ack:
                return self._stop('send_not_acknowledged')
            if self.transaction:
                # Acceptance/settlement is independent of observable effects.
                # The idle watchdog queries its ID; never guess from this state.
                return []
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
            catalog=self.catalog
            if self.native_catalog:
                native=self.native_catalog.refresh().localization()
                catalog={k:{**self.catalog.get(k,{}),**native.get(k,{})} for k in ('cards','powers','relics')}
            summary = enrich_summary(summary, catalog)
            if self.native_catalog:
                glossary=self.native_catalog.keyword_context(summary)
                if glossary:summary['native_keyword_glossary']=glossary
            candidates = describe_candidates(summary, self.memory.filter(raw, candidates))
            summary['decision_context'] = self.memory.context(summary, candidates)
            if self.turn_queue and game.get('room_phase')=='COMBAT' and game.get('screen_type') in {'GRID','HAND_SELECT','CARD_REWARD'}:
                summary['selected_combat_continuation']={
                    'plan_id':self.plan_metadata.get('plan_id'),
                    'remaining_actions':[{k:v for k,v in step.items() if k not in {'expected_before','execution_contract'}} for step in self.turn_queue],
                    'scope':'Previously selected by the model; after this native selection, resume only if actual resource and legality checks still match.'}
        except UnsupportedState as error:
            return self._stop('unsupported_state', message=str(error))
        if self.phase == 'checking':
            if gameplay_state(raw) != gameplay_state(self.pending[0]):
                if protocol(raw) is None:return self._stop('state_changed')
                self._record('decision_invalidated',reason='fresh_state_changed_before_send',before=raw)
                self.stale_decisions+=1
                self.pending=None;self.turn_queue=[];self.planned_selection=None
                self.phase='ready';self.deadline=None
                if self.stale_decisions>=3:return self._stop('state_not_stable')
            else:
                self.tick()
                if self.stopped:return []
                self.sent = self.pending
                self.sent_ack = False
                self.phase = 'confirming'
                self.deadline = time.monotonic() + 30
                self.actions += 1
                command = self.sent[1]['action']['command']
                self._record('command_prepared', before=raw, decision=self.sent[1], command=command)
                return [self._prepare_wire(raw)]
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
        navigation_action=self.native_navigation_intent.resolve(raw,candidates) if self.native_navigation_intent else None
        if self.native_navigation_intent and navigation_action is None:self.native_navigation_intent=None
        if navigation_action is None and not self.memory.visit(summary, candidates):
            return self._stop('decision_loop', repeated_requests=self.memory.repeated_requests)
        self.step_id += 1
        self._loop_candidates = candidates
        try:
            selection_action = None
            native_commit=False
            if self.native_selection_intent:
                selection_action=self.native_selection_intent.resolve(raw,candidates)
                native_commit=selection_action is not None
                if not native_commit:self.native_selection_intent=None
            if not selection_action and self.planned_selection and game.get('screen_type') in {'HAND_SELECT', 'GRID'}:
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
            if self.planning_mode=='native' and free_reward and free_reward['reward']['reward_type']!='CARD':
                free_reward=None
            action = self._combat_planner().bind_plan_step(self.turn_queue[0], summary, candidates) if self.turn_queue and 'player' in summary else None
            inspect_shop = next((a for a in candidates if a.get('kind') == 'screen_shop_room'
                                 and self.memory.location(game) not in self.memory.inspected_shops), None)
            shop_action=None
            if self.shop_queue and game.get('screen_type')=='SHOP_SCREEN':
                if self.shop_location==self.memory.location(game):
                    shop_action=bind_shop_queue(self.shop_queue,summary,candidates)
                if shop_action is None:
                    self._record('shop_plan_invalidated',before=raw,reason='stock_price_capacity_or_location_changed')
                    self.shop_queue=[]
            source = 'reused_turn_plan'
            selecting_in_combat=(game.get('room_phase')=='COMBAT' and game.get('screen_type') in {'GRID','HAND_SELECT','CARD_REWARD'})
            if self.turn_queue and not action and not selection_action and not selecting_in_combat:
                self._record('plan_invalidated', before=raw, reason='native_sequence_boundary' if self.planning_mode == 'native' else 'observed_state_differs_from_turn_forecast', expected=self.turn_queue[0]['expected_before'], observed=summary)
                self.turn_queue = []
            if selection_action:
                decision = ({'action':selection_action,'requested_model':None,'returned_model':None,'confidence':None,
                             'selection_commit_of':self.native_selection_intent.selected_at_step} if native_commit
                            else {'action': selection_action, **self.plan_metadata})
                source = 'native_selection_commit' if native_commit else 'planned_card_selection'
                action = None
                if selection_action['command'] == 'CONFIRM': self.planned_selection = None
            elif navigation_action:
                decision={'action':navigation_action,'requested_model':None,'returned_model':None,'confidence':None,
                          'navigation_commit_of':self.native_navigation_intent.chosen_at_step}
                source='native_navigation_commit'
                self.turn_queue=[]
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
            elif shop_action:
                decision={'action':shop_action,**self.shop_metadata}
                source='reused_shop_plan'
            elif len(candidates) == 1 and candidates[0].get('kind') == 'end':
                decision = {'action': candidates[0], 'requested_model': None, 'returned_model': None, 'confidence': None}
                action = None
                self.turn_queue = []
                source = 'local_only_end'
            elif not action:
                plans, search = self._combat_planner().generate_plans(summary, candidates, self.search_config) if 'player' in summary else ([], {})
                if 'player' in summary:
                    summary = dict(summary, combat_choice_mode=search['policy'], candidate_generation=search)
                    self._record('search_completed', decision_id=f'{self.run_id}:{self.calls + 1}', search=search, candidates=plans)
                if plans and search['policy']=='native_conditional_sequences':
                    from .shortlist import select as shortlist
                    started=time.perf_counter()
                    plans,shortlist_stats=shortlist(plans)
                    shortlist_stats['elapsed_ms']=round((time.perf_counter()-started)*1000,2)
                    summary=dict(summary,shortlist=shortlist_stats,_final_shortlist=True)
                    self._record('shortlist_completed',shortlist=shortlist_stats,
                                 retained_ids=[p['id'] for p in plans])
                if plans:
                    if self.calls >= self.max_decisions:
                        return self._stop('decision_limit')
                    planned_potions = set(search.get('planned_potion_uses', []))
                    standalone_potions = [a for a in candidates if a.get('kind') == 'potion'
                                          and a['id'] not in planned_potions]
                    selection = self._select_choice(raw, summary, plans if search['policy'] == 'native_conditional_sequences' else plans + standalone_potions)
                    source = 'selected_turn_plan'
                    if selection['action']['kind'] == 'turn_plan':
                        self.turn_queue = deepcopy(selection['action']['steps'])
                        self.plan_metadata = {k: deepcopy(v) for k, v in selection.items() if k != 'action'}
                        self.plan_metadata['plan_id'] = selection['action']['id']
                        self._record('plan_selected', before=raw, decision=selection, source=source)
                        action = self._combat_planner().bind_plan_step(self.turn_queue[0], summary, candidates)
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
            return self._stop('selection_error',message=str(error) if isinstance(error,SelectionError) else 'Invalid selector response.',
                              error_code=getattr(error,'code',None),reported_attempts=getattr(error,'attempts',None))
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
        # Only reached at an explicit, reconciled pause boundary. Rebind all
        # imported classes/functions so the new controller actually uses disk
        # fixes instead of silently retaining an old selector.
        modules=['models','monsters','shopping','state','selectors','external_decision','transactions','config','records','screens','effects','combat_protocol','native_sequences','shortlist']
        if old.planning_mode=='enumerate':modules+=['rules','position','turn_planner']
        for name in modules:
            importlib.reload(importlib.import_module('.'+name,__package__))
        current=importlib.reload(importlib.import_module(__name__))
        session_factory=current.RunSession
    new = session_factory(old.output_dir, mode=old.mode,
                          max_decisions=old.calls + budget, run_id=old.run_id,
                          require_native_receipts=old.require_native_receipts,planning_mode=old.planning_mode)
    new.calls, new.actions, new.step_id = old.calls, old.actions, old.step_id
    new.run_identity = old.run_identity
    if hasattr(old, 'memory'):
        new.memory = deepcopy(old.memory)
        # An explicit recovery grants a fresh attempt; failed requests are not
        # confirmed gameplay. Preserve rewards/history, reset only loop limits.
        new.memory.visits.clear()
        new.memory.repeated_requests=0
        new._memory_restored = True
    for name in ('started_at', 'max_actions', 'max_seconds', 'search_config', 'planning_mode', 'stop_after_combat', 'battle_identity', 'battle_start_hp', 'seed', 'native_run_id'):
        if hasattr(old, name):
            setattr(new, name, getattr(old, name))
    new.planned_selection = old.planned_selection
    new.native_selection_intent = old.native_selection_intent
    new.native_navigation_intent = old.native_navigation_intent
    new.plan_metadata = deepcopy(old.plan_metadata)
    new.decision_id = old.decision_id
    new.checkpoint_pending = old.checkpoint_pending
    for name in ('shop_queue','shop_location','shop_metadata'):
        if hasattr(old,name): setattr(new,name,deepcopy(getattr(old,name)))
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
        if old.transaction:
            if old.last_raw:old._reconcile_native(old.last_raw)
            if old.transaction:
                if not getattr(old,'resume_waiting',False):
                    old._record('resume_waiting_receipt',transaction_id=old.transaction.data['id'])
                    old.resume_waiting=True
                    old.transaction.restart_wait()
                reason=old.transaction.timeout_reason()
                if reason:
                    flag.unlink()
                    old._record('resume_failed',reason=reason,transaction_id=old.transaction.data['id'])
                    old.resume_waiting=False
                    return old,False
                command=old.transaction.poll()
                if command:old.resume_query_pending=command
                return old,False
    if old.sent is not None and old.sent_ack:
        from .session import confirmation
        confirm=confirmation
        if session_factory is None and old.sent[1]['action'].get('kind','').startswith('screen_'):
            # A fixed confirmation adapter must be usable BEFORE the old
            # outstanding action is reconciled; otherwise recovery deadlocks.
            screens=importlib.reload(importlib.import_module('.screens',__package__))
            confirm=screens.confirm_screen
        raw = old.last_raw
        evidence = None
        if raw and raw.get('ready_for_command') is True and raw.get('in_game') is True:
            game = raw.get('game_state', {})
            identity = (game.get('seed'), game.get('class'), game.get('ascension_level'))
            if old.run_identity is None and old.sent[1]['action'].get('kind') == 'start':
                evidence = confirm(old.sent[0], raw, old.sent[1]['action'])
                if evidence:
                    old.run_identity = identity
            elif identity == old.run_identity:
                evidence = confirm(old.sent[0], raw, old.sent[1]['action'])
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
