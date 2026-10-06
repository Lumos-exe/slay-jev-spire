"""Visibility-safe native event observations, including a bounded hot-recovery adapter."""
from copy import deepcopy
import json
from pathlib import Path


def augment_event(raw, output_dir):
    game=raw.get('game_state',{});state=game.get('screen_state',{})
    if game.get('screen_type')!='EVENT':return raw
    if state.get('native_event_error'):raise ValueError('Native event observation unavailable')
    view=state.get('native_event');waiting=False
    if view is None:
        path=Path(output_dir)/'native-event-observation.json'
        try:data=json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):data={}
        identity=game.get('jev_identity',{});p=raw.get('jev_protocol',{})
        matches=(data.get('version')==1 and data.get('active') is True
            and data.get('epoch')==p.get('epoch') and data.get('run_id')==identity.get('run_id')
            and data.get('room_id')==identity.get('room_id') and data.get('event_id')==state.get('event_id'))
        if matches:
            labels=[str(x).lower() for x in game.get('choice_list',[])]
            waiting=data.get('revision')!=p.get('revision') or data.get('choice_labels')!=labels
            if not waiting:view=data.get('view')
        elif state.get('event_id')=='Match and Keep!':
            # This distinct native UI needs progress and visibility metadata;
            # treating it as ordinary dialogue loses attempts and card faces.
            waiting=True
    if view is None and not waiting:return raw
    if view is not None and not isinstance(view,dict):raise ValueError('Invalid native event view')
    result=deepcopy(raw)
    if view is not None:
        view=deepcopy(view)
        selected=next((slot for slot in view.get('board',[]) if slot.get('slot')==view.get('selected_slot')
                       and slot.get('known') is True),None)
        if selected and isinstance(selected.get('card',{}).get('id'),str):
            view['selected_card_id']=selected['card']['id']
        result['game_state']['screen_state']['native_event']=view
        waiting=view.get('ready_for_choice') is not True
    if waiting:
        result['_native_transport_ready']=raw.get('ready_for_command')
        result['ready_for_command']=False
        result['_native_event_waiting']=True
    return result
