from types import SimpleNamespace

import pytest


@pytest.fixture
def actions():
    return [
        {"id": "play_1_0", "command": "PLAY 1 0", "description": "打击目标 0"},
        {"id": "end", "command": "END", "description": "结束回合"},
    ]


def test_exact_choice_maps_to_existing_action(actions):
    from slay_jev_spire.selectors import validate_choice

    assert validate_choice("play_1_0", actions) is actions[0]


@pytest.mark.parametrize("choice", [None, 0, True, {}, [], "PLAY 1 0", "play_9_0", " end"])
def test_invalid_choice_is_rejected(choice, actions):
    from slay_jev_spire.selectors import SelectionError, validate_choice

    with pytest.raises(SelectionError):
        validate_choice(choice, actions)


def test_jev_sdk_request_and_response(monkeypatch, actions):
    import httpx2
    import typesafe_sdk
    from slay_jev_spire.selectors import INSTRUCTIONS, choose_jev

    calls = []
    original_client = typesafe_sdk.TypeSafeClient

    def handle(request):
        import json

        calls.append(json.loads(request.content))
        assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
        return httpx2.Response(200, json={
            "model": "jev-test", "answers": {
                "action": {"type": "choice", "choice": "end", "confidence": 0.75,
                           "probabilities": {"end": 0.75, "play_1_0": 0.25}},
            }, "usage": {"input_tokens": 10, "output_tokens": 2},
        })

    def client(**kwargs):
        assert kwargs["retry"].max_retries == 0
        assert kwargs["timeout"] == 30.0
        return original_client(**kwargs, transport=httpx2.MockTransport(handle))

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only-key")
    monkeypatch.setenv("TYPESAFE_BASE_URL", "https://invalid.example")
    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", client)
    result = choose_jev({"turn": 1}, actions)
    assert len(calls) == 1
    assert calls[0]["state"] == {"turn": 1}
    assert calls[0]["questions"]["action"] == {
        "type": "choice", "instructions": INSTRUCTIONS,
        "criteria": {a["id"]: a["description"] for a in actions},
    }
    assert result["action"] is actions[1]
    assert result["requested_model"] == "jev-latest"
    assert result["returned_model"] == "jev-test"
    assert result["confidence"] == 0.75


def test_missing_answer_is_rejected(monkeypatch, actions):
    import typesafe_sdk
    from slay_jev_spire.selectors import SelectionError, choose_jev

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def system_one(self, **kwargs):
            return SimpleNamespace(answers={}, model="jev-test")

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-only-key")
    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", Client)
    with pytest.raises(SelectionError):
        choose_jev({}, actions)


def test_plan_payload_keeps_decision_facts_without_mutating_full_evidence():
    from copy import deepcopy
    from slay_jev_spire.selectors import plan_criteria
    action={'kind':'turn_plan','sequence':[{'kind':'play','card_id':'Deep Breath','card_uuid':'uid','card_name':'深呼吸','target_index':None}],
        'outcome':{'enemy_hp_by_target':[30],'incoming_hp_loss':None,'player_hp_after_turn':None,
                   'remaining_energy':3,'block':0,'draw_count':2,'forecast_scope':'partial','combat_won':False,
                   'known_hand_continuation':{'sequence':[{'card_id':'Strike_R','target_index':0}],
                       'outcome':{'enemy_hp_by_target':[24],'incoming_hp_loss':8,'player_hp_after_turn':52,'remaining_energy':2,'block':0},
                       'assumption':'Repeated explanation'}},'checkpoint':'draw_cards','uncertainties':[]}
    before=deepcopy(action);wire=plan_criteria(action)
    assert action==before
    assert wire['outcome']['draw_count']==2 and wire['outcome']['incoming_hp_loss'] is None
    assert wire['known_hand_continuation']['enemy_hp_by_target']==[24]
    assert wire['sequence'][0]['card_uuid']=='uid'


