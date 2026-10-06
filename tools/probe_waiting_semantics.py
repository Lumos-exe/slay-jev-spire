"""Small synthetic controls separating provider comprehension from game transport.

These are intentionally simplified counterfactuals, not production payloads or
substitutes for full-state gameplay evaluations. No game commands are executed.
"""
import argparse
import json
import os
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from typesafe_sdk import Choice, RetryPolicy, TypeSafeClient, TypeSafeError
    from slay_jev_spire.config import load_jev_key
    from slay_jev_spire.jev_provider import recording_transport

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    output = args.directory / 'results.jsonl'
    if output.exists():
        raise ValueError('Use a fresh result directory')
    load_jev_key()
    cases = [
        ('nob_wait', '敌人本回合不攻击，只强化自己。每打出一张技能，敌人永久增加2点力量。',
         '打出防御：花1能量，获得5格挡。这是一张技能。', 'end'),
        ('hex_wait', '敌人本回合不攻击，只施加减益。每打出一张非攻击牌，抽牌堆增加1张不能打出的晕眩。',
         '打出防御：花1能量，获得5格挡。这是一张技能。', 'end'),
        ('block_to_survive', '敌人本回合攻击，造成10点伤害。玩家生命5，格挡0。',
         '打出防御：花1能量，获得8格挡。这是一张技能。', 'play'),
        ('attack_to_win', '敌人只剩6生命，格挡0，且没有任何被动反击或复活机制。',
         '打出打击：花1能量，对敌人造成6点伤害。', 'play'),
    ]
    (args.directory / 'manifest.json').write_text(json.dumps({
        'scope': __doc__, 'cases': cases, 'repeats': 3,
        'profiles': ['implicit_turn_rules', 'explicit_turn_rules'],
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    with output.open('a', encoding='utf-8') as out:
        for repeat in range(3):
            for name, enemy, play, expected in cases:
                for explicit in (False, True):
                    profile = 'explicit_turn_rules' if explicit else 'implicit_turn_rules'
                    state = ('杀戮尖塔单步决策。玩家有1能量，手中仅有下面选项中的一张牌。'
                             '没有药水、遗物或其他能力。'+enemy)
                    if explicit:
                        state += '通常格挡在下个玩家回合开始时全部清空；不攻击的敌人不会消耗当前格挡。'
                    criteria = {'play': play, 'end': '直接结束玩家回合，让敌人行动。'}
                    order = list(criteria)
                    random.Random(repeat).shuffle(order)
                    criteria = {k: criteria[k] for k in order}
                    started = time.monotonic()
                    row = dict(case=name, profile=profile, repeat=repeat, order=order)
                    try:
                        with TypeSafeClient(api_key=os.environ['TYPESAFE_API_KEY'],
                            base_url='https://api.typesafe.ai', model='jev-latest',
                            retry=RetryPolicy(max_retries=0), timeout=30,
                            transport=recording_transport(args.directory,
                                f'{name}:{profile}:{repeat}', {k:k for k in criteria})) as client:
                            result = client.system_one(state=state, questions={'action': Choice(
                                instructions='选择更有助于生存并赢得战斗的一项；不要假设未列出的效果。',
                                criteria=criteria)})
                        selected = result.answers['action'].choice
                        row.update(status='ok', selected=selected, accepted=selected==expected,
                                   model=result.model)
                    except TypeSafeError as error:
                        row.update(status='provider_error', error_type=type(error).__name__)
                    row['elapsed_ms'] = round((time.monotonic()-started)*1000, 2)
                    out.write(json.dumps(row)+'\n'); out.flush()
                    print(json.dumps(row), flush=True)


if __name__ == '__main__':
    main()
