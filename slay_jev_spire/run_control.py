"""显式恢复已中断的运行，重载代码但不重复发送旧动作。"""

import importlib
from copy import deepcopy


def resume_session(old, budget: int, *, session_factory=None):
    if not old.stopped or old.reason in {'game_over', 'left_game', 'run_changed'}:
        raise ValueError('此运行不能恢复。')
    if type(budget) is not int or not 1 <= budget <= 2000:
        raise ValueError('恢复预算必须为 1–2000。')
    if session_factory is None:
        # 依赖顺序重载；下一次选择只读取新的 STATE，不重试旧 pending。
        for name in ('selectors', 'native_combat', 'catalog', 'screens', 'journey', 'decision_memory', 'turn_planner', 'experience', 'run_session'):
            module = importlib.import_module('slay_jev_spire.' + name)
            importlib.reload(module)
        from .run_session import RunSession
        session_factory = RunSession
    new = session_factory(old.output_dir, mode=old.mode,
                          max_decisions=old.calls + budget, run_id=old.run_id)
    new.calls, new.actions, new.step_id = old.calls, old.actions, old.step_id
    new.run_identity = old.run_identity
    if hasattr(old, 'memory'):
        new.memory = deepcopy(old.memory)
        new._memory_restored = True
    for name in ('started_at', 'max_actions', 'max_seconds'):
        if hasattr(old, name):
            setattr(new, name, getattr(old, name))
    new._record('resumed', previous_session_id=old.id, additional_budget=budget,
                prior_stop_reason=old.reason)
    return new


def handle_resume_request(old, budget: int, *, session_factory=None):
    """只响应显式标志；暂停完成之后才创建新控制器。"""
    flag = old.output_dir / 'resume.flag'
    if not flag.exists():
        return old, False
    old.tick()
    if not old.stopped:
        return old, False
    requested = flag.read_text(encoding='utf-8').strip()
    if requested.isdecimal():
        budget = int(requested)
    if type(budget) is not int or not 1 <= budget <= 2000:
        flag.unlink()
        old._record('resume_failed', reason='invalid_request_budget')
        return old, False
    if old.sent is not None and old.sent_ack:
        from .run_session import confirmation
        raw = old.last_raw
        evidence = None
        if raw and raw.get('ready_for_command') is True and raw.get('in_game') is True:
            game = raw.get('game_state', {})
            identity = (game.get('seed'), game.get('class'), game.get('ascension_level'))
            if old.run_identity is None and old.sent[1]['action'].get('kind') == 'start':
                evidence = confirmation(old.sent[0], raw, old.sent[1]['action'])
                if evidence:
                    old.run_identity = identity
            elif identity == old.run_identity:
                evidence = confirmation(old.sent[0], raw, old.sent[1]['action'])
        if not evidence:
            if not getattr(old, 'resume_waiting', False):
                old._record('resume_waiting_confirmation', reason='outstanding_action_unconfirmed')
                old.resume_waiting = True
                old.resume_query_pending = True
            return old, False
        old._record('action_confirmed', before=old.sent[0], after=raw,
                    decision=old.sent[1], command=old.sent[1]['action']['command'], evidence=evidence)
        old.sent = old.pending = None
    flag.unlink()
    pause = old.output_dir / 'pause.flag'
    if pause.exists():
        pause.unlink()
    try:
        new = resume_session(old, budget, session_factory=session_factory)
    except Exception:
        # 重载失败时保持暂停，不进入自动请求或重发循环。
        pause.write_text('resume failed', encoding='utf-8')
        old._record('resume_failed')
        raise
    return new, True