def test_card_templates_are_lossless_and_share_identity_with_plans():
    from copy import deepcopy
    from slay_jev_spire.selectors import model_payload
    card={'id':'Strike_R','uuid':'original-uuid','type':'ATTACK','cost':1,'is_playable':True,
          'native_values':{'damage':6,'cost_for_turn':1}}
    state={'hand':[dict(card,hand_index=0)],'deck':[card]}
    original=deepcopy(state)
    action={'id':'plan','kind':'turn_plan','sequence':[{'kind':'play','card_id':'Strike_R','card_uuid':'original-uuid'}],
            'outcome':{'enemy_hp_by_target':[3],'incoming_hp_loss':0,'forecast_scope':'deterministic'}}
    wire,criteria,refs=model_payload(state,[action])
    assert state==original and len(wire['card_templates'])==1
    assert wire['hand'][0]['uuid']==criteria['plan']['sequence'][0]['card_uuid']
    def expand(v):
        if isinstance(v,list):return [expand(x) for x in v]
        if not isinstance(v,dict):return v
        if '$card' in v:v={**wire['card_templates'][v['$card']],**{k:x for k,x in v.items() if k!='$card'}}
        return {k:refs.get(x,x) if k in {'uuid','card_uuid'} and isinstance(x,str) else expand(x) for k,x in v.items()}
    assert expand({k:v for k,v in wire.items() if k!='card_templates'})==original


def test_choice_objective_depends_on_screen_and_temporary_card_origin():
    from slay_jev_spire.selectors import instructions_for,INSTRUCTIONS,model_payload
    combat=instructions_for({'screen_type':'NONE'})
    reward=instructions_for({'screen_type':'CARD_REWARD'})
    temporary=instructions_for({'screen_type':'CARD_REWARD','combat_context':{}})
    assert combat==INSTRUCTIONS
    assert reward!=combat and temporary!=reward
    assert '拿牌不消耗金币或能量' in reward and '临时牌' in temporary
    state,_,_=model_payload({'screen_type':'CARD_REWARD','deck':[{'id':'Strike_R','type':'ATTACK'}]*5+[{'id':'Defend_R','type':'SKILL'}]*4+[{'id':'Bash','type':'ATTACK'}]},[])
    assert state['deck_profile']['size']==10 and state['deck_profile']['starting_cards']==10


def review_card(cid, cost, kind='SKILL', magic=-1, block=-1, upgrades=0, **fields):
    return dict(id=cid,uuid=cid,type=kind,cost=cost,upgrades=upgrades,
                native_values={'magic_number':magic,'base_block':block,'base_damage':-1},**fields)


def test_strategy_distinguishes_exhaust_engine_from_payoff_and_unknown_cards():
    from slay_jev_spire.selectors import model_payload
    deck=[review_card('Dark Embrace',2,'POWER'),review_card('Corruption',3,'POWER'),
          review_card('Offering',0,magic=3,exhausts=True),review_card('Pommel Strike',1,'ATTACK',magic=2,upgrades=1),
          review_card('Whirlwind',-1,'ATTACK'),review_card('ForeignCard',1)]
    wire,_,_=model_payload({'screen_type':'CARD_REWARD','deck':deck},[])
    strategy=wire['strategy_context']['deck']; roles={c['id']:c for c in strategy['functions']}
    assert 'exhaust_enabler' not in roles['Dark Embrace']
    assert roles['Corruption']['exhaust_enabler'] and roles['Offering']['self_exhaust']
    assert roles['Offering']['draw']==3 and roles['Offering']['energy']==2 and roles['Offering']['hp_cost']==6
    assert roles['Pommel Strike']['draw']==2
    assert strategy['cost_counts']=={'2':1,'3':1,'0':1,'1':2,'-1':1}
    assert strategy['unclassified_effects']=={'ForeignCard':1}


def test_upgrade_deltas_use_native_preview_and_do_not_leak_into_purge():
    from slay_jev_spire.selectors import strategy_context
    from copy import deepcopy
    cards=[review_card('Body Slam',1,'ATTACK',upgrade_preview={'cost':0,'upgrades':1}),
           review_card('Pommel Strike',1,'ATTACK',magic=1,upgrade_preview={'cost':1,'magic_number':2,'upgrades':1}),
           review_card('Perfected Strike',2,'ATTACK',magic=2,upgrade_preview={'cost':2,'magic_number':3,'upgrades':1})]
    deck=cards+[review_card('Strike_R',1,'ATTACK') for _ in range(5)]
    actions=[{'id':f'grid_{i}','card':c} for i,c in enumerate(cards)]
    summary={'screen_type':'GRID','deck':deck,'screen_state':{'for_upgrade':True}}
    before=deepcopy(summary); result=strategy_context(summary,actions)
    assert summary==before
    assert result['upgrade_deltas']['grid_0']['cost']['delta']==-1
    assert result['upgrade_deltas']['grid_1']['draw']=={'before':1,'after':2}
    assert result['upgrade_deltas']['grid_2']['damage_gain_from_strike_count']==7
    summary['screen_state']={'for_purge':True}
    assert 'upgrade_deltas' not in strategy_context(summary,actions)


