"""Explicit encounter mechanics verified against the installed vanilla bytecode.

Sources: SlimeBoss/large slime damage(), TheGuardian.damage/changeState(),
Looter/Mugger.takeTurn/die(). Unknown or modded monsters retain unknown timing.
"""
from copy import deepcopy
from .native_context import observed_fields

SLIMES={'SlimeBoss','AcidSlime_L','SpikeSlime_L'}
THIEVES={'Looter','Mugger'}


def encounter_context(enemies):
    result=[]
    for index,e in enumerate(enemies):
        ident=e.get('id');p={p['id']:p['amount'] for p in e.get('powers',[])}
        entry=dict(index=index,id=ident)
        if ident in SLIMES:
            hp=e['current_hp'];threshold=e['max_hp']//2
            entry.update(interrupt=dict(trigger='HP at or below half, while alive',
                hp_loss_needed=max(0,hp-threshold),current_block=e['block'],
                replaces_current_attack=True,split_move_id=3),
                consequence='Two children inherit HP at the moment of splitting. After switching intent, use remaining damage when worthwhile to reduce both children; do not end automatically at half HP.')
        elif ident=='TheGuardian':
            entry.update(interrupt=dict(trigger='actual HP loss exhausts remaining Mode Shift',
                hp_loss_needed=p.get('Mode Shift'),current_block=e['block'],replaces_current_attack='Mode Shift' in p),
                consequence='Threshold changes intent to Defensive Mode (BUFF), cancels current attack and queues 20 block. Observe before continuing; defensive Sharp Hide punishes attack cards.')
        elif ident in THIEVES:
            move=e.get('move_id');native=observed_fields(e)
            entry.update(steals_per_attack=native.get('goldAmt',p.get('Thievery')),
                stolen_gold=native.get('stolenGold'),
                player_turns_left_to_prevent_escape=1 if move==3 or e['intent']=='ESCAPE' else 2 if move==2 else None,
                consequence='Block does not prevent stealing. Kill before escape to recover stolen gold as a reward; partial damage alone does not stop escape. DEFEND/smoke is followed by ESCAPE, not another ordinary attack.')
        elif ident=='Hexaghost':
            entry.update(interrupt=None,
                consequence='No HP threshold cancels attacks. Divider and Inferno are multi-hit attacks; Strength reduction applies per hit. Burns and Inflame make a prolonged defense-only race worse. Evaluate burst, scaling and potions against the clock, not a fictional stagger.')
        elif ident=='GremlinNob':
            entry.update(permanent_strength_per_skill=p.get('Anger',0),
                consequence='While Anger is active, every Skill permanently increases enemy Strength before its effect. A small block gain this turn can increase damage on every later attack. Compare an attack/potion kill race against repeated defense; do not forbid Skills that secure a kill, draw into a rescue, or prevent immediate death. Before Anger is applied, this penalty is absent.')
        else: continue
        result.append(entry)
    return result


def cancel_attack(state,index,reason,new_intent,new_move,**details):
    enemy=state['enemies'][index]
    if any(x['target_index']==index for x in state['interruptions']): return
    damage=enemy['damage'];hits=enemy['hits']
    cancelled=damage*hits if enemy['intent'].startswith('ATTACK') and type(damage) is int and type(hits) is int else 0
    state['interruptions'].append(dict(target_index=index,enemy_id=enemy['id'],reason=reason,
        previous_intent=enemy['intent'],cancelled_attack_damage=cancelled,new_intent=new_intent,
        new_move_id=new_move,**details))
    enemy.update(intent=new_intent,move_id=new_move,damage=0,hits=0,base_damage=0)


def economy_forecast(state,enemy_start=None,enemy_end=None):
    gold=state.get('gold');targets=[]
    for index,e in enumerate(state['enemies']):
        if e['id'] not in THIEVES: continue
        start=enemy_start[index] if enemy_start is not None else e
        end=enemy_end[index] if enemy_end is not None else e
        native=e.get('monster_state',{})
        stolen=native.get('stolenGold')
        rate=native.get('goldAmt',e['powers'].get('Thievery'))
        alive=start['hp']>0 and not start['gone']
        attack=alive and start['move_id'] in (1,4) and start['intent'].startswith('ATTACK')
        loss=min(gold,rate) if attack and type(gold) is int and type(rate) is int else None if attack else 0
        if loss is not None and gold is not None: gold-=loss
        escape=alive and (start['move_id']==3 or start['intent']=='ESCAPE')
        killed=end['hp']<=0 and not end['gone']
        refund=(stolen+loss if type(stolen) is int and type(loss) is int else None) if killed else 0
        targets.append(dict(target_index=index,hp_after_cards=e['hp'],
            stolen_gold=stolen,steals_this_enemy_turn=loss,
            escapes_this_enemy_turn=escape,
            recovered_as_reward=refund,
            permanently_lost_on_escape=stolen if escape else 0,
            escape_opportunities=1 if escape else 2 if e['move_id']==2 else None))
    return dict(targets=targets,gold_after_known_steals=gold,
                scope='Conditional on surviving thieves executing their current move. Killing refunds stolen gold via reward, not immediate spendable gold. Block does not stop theft.')
