from copy import deepcopy
import pytest
from slay_jev_spire.screens import prepare_screen, confirm_screen
from slay_jev_spire.state import UnsupportedState


def raw(screen, choices, state, commands=('choose',), **game):
    return {'available_commands':list(commands),'game_state':{'screen_type':screen,'choice_list':choices,'screen_state':state,**game}}


def card(name='Strike', uuid='a', **extra):
    return {'name':name,'uuid':uuid,'upgrades':0,**extra}


def test_event_disabled_duplicate_labels_use_explicit_indices():
    r=raw('EVENT',['same','same'],{'options':[{'label':'No','disabled':True},{'label':'Same','text':'first','disabled':False,'choice_index':0},{'label':'Same','text':'second','disabled':False,'choice_index':1}]})
    assert [a['command'] for a in prepare_screen(r)] == ['CHOOSE 0','CHOOSE 1']
    assert prepare_screen(r)[1]['description']=='second'
    r['game_state']['screen_state']['options'][2]['choice_index']=0
    with pytest.raises(UnsupportedState): prepare_screen(r)


def test_shop_native_affordable_order_and_full_potions():
    r=raw('SHOP_SCREEN',['purge','strike','relic','potion'],{'purge_available':True,'purge_cost':75,'cards':[card(price=30.5),card('Expensive','b',price=200)],'relics':[{'name':'Relic','id':'r','price':50}],'potions':[{'name':'Potion','id':'p','price':20}]},('choose','leave'),gold=100,potions=[{'id':'Full'}])
    assert [a['command'] for a in prepare_screen(r)]==['CHOOSE 0','CHOOSE 1','CHOOSE 2','LEAVE']
    r['game_state']['potions']=[{'id':'Potion Slot'}]
    assert prepare_screen(r)[3]['command']=='CHOOSE 3'


def test_grid_selected_not_renumbered_and_confirm_only():
    a,b=card(),card('Defend','b')
    r=raw('GRID',['strike','defend'],{'cards':[a,b],'selected_cards':[a],'num_cards':2,'for_upgrade':True})
    assert [x['command'] for x in prepare_screen(r)]==['CHOOSE 1']
    r['game_state']['screen_state']['confirm_up']=True
    r['game_state']['choice_list']=[]
    r['available_commands']=['confirm','cancel']
    assert [x['command'] for x in prepare_screen(r)]==['CONFIRM','CANCEL']


def test_grid_immediate_upgrade_or_purge_has_uuid_evidence():
    c=card()
    before=raw('GRID',['strike'],{'cards':[c],'selected_cards':[],'num_cards':1,'for_upgrade':True},deck=[c])
    action=prepare_screen(before)[0]
    after=raw('REST',[],{},deck=[card(upgrades=1)])
    assert confirm_screen(before,after,action)
    after['game_state']['deck']=[c]
    assert confirm_screen(before,after,action) is None
    before['game_state']['screen_state']={'cards':[c],'selected_cards':[],'num_cards':1,'for_purge':True}
    action=prepare_screen(before)[0]
    after['game_state']['deck']=[]
    assert confirm_screen(before,after,action)


def test_hand_selection_and_confirm_require_specific_card_evidence():
    c=card()
    before=raw('HAND_SELECT',['strike'],{'hand':[c],'selected':[],'max_cards':1})
    action=prepare_screen(before)[0]
    after=deepcopy(before)
    after['game_state']['gold']=123
    assert confirm_screen(before,after,action) is None
    after['game_state']['screen_state'].update(hand=[],selected=[c])
    after['game_state']['choice_list']=[]
    after['available_commands']=['confirm']
    assert confirm_screen(before,after,action)
    confirm=prepare_screen(after)[0]
    done=raw('NONE',[],{},combat_state={'hand':[],'exhaust_pile':[c]})
    assert confirm_screen(after,done,confirm)
    done['game_state']['combat_state']['exhaust_pile']=[]
    assert confirm_screen(after,done,confirm) is None


@pytest.mark.parametrize('screen,label,state',[('CHEST','open',{'chest_open':False}),('SHOP_ROOM','shop',{}),('REST','smith',{'rest_options':['smith']}),('BOSS_REWARD','relic',{'relics':[{'name':'Relic','id':'r'}]})])
def test_other_screens_only_native_buttons(screen,label,state):
    r=raw(screen,[label],state)
    assert len(prepare_screen(r))==1
    assert all(a['kind'].startswith('screen_') for a in prepare_screen(r))
    r['available_commands']=[]
    assert prepare_screen(r)==[]


