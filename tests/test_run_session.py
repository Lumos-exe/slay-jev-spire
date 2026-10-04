from pathlib import Path
import copy
import json
from tests.test_journey import reward
from slay_jev_spire.selectors import choose_mock


def test_main_menu_waits_without_budget_or_timeout_then_accepts_run(tmp_path):
    s = session(tmp_path)
    menu = {'in_game': False, 'ready_for_command': True,
            'available_commands': ['start', 'key', 'click', 'state']}
    assert s.receive(menu) == []
    assert not s.stopped and s.calls == 0 and s.deadline is None
    assert s.receive(menu) == []
    assert not s.stopped and s.calls == 0
    assert s.receive(reward()) == ['STATE']
    assert s.calls == 0  # Guaranteed gold pickup does not call the model.


def test_main_menu_wait_still_honors_pause(tmp_path):
    s = session(tmp_path)
    (tmp_path / 'pause.flag').write_text('pause')
    assert s.receive({'in_game': False, 'ready_for_command': True}) == []
    assert s.stopped and s.reason == 'paused'


def session(path,**kw):
    from slay_jev_spire.session import RunSession
    return RunSession(path,mode='mock',**kw)


def send(s,r):
    assert s.receive(r)==['STATE']
    command=s.receive(r)[0]; s.command_sent(command); return command


def test_reward_confirmation_ignores_unrelated_change_and_correlates(tmp_path):
    s=session(tmp_path,max_decisions=1); r=reward()
    assert send(s,r)=='CHOOSE 0'
    other=copy.deepcopy(r); other['game_state']['map']=[]
    assert s.receive(other)==['STATE'] and not s.stopped
    after=copy.deepcopy(r); g=after['game_state']; g['gold']+=13
    g['screen_state']['rewards'].pop(0); g['choice_list'].pop(0)
    assert s.receive(after)==['STATE'] and not s.stopped and s.calls == 0
    records=[json.loads(x) for x in (tmp_path/'runs.jsonl').read_text(encoding='utf-8').splitlines()]
    confirmed=next(x for x in records if x['status']=='action_confirmed')
    assert confirmed['before']==r and confirmed['after']==after and confirmed['step_id']==1
    assert confirmed['run_id']==s.id


def test_changed_before_send_pause_and_identity(tmp_path):
    s=session(tmp_path); r=reward(); s.receive(r)
    changed=copy.deepcopy(r); changed['game_state']['gold']+=1
    assert s.receive(changed)==[] and s.reason=='state_changed'
    s=session(tmp_path/'pause'); s.receive(r)
    (s.output_dir/'pause.flag').write_text('pause')
    assert s.receive(r)==[] and s.reason=='paused'
    s=session(tmp_path/'identity'); send(s,r)
    changed['game_state']['seed']=42
    assert s.receive(changed)==[] and s.reason=='run_changed'


def test_complete_native_game_over_and_unsupported_after_map(tmp_path):
    s=session(tmp_path); r=reward(); g=r['game_state']; g['screen_type']='MAP'
    g['choice_list']=['x=2']; g['screen_state']={'next_nodes':[{'x':2,'y':1,'symbol':'?'}]}
    assert send(s,r)=='CHOOSE 0'
    after=copy.deepcopy(r); g=after['game_state']; g['floor']=2; g['screen_type']='EVENT'
    g['screen_state']={'current_node':{'x':2,'y':1}}
    assert s.receive(after)==[] and s.reason=='unsupported_state'
    rows=[json.loads(x) for x in (tmp_path/'runs.jsonl').read_text(encoding='utf-8').splitlines()]
    assert any(x['status']=='action_confirmed' for x in rows)
    s=session(tmp_path/'end'); end=reward(); end['game_state']['screen_type']='GAME_OVER'
    end['game_state']['screen_state']={'victory':False,'score':123}
    assert s.receive(end)==[] and s.reason=='game_over' and s.result=={'victory':False,'score':123}


def test_transition_timeout_and_pause_inside_selector(tmp_path):
    s=session(tmp_path); r=reward(); r['ready_for_command']=False
    assert s.receive(r)==[] and s.deadline is not None
    s.deadline=0; s.tick(); assert s.reason=='state_timeout'
    def pause(summary,actions):
        (tmp_path/'model'/'pause.flag').write_text('pause'); return choose_mock(summary,actions)
    s=session(tmp_path/'model',selector=pause)
    choice = reward()
    choice['game_state']['screen_state']['rewards'] = [{'reward_type': 'CARD'}]
    choice['game_state']['choice_list'] = ['card']
    assert s.receive(choice)==[] and s.reason=='paused' and s.actions==0

