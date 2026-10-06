"""Continue an already chosen native selection without asking the model again."""
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class SelectionIntent:
    card_uuid: str
    run_id: str | None
    epoch: str | None
    task: tuple
    selected_at_step: int

    @staticmethod
    def task_key(game):
        state=game.get('screen_state',{})
        return tuple(state.get(k) for k in ('for_upgrade','for_purge','for_transform','num_cards','any_number'))

    @classmethod
    def after_choice(cls, action, raw, step):
        game=raw.get('game_state',{});state=game.get('screen_state',{})
        uid=action.get('card_uuid')
        if (action.get('kind')!='screen_grid' or not uid or game.get('screen_type')!='GRID'
            or state.get('confirm_up') is not True or state.get('pending_card_uuid')!=uid):return None
        return cls(uid,game.get('jev_identity',{}).get('run_id'),raw.get('jev_protocol',{}).get('epoch'),cls.task_key(game),step)

    def resolve(self, raw, actions):
        game=raw.get('game_state',{});state=game.get('screen_state',{})
        if (game.get('screen_type')!='GRID' or state.get('confirm_up') is not True
            or state.get('pending_card_uuid')!=self.card_uuid or self.task_key(game)!=self.task
            or game.get('jev_identity',{}).get('run_id')!=self.run_id
            or raw.get('jev_protocol',{}).get('epoch')!=self.epoch):return None
        return next((a for a in actions if a['command']=='CONFIRM'),None)

    def to_record(self):return asdict(self)

    @classmethod
    def from_record(cls, data):
        return cls(**dict(data,task=tuple(data['task']))) if data else None
