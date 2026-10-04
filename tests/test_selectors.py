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