def test_missing_combat_hand_does_not_confirm_and_game_over_preserved(tmp_path):
    from slay_jev_spire.session import confirmation
    r=json.loads(Path('samples/communication_mod_combat.json').read_text(encoding='utf-8'))
    after=copy.deepcopy(r); del after['game_state']['combat_state']['hand']
    action={'command':'PLAY 1 0','card_uuid':r['game_state']['combat_state']['hand'][0]['uuid']}
    assert confirmation(r,after,action) is None
    s=session(tmp_path); before=reward(); send(s,before)
    end=copy.deepcopy(before); end['game_state']['screen_type']='GAME_OVER'
    end['game_state']['screen_state']={'score':1,'victory':False}
    assert s.receive(end)==[] and s.reason=='game_over'
    rows=[json.loads(x) for x in (tmp_path/'runs.jsonl').read_text(encoding='utf-8').splitlines()]
    assert any(x['status']=='action_unconfirmed' for x in rows)


def test_rewards_to_cards_to_map_to_supported_combat(tmp_path):
    r=reward(); g=r['game_state']; g['screen_state']['rewards']=[{'reward_type':'CARD'}]; g['choice_list']=['card']
    def select(summary,actions):
        return choose_mock(summary, sorted(actions,key=lambda a:a['command']!='SKIP'))
    s=session(tmp_path,selector=select)
    assert send(s,r)=='CHOOSE 0'
    cards=copy.deepcopy(r); g=cards['game_state']; g['screen_type']='CARD_REWARD'; g['choice_list']=['unknown']
    g['screen_state']={'cards':[{'name':'unknown','id':'Unknown'}],'skip_available':True,'bowl_available':False}
    cards['available_commands']=['choose','skip','state']
    assert s.receive(cards)==['STATE']; command=s.receive(cards)[0]; assert command=='SKIP'; s.command_sent(command)
    rewards=copy.deepcopy(r); rewards['game_state']['screen_state']['rewards']=[]; rewards['game_state']['choice_list']=[]
    assert s.receive(rewards)==['STATE']; command=s.receive(rewards)[0]; assert command=='PROCEED'; s.command_sent(command)
    route=copy.deepcopy(rewards); route['game_state']['screen_type']='MAP'; route['game_state']['choice_list']=['x=0']
    route['game_state']['screen_state']={'next_nodes':[{'x':0,'y':1,'symbol':'M'}]}
    assert s.receive(route)==['STATE']; command=s.receive(route)[0]; assert command=='CHOOSE 0'; s.command_sent(command)
    combat=json.loads(Path('samples/communication_mod_combat.json').read_text(encoding='utf-8'))
    for k in ('seed','class','ascension_level'): combat['game_state'][k]=r['game_state'][k]
    combat['game_state']['floor']=2
    combat['game_state']['combat_state']['monsters'][0]['intent']='ATTACK'
    assert s.receive(combat)==['STATE']; command=s.receive(combat)[0]; assert command.startswith('PLAY'); s.command_sent(command)
    bad=copy.deepcopy(combat); bad['game_state']['combat_state']['hand'].pop(0)
    bad['game_state']['combat_state']['hand'][0]['id']=None  # 新规则接受陌生牌；错误字段仍要停止。
    assert s.receive(bad)==[] and s.reason=='unsupported_state'


def test_card_gain_bowl_end_and_potion_evidence():
    from slay_jev_spire.session import confirmation
    r=reward(); after=copy.deepcopy(r); g=after['game_state']
    action={'command':'CHOOSE 1','kind':'reward','choice_index':1,'reward':r['game_state']['screen_state']['rewards'][1]}
    g['screen_state']['rewards'].pop(1); g['potions'][0]=action['reward']['potion']
    assert confirmation(r,after,action)=='potion_reward_collected'
    r['game_state']['screen_type']='CARD_REWARD'; after=copy.deepcopy(r); after['game_state']['screen_type']='COMBAT_REWARD'
    after['game_state']['deck'].append({'id':'Unknown'})
    assert confirmation(r,after,{'command':'CHOOSE 0','kind':'card','card':{'id':'Unknown'}})=='card_added_to_deck'
    after['game_state']['max_hp']+=2
    assert confirmation(r,after,{'command':'CHOOSE 1','kind':'bowl'})=='bowl_hp_increased'
    combat=json.loads(Path('samples/communication_mod_combat.json').read_text(encoding='utf-8'))
    after=copy.deepcopy(combat); after['game_state']['combat_state']['turn']+=1
    assert confirmation(combat,after,{'command':'END'})=='turn_advanced'
