from copy import deepcopy
from slay_jev_spire.session import DecisionMemory


def test_consumed_unknown_potion_keeps_native_description_during_selection():
    potion={'id':'FuturePotion','native_description':'Choose a card; it costs 0 this turn.',
            'unknown_mod_field':{'value':17}}
    before={'game_state':{'screen_type':'NONE','room_phase':'COMBAT',
        'potions':[potion],'combat_state':{'turn':4,'hand':[]}}}
    after={'game_state':{'screen_type':'CARD_REWARD','room_phase':'COMBAT',
        'potions':[{'id':'Potion Slot'}]}}
    decision={'action':{'kind':'potion','command':'POTION USE 0','potion_index':0,'potion_id':'FuturePotion'}}
    memory=DecisionMemory();memory.observe(before,after,decision)
    context=memory.context({'combat_context':{}},[])
    assert context['selection_origin']['potion']==potion
    assert before['game_state']['potions']==[potion]
    # Replaying confirmed observations after a controller restart reconstructs it.
    restored=DecisionMemory();restored.observe(deepcopy(before),deepcopy(after),deepcopy(decision))
    assert restored.context({'combat_context':{}},[])==context
    memory.observe(after,{'game_state':{'screen_type':'NONE','room_phase':'COMBAT'}},
                   {'action':{'kind':'card','command':'CHOOSE 0'}})
    assert memory.selection_origin is None
    assert 'selection_origin' not in memory.context({'combat_context':{}},[])


def test_played_unknown_card_source_is_not_replaced_by_nested_selection():
    card={'id':'UnknownCard','uuid':'source','raw_description':'Select twice.'}
    before={'game_state':{'screen_type':'NONE','room_phase':'COMBAT',
                         'combat_state':{'turn':2,'hand':[card]}}}
    selection={'game_state':{'screen_type':'GRID','room_phase':'COMBAT'}}
    memory=DecisionMemory()
    memory.observe(before,selection,{'action':{'kind':'play','command':'PLAY 1','card_uuid':'source'}})
    memory.observe(selection,selection,{'action':{'kind':'screen_grid','command':'CHOOSE 0'}})
    assert memory.context({'combat_context':{}},[])['selection_origin']['card']==card
    assert 'selection_origin' not in memory.context({'screen_type':'CARD_REWARD'},[])
