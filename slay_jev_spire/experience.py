"""Evidence-based review and cross-run lessons; no model weight updates."""
from copy import deepcopy
import json
from pathlib import Path

from .journey import prepare_journey
from .turn_planner import turn_plans, proven_lethal_plan
from .decision_memory import DecisionMemory
from .state import UnsupportedState

MESSAGES = {
    'missed_verified_lethal': '存在程序验证的本回合击杀牌序时，优先完成击杀；不要为无必要的防御或提前结束回合放弃击杀。反伤、死亡触发和未知效果必须先验证。',
    'reward_reopen_loop': '同一组卡牌奖励已经明确跳过后，不要反复打开；领取其余奖励或继续。保持原生索引。',
}


def _load(path):
    if not path.exists():
        return {'version': 1, 'lessons': []}
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('version') != 1 or not isinstance(value.get('lessons'), list):
        raise ValueError('Invalid experience schema.')
    return value


def review_and_store(rows, path: Path):
    """Review observed decisions, never assert unverified counterfactual outcomes."""
    findings = []
    confirmations = {(r.get('run_id'), r.get('step_id')): r for r in rows if r.get('status') == 'action_confirmed'}
    memories = {}
    for row in rows:
        code = None
        raw = row.get('before') or {}; game = raw.get('game_state', {})
        identity = (game.get('seed'), game.get('class'), game.get('ascension_level'))
        memory = memories.setdefault(identity, DecisionMemory())
        if row.get('status') == 'decision' and row.get('source') not in {'local_verified_lethal', 'local_verified_turn_plan', 'reused_turn_plan'}:
            action = row.get('decision', {}).get('action', {})
            if action.get('kind') in {'end', 'play'}:
                card = next((c for c in game.get('combat_state', {}).get('hand', []) if c.get('uuid') == action.get('card_uuid')), {})
                if action.get('kind') == 'end' or card.get('id') == 'Defend_R':
                    try:
                        summary, actions = prepare_journey(raw)
                        plans = turn_plans(summary, actions) or []
                        if any(p['outcome']['combat_won'] for p in plans) or proven_lethal_plan(summary, actions):
                            code = 'missed_verified_lethal'
                    except (UnsupportedState, KeyError, TypeError):
                        pass
        if row.get('status') == 'decision' and game.get('screen_type') == 'COMBAT_REWARD':
            action = row.get('decision', {}).get('action', {})
            if action.get('kind') == 'reward' and action.get('reward', {}).get('reward_type') == 'CARD' and not memory.filter(raw, [action]):
                code = 'reward_reopen_loop'
        if row.get('status') == 'action_confirmed' and row.get('decision'):
            try:
                memory.observe(raw, row.get('after') or {}, row['decision'])
            except (KeyError, TypeError):
                pass
        if not code:
            continue
        confirmed = confirmations.get((row.get('run_id'), row.get('step_id')), {})
        after = (confirmed.get('after') or {}).get('game_state', {})
        before_hp, after_hp = game.get('current_hp'), after.get('current_hp')
        findings.append({'code': code, 'run_id': row.get('run_id'), 'step_id': row.get('step_id'),
                         'floor': game.get('floor'), 'turn': game.get('combat_state', {}).get('turn'),
                         'hp_loss': max(0, before_hp - after_hp) if type(before_hp) is int and type(after_hp) is int else None,
                         'evidence_scope': 'verified_current_state_alternative; hp_delta_observed_not_counterfactual'})
    memory = _load(path)
    for finding in findings:
        lesson = next((x for x in memory['lessons'] if x.get('code') == finding['code']), None)
        if lesson is None:
            lesson = {'code': finding['code'], 'occurrences': 0, 'evidence': []}
            memory['lessons'].append(lesson)
        identity = (finding['run_id'], finding['step_id'])
        if any((e.get('run_id'), e.get('step_id')) == identity for e in lesson['evidence']):
            continue
        lesson['evidence'].append(finding)
        lesson['occurrences'] += 1
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)
    return findings


def applicable_experiences(summary, path: Path):
    try:
        lessons = _load(path)['lessons']
    except (OSError, ValueError, TypeError):
        return []
    screen = summary.get('screen_type')
    result = []
    for lesson in lessons:
        code = lesson.get('code')
        relevant = (code == 'missed_verified_lethal' and screen == 'NONE') or (code == 'reward_reopen_loop' and screen in {'CARD_REWARD', 'COMBAT_REWARD'})
        if relevant:
            result.append({'code': code, 'message': MESSAGES[code], 'occurrences': lesson.get('occurrences'),
                           'evidence': deepcopy(lesson.get('evidence', [])[-3:]), 'source': 'verified_local_review'})
    return result
