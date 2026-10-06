"""Audit saved turns and optionally replay predeclared pairs; no game commands."""
import argparse
from collections import Counter
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from slay_jev_spire.native_sequences import generate_plans
from slay_jev_spire.records import append_record

CASES = {
    '298b8d25-5ebb-43ae-bba6-52d2cb43f9b0': {171, 175, 190},
    'eb174714-2d9d-43b2-bbd7-4df0d3e0e22a': {204, 208},
    '7fffafda-9e32-4cb2-b702-86700df24e12': {94},
    'ec1aadf1-02ec-439d-90a2-7fde112953d9': {118},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True, action='append')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jev', action='store_true')
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--display', choices=('references','readable'), default='references')
    parser.add_argument('--order', choices=('original','reverse','hashed'), default='original')
    parser.add_argument('--group-by-first-step', action='store_true')
    parser.add_argument('--step', type=int, action='append')
    parser.add_argument('--shortlist', action='store_true')
    parser.add_argument('--effects', action='store_true',help='Read-only B experiment on the exact same shortlist.')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.jev:
        from slay_jev_spire.config import load_jev_key
        from slay_jev_spire.selectors import choose_jev
        load_jev_key()
    from slay_jev_spire import selectors
    original_payload = selectors.simple_combat_payload
    original_instructions = selectors.instructions_for
    def modeled_effects(summary,plan):
        from slay_jev_spire import rules
        state=rules.initial(summary)
        if state['uncertainties']:return None
        evaluated=0
        for step in plan['sequence']:
            if step['kind']=='end':break
            if step['kind']!='play':return None
            legal=[s for s in rules.legal_steps(state) if s['card_uuid']==step['card_uuid'] and s.get('target_index')==step.get('target_index')]
            if not legal:return None
            selection=any(s.get('selection_uuid') for s in legal)
            state=rules.play(state,step);evaluated+=1
            if state['uncertainties']:return None
            if selection:rules.checkpoint(state,'native_selection')
            if state['checkpoint']:break
        out=rules.outcome(state)
        return dict(evaluated_actions=evaluated,after_actions=dict(player_hp=state['hp'],
            enemy_hp=out['enemy_hp_by_target'],block=state['block'],energy=state['energy']),
            if_end_now=dict(player_hp=out['player_hp_after_turn'],incoming_hp_loss=out['incoming_hp_loss'],scope=out['forecast_scope']),
            cancelled_attacks=out.get('interruptions',[]),boundary=state['checkpoint'])
    def readable_payload(summary, actions, **kwargs):
        state, criteria, refs = original_payload(summary, actions, **kwargs)
        if summary.get('combat_choice_mode') == 'native_conditional_sequences':
            for action in actions:
                if args.display=='readable':criteria[action['id']] = {'actions': action['description']}
                if args.effects:criteria[action['id']]['known_results']=modeled_effects(summary,action)
        return state, criteria, refs
    def readable_instructions(summary):
        text=original_instructions(summary)
        if args.display=='readable':text=text.replace('sequence引用turn_steps，按顺序执行；', 'actions直接列出按顺序执行的牌名和目标；')
        if args.effects and summary.get('combat_choice_mode')=='native_conditional_sequences':
            text=text.replace('没有计算卡牌、遗物、能力或敌人的效果，没有伤害预测或本地收益评分。',
                'known_results是现有规则覆盖部分的简易结果，不是收益分或胜率；null表示未知。'
                'after_actions是执行已评估动作后的状态，if_end_now只是假如此刻结束回合，不是观察段的必然后果。'
                'cancelled_attacks明确列出被机制取消的当前攻击，仍须考虑新阶段和后续局面。')
        return text
    rows = []; sources = Counter(); searches = []; seen = set()
    for path in sorted({p for directory in args.evidence for p in directory.glob('*.jsonl.gz')}):
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                if row.get('status') != 'decision' or 'player' not in row.get('summary', {}):
                    continue
                sources[row.get('source')] += 1
                key = (row['run_id'], str(row.get('battle_id')), row['summary']['turn'])
                if key not in seen:
                    seen.add(key)
                    pool, search = generate_plans(row['summary'], row['candidates'])
                    if args.shortlist:
                        from slay_jev_spire.shortlist import select
                        started=time.perf_counter()
                        _,short=select(pool)
                        search['shortlist']=dict(short,elapsed_ms=round((time.perf_counter()-started)*1000,2))
                    searches.append(dict(run_id=row['run_id'], step=row['step_id'], **search))
                if row['step_id'] in CASES.get(row['run_id'], set()):
                    rows.append(row)
    audit = dict(baseline_sources=dict(sources), turns=len(searches),
        truncated=dict(Counter(reason for s in searches for reason in s['truncated'])),
        time_budget_rate=sum('time_budget' in s['truncated'] for s in searches)/len(searches),
        candidate_count_median=statistics.median(s['candidates'] for s in searches),
        candidate_count_max=max(s['candidates'] for s in searches),
        elapsed_ms_median=statistics.median(s['elapsed_ms'] for s in searches),
        elapsed_ms_max=max(s['elapsed_ms'] for s in searches), searches=searches)
    if args.shortlist:
        audit['shortlist_candidates_median']=statistics.median(s['shortlist']['retained_candidates'] for s in searches)
        audit['shortlist_candidates_max']=max(s['shortlist']['retained_candidates'] for s in searches)
        audit['shortlist_ms_median']=statistics.median(s['shortlist']['elapsed_ms'] for s in searches)
        audit['shortlist_ms_max']=max(s['shortlist']['elapsed_ms'] for s in searches)
    (args.output/'audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in audit.items() if k!='searches'}), flush=True)
    for row in rows:
        if args.step and row['step_id'] not in args.step:
            continue
        summary = row['summary']; plans, search = generate_plans(summary, row['candidates'])
        shortlist_stats=None
        if args.shortlist:
            from slay_jev_spire.shortlist import select
            plans,shortlist_stats=select(plans)
        if args.order=='reverse': plans.reverse()
        if args.order=='hashed': plans.sort(key=lambda p: hashlib.sha256(p['id'].encode()).hexdigest())
        record = dict(run_id=row['run_id'], step=row['step_id'], search=search,
                      shortlist=shortlist_stats,
                      original_action=row['decision']['action'], original_latency_ms=row['decision'].get('latency_ms'))
        if not args.jev:
            append_record(args.output/'cases.jsonl', dict(record, summary=summary, candidates=plans))
            continue
        for repeat in range(args.repeats):
            # Alternate order, with the same complete native state. This is an
            # architecture comparison, not a claim that only one field changed.
            for arm in (('single', 'sequence') if repeat % 2 == 0 else ('sequence', 'single')):
                state = deepcopy(summary)
                if arm == 'sequence':
                    state.update(combat_choice_mode=search['policy'], candidate_generation=search)
                    if args.shortlist:state.update(shortlist=shortlist_stats,_final_shortlist=True)
                else:
                    state['combat_choice_mode']='native_actions'
                    for key in ('candidate_generation','shortlist','_final_shortlist'):
                        state.pop(key,None)
                from slay_jev_spire.jev_provider import capture_http
                comparison_started = time.perf_counter()
                with capture_http(args.output, f'{row["run_id"]}:{row["step_id"]}:{repeat}:{arm}'), \
                     patch.object(selectors, 'simple_combat_payload', readable_payload if args.display=='readable' or args.effects else original_payload), \
                     patch.object(selectors, 'instructions_for', readable_instructions if args.display=='readable' or args.effects else original_instructions):
                    if arm=='sequence' and args.group_by_first_step:
                        groups={}
                        for plan in plans:
                            key=json.dumps(plan['sequence'][0],sort_keys=True)
                            groups.setdefault(key,[]).append(plan)
                        finalists=[]; group_decisions=[]
                        for group in groups.values():
                            if len(group)==1:
                                finalists.append(group[0]);continue
                            decision=choose_jev(state,group)
                            group_decisions.append(decision);finalists.append(decision['action'])
                        result=choose_jev(state,finalists)
                        result['first_step_groups']=group_decisions
                        result['model_requests']=result.get('model_requests',1)+sum(d.get('model_requests',1) for d in group_decisions)
                    else:
                        result = choose_jev(state, plans if arm == 'sequence' else row['candidates'])
                result['latency_ms'] = round((time.perf_counter() - comparison_started)*1000, 2)
                append_record(args.output/'replay.jsonl', dict(record, repeat=repeat, arm=arm, decision=result))
                print(json.dumps(dict(step=row['step_id'], arm=arm, repeat=repeat,
                    action=result['action']['description'], model_requests=result.get('model_requests',1),
                    latency_ms=result.get('latency_ms'), model=result.get('returned_model')), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
