"""构造与追加单步记录，并提供终端和 JSONL 共用的密钥脱敏。"""

from datetime import datetime, timezone
import json
import os
import hashlib
from collections import Counter
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



def run_metrics(rows):
    requests = {r['step_id']: r for r in rows if r.get('status') == 'request_started'}
    decisions = {r['step_id'] for r in rows if r.get('status') == 'decision' and r['step_id'] in requests}
    failed = {r['step_id'] for r in rows if r.get('status') == 'stopped' and r.get('reason') == 'selection_error'} & requests.keys()
    seen = set()
    duplicates = 0
    for r in requests.values():
        summary = {k: v for k, v in r.get('summary', {}).items() if k not in {'decision_context', 'experience_context'}}
        key = json.dumps([summary, r.get('candidates', [])], sort_keys=True, ensure_ascii=False)
        duplicates += key in seen
        seen.add(key)
    extra_calls={r['step_id']:max(0,r.get('decision',{}).get('model_requests',1)-1)
                 for r in rows if r.get('status')=='decision' and r['step_id'] in requests}
    return {'api_requests': len(requests)+sum(extra_calls.values()), 'logical_requests':len(requests),
            'api_count_complete':not failed and not (requests.keys()-decisions),
            'valid_decisions': len(decisions),
            'confirmed_actions': len({r['step_id'] for r in rows if r.get('status') == 'action_confirmed'}),
            'duplicate_requests': duplicates, 'failed_requests': len(failed),
            'pending_requests': len(requests.keys() - decisions - failed)}


def battle_metrics(rows, expected=10):
    """Report all completed battles, with deaths zeroed and interruptions visible."""
    battles = {}
    for row in rows:
        if row.get('status') == 'battle_complete':
            battles[(row.get('run_id'), str(row.get('battle_id')))] = row
    results = [r['result'] for r in battles.values()]
    wins = sum(r['victory'] is True for r in results)
    hp = sum(r.get('end_hp', 0) if r['victory'] else 0 for r in results)
    stops = [r for r in rows if r.get('status') == 'stopped' and r.get('reason') not in {'battle_finished','game_over'}]
    decisions = [r for r in rows if r.get('status') == 'plan_selected']
    return dict(expected_battles=expected, completed_battles=len(results), wins=wins,
                win_rate_completed=wins / len(results) if results else None,
                win_rate_scheduled=wins / expected if expected else None,
                mean_remaining_hp=hp / len(results) if results else None,
                incomplete=max(0, expected-len(results)), technical_stops=[r.get('reason') for r in stops],
                api_requests=run_metrics(rows)['api_requests'],
                mean_confidence=sum(r['decision']['confidence'] for r in decisions if r['decision'].get('confidence') is not None) / len(decisions) if decisions and all(r['decision'].get('confidence') is not None for r in decisions) else None,
                battles=[dict(run_id=r.get('run_id'), battle_id=r.get('battle_id'), **r['result']) for r in battles.values()])


def source_manifest():
    """Capture component identities once at session creation, not on every action."""
    root = Path(__file__).resolve().parent
    components = {str(p.relative_to(root)).replace('\\', '/'): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted(root.rglob('*.py')) if '__pycache__' not in p.parts}
    version = hashlib.sha256(json.dumps(components, sort_keys=True).encode()).hexdigest()
    return {'code_version': version, 'components': components}


def read_run_records(path, run_id=None):
    """Select a run without materializing other runs' large state snapshots."""
    if run_id is None:
        last = None
        with Path(path).open(encoding='utf-8') as stream:
            for line in stream:
                if line.strip(): last = line
        if last is None: raise ValueError('No run records.')
        run_id = json.loads(last).get('run_id')
    if not run_id: raise ValueError('Missing run ID.')
    rows = []
    with Path(path).open(encoding='utf-8') as stream:
        for line in stream:
            if run_id not in line: continue
            row = json.loads(line)
            if row.get('run_id') == run_id: rows.append(row)
    if not rows: raise ValueError('Run ID was not found.')
    return rows


