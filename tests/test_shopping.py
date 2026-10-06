from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from slay_jev_spire.shopping import generate_shop_plans,bind_shop_queue
from slay_jev_spire.selectors import choose_jev,choose_mock,SelectionError
from slay_jev_spire.session import RunSession


def purchase(ident,price,index=0,kind='screen_shop_card'):
    return dict(id=f'buy_{ident}',kind=kind,command=f'CHOOSE {index}',description=ident,
                item=dict(id=ident,name=ident,uuid=ident,upgrades=0,price=price))


def test_real_shop_regressions_include_complete_affordable_packages():
    cases=json.loads(Path('samples/strategy_shop_cases.json').read_text(encoding='utf-8'))
    for case,wanted,cost in [(cases[0],{'Offering','Inflame','purge'},281),
                             (cases[1],{'Pommel Strike','purge'},120)]:
        actions,stats=generate_shop_plans(case['summary'],case['actions'])
        assert stats['complete_package_enumeration']
        match=next(a for a in actions if a.get('kind')=='shop_plan'
                   and {p['item_id'] for p in a['purchases']}==wanted)
        assert match['cost']==cost
        assert match['steps'][-1]['kind']=='screen_shop_purge'


def test_capacity_price_changers_and_explicit_package_cap():
    a=purchase('A',10,kind='screen_shop_potion');b=purchase('B',10,kind='screen_shop_potion')
    c=purchase('Membership Card',10,kind='screen_shop_relic')
    s=dict(screen_type='SHOP_SCREEN',gold=100,potions=[{'id':'Potion Slot'}])
    choices,stats=generate_shop_plans(s,[a,b,c])
    assert choices==[a,b,c]
    choices,stats=generate_shop_plans(s,[purchase(str(i),1) for i in range(5)],max_packages=2)
    assert stats['packages']==2 and not stats['complete_package_enumeration']
    assert len(choices)==7  # All singles survived.


def test_rebinding_uses_identity_and_rechecks_total_budget():
    old=[purchase('A',40,3),purchase('B',50,4)]
    current=[purchase('B',55,0),purchase('A',40,1)]
    s=dict(screen_type='SHOP_SCREEN',gold=95,potions=[])
    assert bind_shop_queue(old,s,current)['command']=='CHOOSE 1'
    s['gold']=94
    assert bind_shop_queue(old,s,current) is None
    assert bind_shop_queue(old,dict(s,gold=100),current[:1]) is None


def test_jev_separates_best_purchase_from_spend_or_save(monkeypatch):
    monkeypatch.setenv('JEV_COMBAT_PROTOCOL','baseline')
    import typesafe_sdk
    calls=[]
    class Client:
        def __init__(self,**kwargs): pass
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def system_one(self,**kwargs):
            calls.append(kwargs)
            ids=list(kwargs['questions']['action'].criteria)
            picked=ids[0]
            answers={'action':SimpleNamespace(choice=picked,confidence=.8,
                       probabilities={k:1.0 if k==picked else 0.0 for k in ids})}
            if 'decision_basis' in kwargs['questions']:
                answers['decision_basis']=SimpleNamespace(choice='near_term_survival')
            return SimpleNamespace(answers=answers,model='test',usage=None)
    monkeypatch.setenv('TYPESAFE_API_KEY','test-only')
    monkeypatch.setattr(typesafe_sdk,'TypeSafeClient',Client)
    a,b=purchase('A',40),purchase('B',50)
    leave=dict(id='leave',kind='screen_leave',command='LEAVE',description='Leave')
    result=choose_jev(dict(screen_type='SHOP_SCREEN',gold=100),[a,b,leave])
    assert len(calls[0]['questions']['action'].criteria)==2
    assert all('buy' in v for v in calls[0]['questions']['action'].criteria.values())
    assert len(calls[1]['questions']['action'].criteria)==2
    assert list(calls[1]['questions']['action'].criteria.values())[1]=='Leave'
    assert result['shop_review']['chose_purchase']
    assert result['shop_review']['decision_basis']=='near_term_survival'
    assert result['model_requests']==2


def shop_raw():
    cards=[dict(id='Pommel Strike',name='Pommel Strike',uuid='stock_a',type='ATTACK',cost=1,upgrades=0,price=45),
           dict(id='Inflame',name='Inflame',uuid='stock_b',type='POWER',cost=1,upgrades=0,price=68)]
    return dict(in_game=True,ready_for_command=True,available_commands=['choose','leave','state'],
        game_state=dict(seed='shop-fixture',**{'class':'IRONCLAD'},ascension_level=0,
            floor=3,act=1,current_hp=80,max_hp=80,room_phase='COMPLETE',screen_type='SHOP_SCREEN',
            is_screen_up=True,choice_list=['pommel strike','inflame'],gold=134,deck=[],relics=[],potions=[],
            screen_state=dict(cards=cards,relics=[],potions=[],purge_available=False)))


def test_package_executes_only_confirmed_steps_and_survives_restart(tmp_path):
    before=shop_raw()
    before['game_state']['jev_identity'] = dict(version=1, run_id='shop-game', room_id='shop-room', encounter_id=None)
    calls=[]
    def select(summary,actions):
        calls.append(summary)
        plan=next(a for a in actions if a.get('kind')=='shop_plan')
        return choose_mock(summary,[plan])
    session=RunSession(tmp_path,mode='mock',selector=select,catalog={},planning_mode='enumerate')
    assert session.receive(before)==['STATE']
    assert len(session.shop_queue)==2
    assert session.receive(before)==['CHOOSE 0']
    session.command_sent('CHOOSE 0')
    after=deepcopy(before);g=after['game_state']
    bought=g['screen_state']['cards'].pop(0);bought['uuid']='owned_a'
    g['deck'].append(bought);g['gold']=89;g['choice_list']=['inflame']
    assert session.receive(after)==['STATE']
    assert len(session.shop_queue)==1 and len(calls)==1
    assert session.pending[1]['action']['command']=='CHOOSE 0'
    fresh=RunSession(tmp_path,mode='mock',selector=lambda *args:pytest.fail('Should rebind the saved package'),catalog={},planning_mode='enumerate')
    assert fresh.receive(after)==['STATE']
    assert fresh.pending[1]['action']['item']['id']=='Inflame'
    assert fresh.pending[1]['action']['command']=='CHOOSE 0'
