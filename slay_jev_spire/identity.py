"""Native game identities. A seed describes a game, but cannot identify a run."""
from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class GameIdentity:
    run_id: str
    room_id: str | None
    encounter_id: str | None

    @classmethod
    def from_game(cls, game):
        value = game.get('jev_identity')
        if value is None:
            return None  # Legacy evidence may be read, never matched by seed.
        if not isinstance(value, dict) or value.get('version') != 1:
            raise ValueError('Unsupported native identity contract')
        for field in ('run_id', 'room_id', 'encounter_id'):
            item = value.get(field)
            if (field == 'run_id' or item is not None) and (not isinstance(item, str) or not item):
                raise ValueError('Invalid native identity: ' + field)
        return cls(value['run_id'], value.get('room_id'), value.get('encounter_id'))


def reward_key(game, source):
    identity = GameIdentity.from_game(game)
    if identity and isinstance(source, str) and source:
        return (identity.run_id, source)
    return None


def recovery_path(output_dir, run_id):
    # Native identifiers are data, never path components supplied to the OS.
    return output_dir / 'runs' / sha256(run_id.encode()).hexdigest() / 'recovery.jsonl'
