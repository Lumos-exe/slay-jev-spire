from copy import deepcopy
from slay_jev_spire.selection_intent import SelectionIntent


def test_selection_commit_requires_exact_card_task_and_native_epoch():
    raw={'jev_protocol':{'epoch':'one'},'game_state':{'jev_identity':{'run_id':'run'},'screen_type':'GRID',
        'screen_state':{'confirm_up':True,'pending_card_uuid':'new-card-uuid','for_upgrade':True,'num_cards':1}}}
    action={'kind':'screen_grid','card_uuid':'new-card-uuid'}
    intent=SelectionIntent.after_choice(action,raw,4)
    commands=[{'command':'CONFIRM'},{'command':'CANCEL'}]
    assert intent.resolve(raw,commands)==commands[0]
    assert SelectionIntent.from_record(intent.to_record())==intent
    for target,value in [('pending_card_uuid','different'),('for_upgrade',False)]:
        changed=deepcopy(raw);changed['game_state']['screen_state'][target]=value
        assert intent.resolve(changed,commands) is None
    changed=deepcopy(raw);changed['jev_protocol']['epoch']='two'
    assert intent.resolve(changed,commands) is None