def review_run(rows, run_id, metadata=None):
    """Evidence packet for a model reviewer; observations are not causal verdicts."""
    events = [r for r in rows if r.get('run_id') == run_id]
    if not events: raise ValueError('Run ID was not found.')
    names = ('NONE','MAP','COMBAT_REWARD','CARD_REWARD','EVENT','CHEST','SHOP_ROOM',
             'SHOP_SCREEN','REST','BOSS_REWARD','GRID','HAND_SELECT','GAME_OVER')
    coverage = {name: {'observed': False, 'decisions': 0, 'confirmed_actions': 0,
                       'locations': set(), 'action_kinds': Counter()} for name in names}
    last_game = {}; max_floor = 0; max_act = 0; models = set(); hotspots = []; inspected_rewards = set(); card_usage = {}
    inspected_shops = set()
    for row in events:
        for raw in (row.get('before'), row.get('after')):
            game = _game(raw)
            if not game: continue
            last_game = game
            max_floor = max(max_floor, game.get('floor') or 0)
            max_act = max(max_act, game.get('act') or 0)
            name = game.get('screen_type')
            if name == 'CARD_REWARD': inspected_rewards.add((game.get('act'),game.get('floor')))
            if name == 'SHOP_SCREEN': inspected_shops.add((game.get('act'),game.get('floor')))
            if name in coverage:
                coverage[name]['observed'] = True
                coverage[name]['locations'].add((game.get('act'), game.get('floor')))
        before = _game(row.get('before')); name = before.get('screen_type')
        status = row.get('status'); decision = row.get('decision') or {}
        if status == 'request_started':
            playable = {c['id']:c for c in row.get('summary',{}).get('hand',[]) if c.get('is_playable')}
            for identifier, card in playable.items():
                usage=card_usage.setdefault(identifier,{'playable_model_decisions':0,'confirmed_play_commands':0,'max_upgrade_seen':0,'unmodeled_requests':0})
                usage['playable_model_decisions'] += 1
                usage['max_upgrade_seen'] = max(usage['max_upgrade_seen'],card.get('upgrades',0))
                if any('unmodeled_card:'+identifier in c.get('uncertainties',[]) for c in row.get('candidates',[])):
                    usage['unmodeled_requests'] += 1
        if status == 'action_confirmed' and decision.get('action',{}).get('kind') == 'play':
            uid=decision['action'].get('card_uuid')
            card=next((c for c in before.get('combat_state',{}).get('hand',[]) if c.get('uuid')==uid),{})
            if card.get('id'):
                usage=card_usage.setdefault(card['id'],{'playable_model_decisions':0,'confirmed_play_commands':0,'max_upgrade_seen':0,'unmodeled_requests':0})
                usage['confirmed_play_commands'] += 1
        if decision.get('returned_model'): models.add(decision['returned_model'])
        if name in coverage and status == 'decision': coverage[name]['decisions'] += 1
        if name in coverage and status == 'action_confirmed':
            coverage[name]['confirmed_actions'] += 1
            coverage[name]['action_kinds'][decision.get('action',{}).get('kind','unknown')] += 1
            if (name == 'SHOP_ROOM' and decision.get('action',{}).get('kind') in {'screen_proceed','screen_leave'}
                    and (before.get('act'),before.get('floor')) not in inspected_shops):
                hotspots.append(dict(category='uninspected_shop',component_hint=['session.py'],
                    step_id=row.get('step_id'),floor=before.get('floor'),gold=before.get('gold'),
                    evidence_status='confirmed_shop_left_before_stock_inspection'))
            if (name == 'COMBAT_REWARD' and decision.get('action',{}).get('kind') == 'proceed'
                    and (before.get('act'),before.get('floor')) not in inspected_rewards
                    and any(r.get('reward_type') == 'CARD' for r in before.get('screen_state',{}).get('rewards',[]))):
                hotspots.append(dict(category='uninspected_card_reward',component_hint=['session.py'],
                    step_id=row.get('step_id'),decision_id=row.get('decision_id'),floor=before.get('floor'),
                    evidence_status='confirmed_unopened_reward_left'))
            if name == 'COMBAT_REWARD' and decision.get('action',{}).get('kind') == 'proceed':
                relics=[r.get('relic',{}).get('id') for r in before.get('screen_state',{}).get('rewards',[]) if r.get('reward_type')=='RELIC']
                if relics: hotspots.append(dict(category='unclaimed_relic',component_hint=['session.py','selectors.py'],
                    step_id=row.get('step_id'),floor=before.get('floor'),relic_ids=relics,evidence_status='observed_reward_left'))
        if status == 'plan_invalidated':
            expected, observed = row.get('expected',{}), row.get('observed',{})
            hotspots.append(dict(category='forecast_divergence', component_hint=['rules.py','turn_planner.py'],
                step_id=row.get('step_id'), decision_id=row.get('decision_id'), floor=before.get('floor'),
                differing_fields=sorted(k for k in set(expected)|set(observed) if expected.get(k)!=observed.get(k)),
                evidence_status='requires_rule_review'))
        if status == 'stopped' and row.get('reason') not in {'paused','battle_finished','game_over','decision_limit','time_limit','action_limit'}:
            reason = row.get('reason')
            component = ['selectors.py'] if reason=='selection_error' else ['screens.py','session.py'] if name!='NONE' else ['state.py','rules.py','session.py']
            hotspots.append(dict(category='technical_stop', reason=reason, component_hint=component,
                step_id=row.get('step_id'), decision_id=row.get('decision_id'), floor=before.get('floor'),
                message=row.get('message'), evidence_status='observed_stop_not_proven_root_cause'))
        if status == 'action_confirmed':
            after = _game(row.get('after')); a,b = before.get('current_hp'),after.get('current_hp')
            if type(a) is int and type(b) is int and a-b >= 10:
                hotspots.append(dict(category='large_observed_hp_loss', hp_loss=a-b,
                    step_id=row.get('step_id'), decision_id=row.get('decision_id'), floor=before.get('floor'),
                    component_hint=['turn_planner.py','selectors.py'], evidence_status='review_candidate_not_proven_mistake'))
    for value in coverage.values():
        value['locations'] = [list(x) for x in sorted(value['locations'], key=str)]
        value['action_kinds'] = dict(value['action_kinds'])
    lifecycle = next((r for r in reversed(events) if r.get('status') in {'complete','stopped','resumed'}),None)
    terminal = lifecycle if lifecycle and lifecycle['status'] != 'resumed' else None
    game_over = _game(terminal.get('after')) if terminal else {}
    completed = bool(terminal and terminal['status']=='complete' and game_over.get('screen_type')=='GAME_OVER'
                     and type(game_over.get('screen_state',{}).get('victory')) is bool)
    created = next((r for r in events if r.get('status')=='created'),{})
    requests = [r for r in events if r.get('status')=='request_started']
    choices = []
    for row in events:
        d=row.get('decision',{}); distribution=d.get('probabilities')
        if row.get('status') not in {'plan_selected','decision'} or not distribution: continue
        if any(c['decision_id']==row.get('decision_id') for c in choices): continue
        top=sorted(distribution.items(),key=lambda x:x[1],reverse=True)[:2]
        choices.append(dict(decision_id=row.get('decision_id'),step_id=row.get('step_id'),
            confidence=d.get('confidence'),top_choices=top,
            margin=top[0][1]-top[1][1] if len(top)>1 else None))
    choices.sort(key=lambda c: c['margin'] if c['margin'] is not None else 1)
    return dict(schema_version=1,run_id=run_id,metadata=metadata or {},
        code_version=created.get('code_version'),components=created.get('components',{}),models=sorted(models),
        outcome=dict(completed=completed,victory=game_over.get('screen_state',{}).get('victory') if completed else None,
                     reason=terminal.get('reason') if terminal else None,max_act=max_act,max_floor=max_floor,
                     final_hp=last_game.get('current_hp'),score=game_over.get('screen_state',{}).get('score') if completed else None),
        metrics=run_metrics(events),coverage=coverage,hotspots=hotspots,card_usage=card_usage,
        uncertain_choices=choices[:12],request_count=len(requests),
        review_contract={'facts':'Use the linked raw steps and candidates; HP deltas do not prove causality.',
            'changes':'Propose the smallest component change with a regression fixture and a measurable acceptance criterion.',
            'validation':'Re-run the affected fixture and a comparable run. One win or one loss does not establish improvement.'})






