"""Complete a model-chosen room exit through its remaining native UI step."""
from dataclasses import dataclass, asdict
from hashlib import sha256
import json


def resource_key(game):
    fields=('seed','class','act','floor','current_hp','max_hp','gold','deck','relics','potions','current_map_node')
    return sha256(json.dumps({k:game.get(k) for k in fields},sort_keys=True,
                             ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


@dataclass(frozen=True)
class NavigationIntent:
    run_id: str
    room_id: str
    epoch: str
    revision: int
    resources: str
    chosen_at_step: int

    @classmethod
    def after_action(cls,action,before,after,step):
        old=before.get('game_state',{});game=after.get('game_state',{})
        p=after.get('jev_protocol',{});identity=game.get('jev_identity',{})
        if (action.get('command')!='LEAVE' or old.get('screen_type')!='SHOP_SCREEN'
            or game.get('screen_type')!='SHOP_ROOM' or after.get('ready_for_command') is not True
            or not all(isinstance(identity.get(k),str) and identity[k] for k in ('run_id','room_id'))
            or p.get('version')!=1 or not isinstance(p.get('epoch'),str) or type(p.get('revision')) is not int
            or before.get('jev_protocol',{}).get('epoch')!=p['epoch']
            or old.get('jev_identity',{}).get('run_id')!=identity['run_id']
            or old.get('jev_identity',{}).get('room_id')!=identity['room_id']):return None
        return cls(identity['run_id'],identity['room_id'],p['epoch'],p['revision'],resource_key(game),step)

    def resolve(self,raw,actions):
        game=raw.get('game_state',{});p=raw.get('jev_protocol',{});identity=game.get('jev_identity',{})
        if (game.get('screen_type')!='SHOP_ROOM' or raw.get('ready_for_command') is not True
            or identity.get('run_id')!=self.run_id or identity.get('room_id')!=self.room_id
            or p.get('epoch')!=self.epoch or p.get('revision')!=self.revision
            or resource_key(game)!=self.resources):return None
        return next((a for a in actions if a['command']=='PROCEED'),None)

    def to_record(self):return asdict(self)

    @classmethod
    def from_record(cls,value):return cls(**value) if value else None
