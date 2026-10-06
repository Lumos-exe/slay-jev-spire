"""Offline evidence only: no model calls, game commands, or policy tuning.

Run from the repository: python tools/audit_strategy.py --output report.json
Recall uses exhaustive legal sequences and explicit lexicographic objectives,
never the planner's heuristic. It tests retrieval under the current rules, not
whether those rules match the native game or maximize full-run win probability.
"""
import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import json
import math
from pathlib import Path
import platform
import statistics
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from slay_jev_spire import rules
from slay_jev_spire import turn_planner
from slay_jev_spire.state import prepare_native_combat
from slay_jev_spire.turn_planner import generate_plans, SearchConfig


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def source_path(path):
    try: return str(path.resolve().relative_to(ROOT))
    except ValueError: return str(path.resolve())


def search_metrics(searches):
    n = len(searches)
    reasons = Counter(reason for s in searches for reason in set(s.get('truncated', [])))
    times = [s['elapsed_ms'] for s in searches if 'elapsed_ms' in s]
    return dict(searches=n, truncated=dict(reasons),
                time_budget_rate=reasons['time_budget'] / n if n else None,
                beam_pruned_searches=sum(bool(s.get('beam_pruned')) for s in searches),
                continuation_searches=sum(s.get('continuation_nodes', 0) > 0 for s in searches),
                continuation_nodes=sum(s.get('continuation_nodes', 0) for s in searches),
                expanded=sum(s.get('expanded', 0) for s in searches),
                elapsed_p50_ms=statistics.median(times) if times else None,
                elapsed_p95_ms=percentile(times, .95), elapsed_max_ms=max(times, default=None))


def audit_logs(paths):
    reports, all_searches, seen = [], [], set()
    for path in paths:
        searches, shops, unknowns, powers_seen = [], [], Counter(), Counter()
        fields = Counter()
        components = {}
        for line in path.open(encoding='utf-8-sig'):
            row = json.loads(line)
            components.update(row.get('components', {}))
            status = row.get('status')
            if status == 'search_completed':
                # Event identities, not state hashes: repeated searches count as calls.
                key = (row.get('run_id'), row.get('session_id'), row.get('decision_id'),
                       row.get('step_id'), row.get('timestamp'))
                if key in seen:
                    continue
                seen.add(key)
                searches.append(row['search'])
                for u in {u for p in row.get('candidates', []) for u in p.get('uncertainties', [])}:
                    unknowns[u] += 1
            if status != 'decision':
                continue
            summary = row.get('summary', {})
            if 'player' in summary:
                fields['combat_decisions'] += 1
                for owner in [summary['player']] + summary.get('enemies', []):
                    for power in owner.get('powers', []):
                        powers_seen[power['id']] += 1
                        fields['power_instances'] += 1
                        fields['power_native_description'] += bool(power.get('native_description'))
                        fields['power_type'] += bool(power.get('power_type'))
                for enemy in summary.get('enemies', []):
                    fields['enemy_instances'] += 1
                    fields['enemy_move_id'] += 'move_id' in enemy
                    if enemy['intent'].startswith('ATTACK'):
                        fields['attack_intents'] += 1
                        fields['attack_base_damage'] += type(enemy.get('move_base_damage')) is int and enemy['move_base_damage'] >= 0
                        fields['attack_adjusted_damage'] += type(enemy.get('move_adjusted_damage')) is int and enemy['move_adjusted_damage'] >= 0
                        fields['attack_hits'] += type(enemy.get('move_hits')) is int and enemy['move_hits'] > 0
                for card in summary.get('hand', []):
                    fields['hand_cards'] += 1
                    fields['hand_native_values'] += card.get('native_values', {}).get('source') == 'game_card_fields'
            game = row.get('before', {}).get('game_state', {})
            if game.get('screen_type') in {'SHOP_ROOM', 'SHOP_SCREEN'}:
                decision = row['decision']; action = decision['action']
                stock = [dict(action=a['id'], kind=a['kind'], item=a.get('item', {}).get('id', 'purge'),
                              price=a['item']['price']) for a in row.get('candidates', []) if 'item' in a]
                shops.append(dict(step_id=row['step_id'], floor=game.get('floor'), screen=game['screen_type'],
                    gold=game['gold'], hp=game.get('current_hp'), chosen=action['id'], kind=action['kind'],
                    source=row.get('source'), stock=stock, probabilities=decision.get('probabilities'),
                    confidence=decision.get('confidence'), deck=[c['id'] for c in game.get('deck', [])],
                    relics=[r['id'] for r in game.get('relics', [])]))
        all_searches.extend(searches)
        reports.append(dict(path=source_path(path), components=components,
                            **search_metrics(searches), shops=shops,
                            input_fields=dict(fields), observed_powers=dict(powers_seen),
                            candidate_uncertainties_per_search=dict(unknowns)))
    return dict(aggregate=search_metrics(all_searches), runs=reports)


