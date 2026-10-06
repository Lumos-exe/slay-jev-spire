from slay_jev_spire.selectors import strategy_context


def test_attack_damage_and_conditions_are_not_omitted_from_build_summary():
    deck=[{'id':'Pommel Strike','cost':1,'type':'ATTACK','native_values':{'base_damage':9,'magic_number':1}},
          {'id':'Body Slam','cost':1,'type':'ATTACK','native_values':{'base_damage':0}},
          {'id':'Clash','cost':0,'type':'ATTACK','native_values':{'base_damage':14}},
          {'id':'Metallicize','cost':1,'type':'POWER','native_values':{'magic_number':3}}]
    result=strategy_context({'screen_type':'CARD_REWARD','deck':deck},[])
    facts={c['id']:c for c in result['deck']['functions']}
    assert facts['Pommel Strike']['base_damage_per_hit']==9 and facts['Pommel Strike']['draw']==1
    assert facts['Pommel Strike']['cost']==1
    assert 'damage_condition' in facts['Body Slam'] and 'base_damage_per_hit' not in facts['Body Slam']
    assert facts['Clash']['play_condition']
    assert facts['Metallicize']['future_end_turn_block']==3


def test_route_summary_uses_current_node_not_an_unreachable_nearby_elite():
    summary={'current_map_node':{'x':0,'y':1},'map':[
        {'x':0,'y':1,'symbol':'$','children':[{'x':0,'y':2}]},
        {'x':0,'y':2,'symbol':'M','children':[{'x':0,'y':3}]},
        {'x':0,'y':3,'symbol':'E','children':[]},
        {'x':9,'y':2,'symbol':'E','children':[]}]}
    route=strategy_context(summary,[])['route_ahead']
    assert route['nearest_reachable_nodes']=={'M':1,'E':2}
