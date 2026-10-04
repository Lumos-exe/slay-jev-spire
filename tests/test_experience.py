from copy import deepcopy
from tests.test_turn_batches import battle
from slay_jev_spire.journey import prepare_journey


def mistaken_end():
    raw = battle()
    raw['game_state']['combat_state']['monsters'][0]['current_hp'] = 7
    after = deepcopy(raw); after['game_state']['current_hp'] -= 10
    return [{'run_id': 'old', 'step_id': 1, 'status': 'decision', 'mode': 'jev', 'before': raw,
             'decision': {'action': {'command': 'END', 'kind': 'end'}}},
            {'run_id': 'old', 'step_id': 1, 'status': 'action_confirmed', 'before': raw, 'after': after,
             'decision': {'action': {'command': 'END', 'kind': 'end'}}}]


def test_verified_error_is_persisted_deduplicated_and_retrieved_next_run(tmp_path):
    from slay_jev_spire.experience import review_and_store, applicable_experiences
    path = tmp_path / 'experience.json'
    findings = review_and_store(mistaken_end(), path)
    assert findings[0]['code'] == 'missed_verified_lethal'
    review_and_store(mistaken_end(), path)
    summary, actions = prepare_journey(battle())
    lessons = applicable_experiences(summary, path)
    assert lessons[0]['occurrences'] == 1
    assert lessons[0]['evidence'][0]['hp_loss'] == 10
    assert applicable_experiences({'screen_type': 'MAP'}, path) == []


def test_sleeping_enemy_or_nonlethal_end_is_not_invented_error(tmp_path):
    from slay_jev_spire.experience import review_and_store
    rows = mistaken_end()
    rows[0]['before']['game_state']['combat_state']['monsters'][0]['current_hp'] = 100
    assert review_and_store(rows, tmp_path / 'experience.json') == []


def test_corrupt_memory_is_reported_not_silently_applied(tmp_path):
    from slay_jev_spire.experience import applicable_experiences
    path = tmp_path / 'experience.json'; path.write_text('broken')
    lessons = applicable_experiences({'screen_type': 'NONE'}, path)
    assert lessons == []