def test_event_confirmation_ignores_unrelated_metadata():
    before=raw('EVENT',['leave'],{'event_id':'x','body_text':'body','options':[{'label':'Leave','disabled':False,'choice_index':0}]})
    action=prepare_screen(before)[0]
    after=deepcopy(before); after['game_state']['map']=[123]
    assert confirm_screen(before,after,action) is None
    after['game_state']['screen_state']['body_text']='next'
    assert confirm_screen(before,after,action)


def test_shop_purchase_copy_uuid_requires_stock_and_cost_evidence():
    stock=card(price=50,id='Strike_R')
    before=raw('SHOP_SCREEN',['strike'],{'cards':[stock]},gold=100,deck=[])
    action=prepare_screen(before)[0]
    after=raw('SHOP_SCREEN',[],{'cards':[]},gold=50,deck=[card(uuid='copy',id='Strike_R')])
    assert confirm_screen(before,after,action)
    after['game_state']['gold']=100
    assert confirm_screen(before,after,action) is None


def test_grid_confirm_upgrade_and_transform_target_evidence():
    c=card()
    before=raw('GRID',[],{'cards':[c],'selected_cards':[c],'num_cards':1,'confirm_up':True,'for_upgrade':True},('confirm',),deck=[c])
    action=prepare_screen(before)[0]
    after=raw('REST',[],{},deck=[card(upgrades=1)])
    assert confirm_screen(before,after,action)
    before['game_state']['screen_state']['for_upgrade']=False
    before['game_state']['screen_state']['for_transform']=True
    action=prepare_screen(before)[0]
    after['game_state']['deck']=[]
    assert confirm_screen(before,after,action) is None
    after['game_state']['deck']=[card('Bash','new')]
    assert confirm_screen(before,after,action)


def test_hand_confirm_observes_combat_only_upgrade_without_master_deck_change():
    selected=card()
    before=raw('HAND_SELECT',[],{'hand':[],'selected':[selected],'max_cards':1},('confirm',),deck=[selected],combat_state={'hand':[selected]})
    action=prepare_screen(before)[0]
    after=raw('NONE',[],{},deck=[selected],combat_state={'hand':[card(upgrades=1)]})
    assert confirm_screen(before,after,action)
    after['game_state']['combat_state']['hand']=[selected]
    after['game_state']['gold']=123
    assert confirm_screen(before,after,action) is None


def test_hand_confirm_observes_returned_selection_uuid_only_after_close():
    selected=card()
    before=raw('HAND_SELECT',[],{'hand':[],'selected':[selected],'max_cards':1},('confirm',),combat_state={'hand':[]})
    action=prepare_screen(before)[0]
    after=raw('NONE',[],{},combat_state={'hand':[selected]})
    assert confirm_screen(before,after,action)
    after['game_state']['screen_type']='HAND_SELECT'
    after['game_state']['screen_state']=deepcopy(before['game_state']['screen_state'])
    after['game_state']['screen_state']['unrelated']=123
    assert confirm_screen(before,after,action) is None


def test_hand_confirm_requires_every_selected_uuid_destination():
    first,second=card(),card('Defend','b')
    before=raw('HAND_SELECT',[],{'hand':[],'selected':[first,second],'max_cards':2},('confirm',),combat_state={'draw_pile':[],'hand':[]})
    action=prepare_screen(before)[0]
    after=raw('NONE',[],{},combat_state={'draw_pile':[first]})
    assert confirm_screen(before,after,action) is None
    after['game_state']['combat_state']['draw_pile']=[first,second]
    assert confirm_screen(before,after,action)
    before['game_state']['combat_state']['draw_pile']=[first,second]
    assert confirm_screen(before,after,action) is None


def test_grid_target_uuid_can_move_immediately_to_draw_pile():
    chosen,other=card(),card('Defend','b')
    before=raw('GRID',['strike','defend'],{'cards':[chosen,other],'selected_cards':[],'num_cards':1},combat_state={'discard_pile':[chosen,other],'draw_pile':[]})
    action=prepare_screen(before)[0]
    after=raw('NONE',[],{},combat_state={'discard_pile':[other],'draw_pile':[chosen]})
    assert confirm_screen(before,after,action)
    after['game_state']['combat_state']['draw_pile']=[other]
    assert confirm_screen(before,after,action) is None