def card(ident, cost, kind='ATTACK', damage=0, block=0, magic=0, **extra):
    return dict(id=ident, name=ident, uuid=ident, cost=cost, type=kind, upgrades=0,
                has_target=kind == 'ATTACK', is_playable=True, exhausts=ident in rules.EXHAUST,
                ethereal=False, native_values=dict(source='game_card_fields', cost_for_turn=cost,
                    base_damage=damage, damage=damage, base_block=block, block=block,
                    magic_number=magic, base_magic_number=magic), **extra)


def fixture(name, hand, *, energy=3, hp=30, enemy_hp=40, damage=12, enemies=1, powers=(), enemy_powers=(), objective='survival', relics=()):
    hand = [deepcopy(c) for c in hand]
    for i, c in enumerate(hand):
        c['uuid'] = f'{i}:{c["id"]}'
        c['is_playable'] = c['cost'] >= -1 and c['cost'] <= energy
    def power(p):
        return dict(id=p[0], name=p[0], amount=p[1])
    raw = dict(in_game=True, ready_for_command=True, available_commands=['play', 'end'],
        game_state={'class': 'IRONCLAD', 'room_phase': 'COMBAT', 'action_phase': 'WAITING_ON_USER',
                    'screen_type': 'NONE', 'is_screen_up': False, 'relics':list(relics), 'potions':[],
                    'combat_state':dict(turn=1, limbo=[], hand=hand, draw_pile=[], discard_pile=[], exhaust_pile=[],
                        player=dict(current_hp=hp, max_hp=80, block=0, energy=energy, orbs=[], powers=list(map(power,powers))),
                        monsters=[dict(id='Cultist', name='Cultist', current_hp=enemy_hp, max_hp=enemy_hp,
                            block=0, powers=list(map(power,enemy_powers)), is_gone=False, half_dead=False,
                            intent='ATTACK', move_base_damage=damage, move_adjusted_damage=damage,
                            move_hits=1) for _ in range(enemies)])})
    return dict(name=name, raw=raw, objective=objective)


def fixed_cases():
    strike = card('Strike_R',1,damage=6)
    defend = card('Defend_R',1,'SKILL',block=5)
    bash = card('Bash',2,damage=8,magic=2)
    inflame = card('Inflame',1,'POWER',magic=2)
    cases = [
        fixture('bash_before_strike_lethal', [strike,bash],enemy_hp=16),
        fixture('block_to_survive', [strike,defend,defend,bash],hp=5,damage=14),
        fixture('strength_before_multi_hit', [strike,inflame,card('Twin Strike',1,damage=5)],enemy_hp=80),
        fixture('body_slam_after_block', [card('Body Slam',1),defend,card('Ghostly Armor',1,'SKILL',block=10)],enemy_hp=40),
        fixture('artifact_before_vulnerable', [bash,card('Thunderclap',1,damage=4,magic=1),strike],energy=4,
                enemy_powers=[('Artifact',1)],enemy_hp=40),
        fixture('exhaust_status_for_block', [card('Second Wind',1,'SKILL',block=5),defend,card('Wound',-2,'STATUS'),strike],
                powers=[('Feel No Pain',3)],hp=10,damage=20),
        fixture('fiend_fire_order', [card('Fiend Fire',2,damage=7),strike,defend,inflame],enemy_hp=40),
        fixture('multi_target_kill_and_block', [strike,strike,bash,defend],enemy_hp=12,enemies=2),
        fixture('thorns_low_hp', [strike,card('Twin Strike',1,damage=5),defend],hp=4,enemy_hp=20,enemy_powers=[('Thorns',3)]),
        fixture('orichalcum_do_not_block_for_five', [strike,defend],damage=6,relics=[{'id':'Orichalcum'}]),
        fixture('wide_hand_survival', [strike,strike,bash,defend,defend,inflame,card('Iron Wave',1,damage=5,block=5),
            card('Twin Strike',1,damage=5)], energy=4,hp=8,damage=20,enemy_hp=90),
        fixture('wide_multi_target_damage', [strike,strike,bash,defend,inflame,card('Cleave',1,damage=8),
            card('Twin Strike',1,damage=5)],energy=4,enemies=3,enemy_hp=24,objective='damage'),
    ]
    for case in cases:
        for c in case['raw']['game_state']['combat_state']['hand']:
            if c['id'] in rules.AOE: c['has_target'] = False
    return cases


def objective_value(out, objective):
    if out['forecast_scope'] != 'deterministic':
        return None
    hp = out['player_hp_after_turn']
    enemy_hp = sum(out['enemy_hp_after_turn_by_target'])
    # Stated objectives, not hidden weighted utility. Survival is always first.
    if objective == 'survival':
        return (hp > 0, out['combat_won'], hp, -enemy_hp)
    if objective == 'damage':
        return (hp > 0, out['combat_won'], -enemy_hp, hp)
    raise ValueError(objective)