def _cell(value) -> str:
    return str(value if value is not None else '—').replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def _game(raw) -> dict:
    return raw.get('game_state', {}) if isinstance(raw, dict) else {}


def _delta(before, after, key):
    a, b = before.get(key), after.get(key)
    return f'{b - a:+d}' if type(a) is int and type(b) is int else '—'


def render_run_report(rows: list[dict], run_id: str) -> str:
    """只汇总指定运行的证据，未确认的命令和中断不会写成成功。"""
    events = [row for row in rows if row.get('run_id') == run_id]
    if not events:
        raise ValueError('找不到指定运行的记录。')
    lifecycle = next((r for r in reversed(events) if r.get('status') in {'stopped', 'complete', 'resumed'}), None)
    terminal = lifecycle if lifecycle and lifecycle['status'] != 'resumed' else None
    outcome = '进行中；未确认整局结束'
    if terminal:
        game = _game(terminal.get('after'))
        result = game.get('screen_state', {})
        if terminal['status'] == 'complete' and game.get('screen_type') == 'GAME_OVER' and type(result.get('victory')) is bool:
            outcome = ('胜利' if result['victory'] else '死亡') + '；分数 ' + _cell(result.get('score'))
        elif terminal['status'] == 'stopped':
            outcome = '中断；原因 ' + _cell(terminal.get('reason'))
        else:
            outcome = '未确认整局结束'
    mode = next((r.get('mode') for r in events if r.get('mode')), '未知')
    metrics = run_metrics(events)
    lines = ['# 对局决策记录', '', f'运行：`{_cell(run_id)}`', '', f'选择模式：{_cell(mode)}', '', f'结果：{outcome}', '',
             '下表记录观察到的状态变化。血量、金币变化属于本次动作到确认之间的观测，不代表已证明因果或策略优劣。', '']
    lines += [f"请求尝试 {metrics['api_requests']}；合法选择 {metrics['valid_decisions']}；已确认动作 {metrics['confirmed_actions']}；失败请求 {metrics['failed_requests']}；重复局面请求 {metrics['duplicate_requests']}；无返回记录 {metrics['pending_requests']}。", '',
              '重复局面需结合动作判断是否浪费；请求尝试数不是服务商账单或 token 使用量。', '']
    decisions = [r for r in events if r.get('status') == 'decision']
    if not decisions:
        lines.append('尚无决策记录。')
    else:
        lines += ['| 步骤 | 楼层 / 界面 | 选择与命令 | 置信度 | 执行状态 | 血量变化 | 金币变化 | 结果证据 |',
                  '| --- | --- | --- | --- | --- | --- | --- | --- |']
        by_step = {}
        for event in events:
            by_step.setdefault(event.get('step_id'), []).append(event)
        for row in decisions:
            step = row.get('step_id')
            following = by_step.get(step, [])
            confirmation = next((r for r in following if r.get('status') == 'action_confirmed'), None)
            sent = any(r.get('status') == 'command_sent' for r in following)
            status = '已确认' if confirmation else ('已发送，未确认' if sent else '未发送')
            before = _game(row.get('before'))
            after = _game(confirmation.get('after')) if confirmation else {}
            decision = row.get('decision', {})
            action = decision.get('action', {})
            values = [step, f"{before.get('floor', '—')} / {before.get('screen_type', '—')}",
                      f"{action.get('description', '—')} ({action.get('command', '—')})",
                      decision.get('confidence'), status, _delta(before, after, 'current_hp'),
                      _delta(before, after, 'gold'), confirmation.get('evidence') if confirmation else None]
            lines.append('| ' + ' | '.join(_cell(v) for v in values) + ' |')
    return safe_text('\n'.join(lines) + '\n')
