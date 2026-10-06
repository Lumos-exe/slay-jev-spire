"""Mechanical, broad sampling of command sequences; no game-value judgment."""
from collections import defaultdict, deque
from hashlib import sha256
import json


def signature(plan):
    # Only action identity participates. Names, damage, HP, powers, predicted
    # outcomes and whether an effect is modeled cannot influence selection.
    return tuple(tuple(s.get(k) for k in ('kind','card_uuid','target_index',
        'selection_uuid','potion_index','potion_id','subaction')) for s in plan['sequence'])


def stable_order(value):
    """Reproducible tie-breaking, never a recommendation or utility score."""
    return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def action_prefix(plan):
    key=signature(plan)
    return key[:-1] if plan['sequence'][-1]['kind']=='end' else key


def select(plans, limit=32):
    if type(limit) is not int or limit<1:
        raise ValueError('Shortlist limit must be positive.')
    unique={}
    keys={}
    for plan in plans:
        key=signature(plan)
        unique.setdefault(key,plan)
        keys[id(plan)]=key
    pool=list(unique.values())
    # Runtime UUIDs are random identifiers, not decision information. Number
    # instances by first appearance in the generated pool for tie-breaking;
    # retain actual UUIDs in signatures, returned plans and execution checks.
    instances={}
    for plan in pool:
        for step in plan['sequence']:
            for field in ('card_uuid','selection_uuid'):
                uid=step.get(field)
                if uid is not None:instances.setdefault(uid,len(instances))
    def local_row(row):
        row=list(row)
        for index in (1,3):
            if row[index] is not None:row[index]=instances[row[index]]
        return tuple(row)
    # Cache per invocation only: selection repeatedly visits each candidate in
    # several coverage passes. These are the same keys as before, not scores.
    rows={row:local_row(row) for key in unique for row in key}
    row_orders={row:stable_order(local) for row,local in rows.items()}
    orders={};resource_keys={};prefix_keys={}
    for key,plan in unique.items():
        orders[id(plan)]=stable_order(tuple(rows[row] for row in key))
        resource_keys[id(plan)]=tuple(rows[row] for row in sorted(
            (row for row in key if row[0]!='end'),key=row_orders.__getitem__))
        prefix_keys[id(plan)]=key[:-1] if plan['sequence'][-1]['kind']=='end' else key
    def plan_key(plan):
        return keys[id(plan)]
    def prefix_key(plan):
        return prefix_keys[id(plan)]
    def plan_order(plan):
        return orders[id(plan)]
    def first_order(first):
        return stable_order(local_row(first))
    def resource_set(plan):
        return resource_keys[id(plan)]
    chosen=[];selected=set();prefixes=set();resources=set()
    def take(plan):
        key=plan_key(plan)
        if key not in selected and len(chosen)<limit:
            chosen.append(plan);selected.add(key);prefixes.add(prefix_key(plan));resources.add(resource_set(plan))
    # Preserve requested decision forms, without judging which is better.
    for predicate in (
        lambda p:len(p['sequence'])==1 and p['sequence'][0]['kind']=='end',
        lambda p:len(p['sequence'])==1 and p['sequence'][0]['kind']!='end',
        lambda p:sum(s['kind']!='end' for s in p['sequence'])>1,
    ):
        choices=[p for p in pool if predicate(p)]
        if choices:take(min(choices,key=plan_order))
    branches=defaultdict(lambda:defaultdict(list))
    for plan in pool:
        key=plan_key(plan)
        if key in selected:continue
        # Rotate first actions, lengths and END/OBSERVE, without card ratings.
        shape=(sum(s['kind']!='end' for s in plan['sequence']),plan['sequence'][-1]['kind']=='end')
        branches[key[0]][shape].append(plan)
    queues={}
    for first,shapes in branches.items():
        buckets=deque(deque(sorted(shapes[shape],key=plan_order))
                      for shape in sorted(shapes))
        branch=deque()
        while buckets:
            bucket=buckets.popleft();branch.append(bucket.popleft())
            if bucket:buckets.append(bucket)
        queues[first]=branch
    # First cover different combinations of concrete resources/targets, then
    # different orders, then ending variants. Orders and endings remain distinct
    # candidates, never declared equivalent or evaluated for game value.
    for key_function,covered in ((resource_set,resources),(prefix_key,prefixes),(plan_key,selected)):
        represented={plan_key(p)[0] for p in chosen}
        active=deque(sorted(queues,key=lambda first:(first in represented,first_order(first))))
        deferred=defaultdict(deque)
        while active and len(chosen)<limit:
            first=active.popleft()
            while queues[first] and key_function(queues[first][0]) in covered:
                deferred[first].append(queues[first].popleft())
            if queues[first]:take(queues[first].popleft())
            if queues[first]:active.append(first)
        queues=deferred
    all_first={plan_key(p)[0] for p in pool}
    retained_first={plan_key(p)[0] for p in chosen}
    stats=dict(policy='branch_round_robin_v2',identity_order='first_appearance_in_generated_pool',input_candidates=len(plans),
        unique_candidates=len(pool),exact_duplicates_removed=len(plans)-len(pool),
        retained_candidates=len(chosen),limit=limit,omitted_candidates=len(pool)-len(chosen),
        action_prefixes_retained=len(prefixes),
        resource_combinations_available=len({resource_set(p) for p in pool}),
        resource_combinations_retained=len(resources),
        first_actions_available=len(all_first),first_actions_retained=len(retained_first),
        sequence_lengths_retained=sorted({sum(s['kind']!='end' for s in p['sequence']) for p in chosen}),
        scope='Mechanical branch coverage only; no estimate of quality or optimal-plan recall.')
    # Presentation is a fixed permutation of local command identities; it does
    # not turn lexical command order (e.g. END first) into a recommendation.
    return sorted(chosen,key=lambda p:sha256(plan_order(p).encode()).hexdigest()),stats
