"""Observable position features, with a separate contract for future uncertainty.

This is a vector for the ranker, not an uncalibrated weighted value function.
No sampled draw or invented monster move is presented as a future fact.
"""
from collections import Counter
from copy import deepcopy


def pile_profile(cards):
    groups=Counter((c['id'],c.get('upgrades',0),c['cost'],bool(c.get('exhausts')),
                    bool(c.get('ethereal')),bool(c.get('retain') or c.get('self_retain')))
                   for c in cards)
    return [dict(id=k[0],upgrades=k[1],cost_now=k[2],exhausts=k[3],ethereal=k[4],retain=k[5],count=n)
            for k,n in sorted(groups.items())]


def position_context(state, ended, out):
    """Describe candidate-specific future resources, including delayed setup.

    Piles are AFTER CARDS, before unresolved end-turn effects, unless explicitly
    stated otherwise. The enemy forecast covers modeled attacks only. Keeping
    both boundaries explicit prevents a partial outcome becoming a fake s(t+1).
    """
    pp=state['powers']
    unknown=list(state['uncertainties'])
    if state['checkpoint']: unknown.append('observe:'+state['checkpoint'])
    enemies=[]
    for i,enemy in enumerate(state['enemies']):
        if enemy['hp']<=0 and not enemy['half_dead']: continue
        ep=enemy['powers']
        effects=[]
        if ep.get('Ritual'):
            effects.append(dict(trigger='enemy_end_turn',effect='gain_strength',amount=ep['Ritual']))
        if ep.get('Thievery'):
            effects.append(dict(trigger='stealing_attack_even_when_blocked',effect='steal_gold',amount=ep['Thievery'],
                                scope='attack type and escape timing require monster move logic'))
        if ep.get('Anger'):
            effects.append(dict(trigger='player_plays_skill',effect='gain_strength',amount=ep['Anger']))
        if enemy['intent'] in {'BUFF','DEBUFF','STRONG_DEBUFF','DEFEND','DEFEND_BUFF','ATTACK_BUFF','ATTACK_DEBUFF','ATTACK_DEFEND','ESCAPE'}:
            unknown.append(f'enemy_move_effects:{i}:{enemy["intent"]}')
        unknown.append(f'next_enemy_move:{i}')
        enemies.append(dict(index=i,id=enemy['id'],hp_after_cards=enemy['hp'],block_after_cards=enemy['block'],
                            powers_after_cards=deepcopy(ep),intent=enemy['intent'],move_id=enemy.get('move_id'),
                            delayed_effects=effects,half_dead=enemy['half_dead'],gone=enemy['gone']))
    delayed=[]
    for relic in state.get('outside_turn_relics',[]):
        if relic['phase']=='turn_start':
            delayed.append(dict(source=relic['id'],trigger='next_player_start',
                                counter=relic['counter'],description=relic['description']))
            unknown.append('next_start_relic_effect:'+relic['id'])
        elif relic['phase']=='battle_end':
            delayed.append(dict(source=relic['id'],trigger='combat_victory',description=relic['description'],
                condition='Player alive and HP <= half max HP before ordinary onVictory relic callbacks',
                effect='heal',base_amount=12,rule_source='AbstractRoom.endBattle -> MeatOnTheBone.onTrigger'))
            unknown.append('victory_healing_not_in_current_turn_hp:'+relic['id'])
    for power,trigger,effect in [('Demon Form','next_player_start','gain_strength'),
                                ('Berserk','next_player_start','gain_energy'),
                                ('Brutality','next_player_start','draw_and_lose_hp'),
                                ('Metallicize','each_player_end','gain_block'),
                                ('Plated Armor','each_player_end','gain_block'),
                                ('LoseStrength','player_end','lose_strength')]:
        if pp.get(power): delayed.append(dict(source=power,trigger=trigger,effect=effect,amount=pp[power]))
    for power,effect in [('Feel No Pain','block_on_exhaust'),('Dark Embrace','draw_on_exhaust'),
                        ('Corruption','free_skills_that_exhaust'),('Barricade','retain_block'),
                        ('Evolve','draw_on_status'),('Fire Breathing','damage_on_status_or_curse_draw')]:
        if power in pp: delayed.append(dict(source=power,effect=effect,amount=pp[power]))
    if any(pp.get(p) for p in ('Weak','Vulnerable','Frail','IntangiblePlayer','No Draw','Draw Reduction')):
        unknown.append('power_expiration_and_just_applied_timing')
    if state.get('energy_per_turn') is None: unknown.append('base_energy_per_turn')
    if state.get('draw_per_turn') is None: unknown.append('base_draw_per_turn')
    pool=state['hand']+state['draw_pile']+state['discard_pile']
    types=Counter(c['type'] for c in pool)
    return dict(
        horizon='after_cards; modeled_enemy_damage; conditional_next_player_start',
        complete_future_state=not enemies and out['combat_won'] and not unknown,
        player_powers_after_cards=deepcopy(pp),enemies_after_cards=enemies,
        hp_after_modeled_enemy_damage=out['player_hp_after_turn'],
        block_retained_after_modeled_enemy_damage=out['retained_block'],
        piles_after_cards={p:pile_profile(state[p]) for p in ('hand','draw_pile','discard_pile','exhaust_pile')},
        active_cycle=dict(size=len(pool),status_cards=types['STATUS'],curse_cards=types['CURSE'],
                          attacks=types['ATTACK'],skills=types['SKILL'],powers=types['POWER']),
        future_resources=dict(base_energy_per_turn=state.get('energy_per_turn'),
            base_draw_per_turn=state.get('draw_per_turn'),
            retained_energy=state['energy'] if 'Ice Cream' in state['relics'] else 0,
            strength_at_next_start_if_no_other_effects=pp.get('Strength',0)-pp.get('LoseStrength',0)+pp.get('Demon Form',0),
            delayed_effects=delayed),
        uncertainties=sorted(set(unknown)),
        value_scope='Unweighted position facts. Compare next-turn damage, defense and draw quality using deck and enemy context. Unknown next moves and draws are not zero-risk outcomes.')