def test_identical_chest_choices_expose_different_visible_campfire_routes():
    from slay_jev_spire.selectors import strategy_context
    # Round 11 step 106 topology: both choices look like T in the native action.
    nodes=[{'symbol':'T','x':0,'y':8,'children':[{'x':0,'y':9}]},
           {'symbol':'T','x':1,'y':8,'children':[{'x':1,'y':9}]},
           {'symbol':'M','x':0,'y':9,'children':[{'x':1,'y':10}]},
           {'symbol':'R','x':1,'y':9,'children':[{'x':2,'y':10}]},
           {'symbol':'?','x':1,'y':10,'children':[]},
           {'symbol':'M','x':2,'y':10,'children':[]}]
    actions=[{'id':'left','node':nodes[0]},{'id':'right','node':nodes[1]}]
    result=strategy_context({'screen_type':'MAP','map':nodes},actions)['routes']
    assert result['left']['visible_paths']==[['T','M','?']]
    assert result['right']['visible_paths']==[['T','R','M']]
    assert result['left']['resource_ranges']['R']==[0,0]
    assert result['right']['resource_ranges']['R']==[1,1]


def test_budget_context_keeps_offering_inflame_and_purge_package_executable():
    from slay_jev_spire.selectors import strategy_context
    deck=[review_card('Dark Embrace',2,'POWER')]
    summary={'screen_type':'SHOP_SCREEN','gold':296,'deck':deck,'relics':[{'id':'Bird Faced Urn'}]}
    actions=[{'id':'offering','kind':'screen_shop_card','item':review_card('Offering',0,magic=3,exhausts=True,price=138)},
             {'id':'inflame','kind':'screen_shop_card','item':review_card('Inflame',1,'POWER',magic=2,price=68)},
             {'id':'purge','kind':'screen_shop_purge','item':{'price':75}}]
    bundle=strategy_context(summary,actions)['shop_bundles'][0]
    assert set(bundle['actions'])=={'offering','inflame'} and bundle['cost']==206
    assert bundle['also_affords_purge']=={'action':'purge','total_cost':281}
    assert bundle['gold_left']==90 and len(bundle['synergies'])==2
    summary['gold']=200
    assert 'shop_bundles' not in strategy_context(summary,actions)


def test_plan_payload_preserves_pollution_block_retention_and_potion_facts():
    from slay_jev_spire.selectors import plan_criteria
    out={'generated_card_counts':{'Wound':2},'generated_card_types':{'STATUS':2},
         'new_status_cards':2,'new_curse_cards':0,'unexhausted_status_cards':0,'unexhausted_curse_cards':0,
         'exhausted_card_counts':{'Wound':2},'effective_block':11,'wasted_block':4,
         'remaining_block_after_turn':4,'retained_block':0,
         'potions_used':[{'potion_index':1,'potion_id':'Weak Potion','target_index':0,'potency':3}]}
    sequence=[{'kind':'potion',**out['potions_used'][0],'subaction':'use'}]
    wire=plan_criteria({'kind':'turn_plan','sequence':sequence,'outcome':out})
    assert wire['outcome']==out and wire['sequence']==sequence


def test_standalone_generated_potion_keeps_native_effect_and_observation_boundary():
    from copy import deepcopy
    from slay_jev_spire.selectors import plan_criteria
    potion={'id':'PowerPotion','name':'能力药水','potency':1,'can_use':True,
            'native_description':'Choose one of 3 random Power cards. It costs 0 this turn.'}
    action={'kind':'potion','id':'potion_use_0','potion_index':0,'subaction':'use',
            'potion_id':'PowerPotion','potion':potion,'description':'Use 能力药水'}
    original=deepcopy(action); wire=plan_criteria(action)
    assert action==original and wire['potion']==potion
    assert wire['subaction']=='use' and 'does not end the turn' in wire['followup']
    wire['potion']['potency']=9
    assert potion['potency']==1