def exhaustive_reference(summary, actions, objective, max_nodes=200000, max_seconds=30):
    """No beam, no heuristic, no state projection/dominance deduplication.

    Explicitly reject a partial oracle. Every node permits ending the turn;
    all modeled potion prefixes are included exactly as in production.
    """
    started = time.monotonic()
    root = rules.initial(summary)
    root_legal = {(a.get('card_uuid'), a.get('target_index')) for a in actions if a['kind']=='play'}
    stack = [(root, [])]; nodes = 0; best = None; witness = None
    while stack:
        if nodes >= max_nodes or time.monotonic()-started >= max_seconds:
            return dict(complete=False, reason='reference_budget', nodes=nodes)
        state, steps = stack.pop(); nodes += 1
        out = rules.outcome(state)
        if out['forecast_scope'] != 'deterministic':
            return dict(complete=False, reason='information_boundary_or_unmodeled_effect', nodes=nodes)
        if steps or any(a['command']=='END' for a in actions):
            value = objective_value(out,objective)
            if best is None or value > best:
                best, witness = value, steps
        available = rules.legal_steps(state)
        if not steps: available = rules.potion_steps(root,summary,actions) + available
        for step in available:
            potion = step['kind']=='potion'
            if not steps and not potion and (step['card_uuid'],step['target_index']) not in root_legal:
                continue
            child = rules.use_potion(state,step) if potion else rules.play(state,step)
            stack.append((child,steps+[step]))
    return dict(complete=True,nodes=nodes,optimum=best,witness=witness,
                elapsed_ms=round((time.monotonic()-started)*1000,2))


def audit_recall(cases, config=None):
    config = config or SearchConfig()
    results=[]
    for case in cases:
        summary,actions=prepare_native_combat(case['raw'])
        reference=exhaustive_reference(summary,actions,case['objective'])
        plans,search=generate_plans(summary,actions,config)
        values=[v for p in plans if 'outcome' in p and (v:=objective_value(p['outcome'],case['objective'])) is not None]
        best=max(values,default=None)
        hit=best==reference['optimum'] if reference['complete'] else None
        result=dict(name=case['name'],objective=case['objective'],reference=reference,
            best_candidate=best,hit=hit,search=search,
            input_sha256=sha256(json.dumps(case['raw'],sort_keys=True).encode()).hexdigest())
        if hit is False:
            result['failure_stage'] = 'computation_guard' if search.get('truncated') else 'rule_coverage'
            result['selection_trace'] = []
        results.append(result)
    eligible=[r for r in results if r['hit'] is not None]
    return dict(config=asdict(config), eligible=len(eligible), hits=sum(r['hit'] for r in eligible),
                recall_at_k=sum(r['hit'] for r in eligible)/len(eligible) if eligible else None,
                excluded=len(results)-len(eligible), cases=results)


def replay_log(path):
    """Replay exact saved planner inputs on this machine, without calling Jev.

    These timings describe the current machine, not the original Windows host.
    """
    saved = {}
    inputs = []
    for line in path.open(encoding='utf-8-sig'):
        row = json.loads(line)
        if row.get('status') == 'search_completed':
            saved[row['decision_id']] = row
        if row.get('status') == 'request_started' and row.get('decision_id') in saved:
            old = saved.pop(row['decision_id'])
            inputs.append((old,row['summary'],row['loop_candidates']))
    results = []
    for old,summary,actions in inputs:
        _,stats=generate_plans(summary,actions)
        results.append(dict(step_id=old['step_id'],historical=old['search'],current=stats))
    return dict(path=source_path(path),matched_inputs=len(inputs),unmatched_searches=len(saved),
                current=search_metrics([r['current'] for r in results]),cases=results)


def profile_continuation():
    case=fixture('draw_heavy_diagnostic',[
        card('Pommel Strike',1,damage=9,magic=1),card('Shrug It Off',1,'SKILL',block=8,magic=1),
        card('Battle Trance',0,'SKILL',magic=3),card('Offering',0,'SKILL',magic=3),
        card('Strike_R',1,damage=6),card('Defend_R',1,'SKILL',block=5),
        card('Inflame',1,'POWER',magic=2)],energy=4)
    draw=card('Strike_R',1,damage=6);draw['uuid']='draw:strike'
    case['raw']['game_state']['combat_state']['draw_pile']=[draw]
    summary,actions=prepare_native_combat(case['raw'])
    _,baseline=generate_plans(summary,actions)
    return dict(scope='Unknown draws end the prefix; no scored hypothetical continuation.',
                baseline=baseline, continuation_calls=0, continuation_ms=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--logs',nargs='*',type=Path)
    parser.add_argument('--replay',type=Path,help='Exact saved inputs; no model calls.')
    args=parser.parse_args()
    paths=args.logs if args.logs is not None else sorted((ROOT/'logs/full-run-loop').glob('round-*/run.jsonl'))
    report=dict(scope='Offline audit. Historical builds separated; recall shares the simulator, not the beam heuristic. No full-run optimality claim.',
        environment=dict(platform=platform.platform(),python=platform.python_version()),
        components={p.name:sha256(p.read_bytes()).hexdigest() for p in (ROOT/'slay_jev_spire').glob('*.py')},
        logs=audit_logs(paths),recall=audit_recall(fixed_cases()))
    report['continuation_profile']=profile_continuation()
    if args.replay: report['replay']=replay_log(args.replay.resolve())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(output=str(args.output),historical=report['logs']['aggregate'],
                         recall={k:v for k,v in report['recall'].items() if k!='cases'}),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
