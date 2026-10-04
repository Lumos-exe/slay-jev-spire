"""把运行事件转换为可读的决策时间线；不调用模型、不推断因果。"""

from .records import safe_text
from .run_metrics import run_metrics


def _cell(value) -> str:
    return str(value if value is not None else '—').replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def _game(raw) -> dict:
    return raw.get('game_state', {}) if isinstance(raw, dict) else {}


def _delta(before, after, key):
    a, b = before.get(key), after.get(key)
    return f'{b - a:+d}' if type(a) is int and type(b) is int else '—'


def render_run_report(rows: list[dict], run_id: str) -> str:
    """只汇总指定运行的证据，未确认的命令和中断不会写成成功。"""
    events = [row for row in rows if row.get('run_id') == run_id]
    if not events:
        raise ValueError('找不到指定运行的记录。')
    lifecycle = next((r for r in reversed(events) if r.get('status') in {'stopped', 'complete', 'resumed'}), None)
    terminal = lifecycle if lifecycle and lifecycle['status'] != 'resumed' else None
    outcome = '进行中；未确认整局结束'
    if terminal:
        game = _game(terminal.get('after'))
        result = game.get('screen_state', {})
        if terminal['status'] == 'complete' and game.get('screen_type') == 'GAME_OVER' and type(result.get('victory')) is bool:
            outcome = ('胜利' if result['victory'] else '死亡') + '；分数 ' + _cell(result.get('score'))
        elif terminal['status'] == 'stopped':
            outcome = '中断；原因 ' + _cell(terminal.get('reason'))
        else:
            outcome = '未确认整局结束'
    mode = next((r.get('mode') for r in events if r.get('mode')), '未知')
    metrics = run_metrics(events)
    lines = ['# 对局决策记录', '', f'运行：`{_cell(run_id)}`', '', f'选择模式：{_cell(mode)}', '', f'结果：{outcome}', '',
             '下表记录观察到的状态变化。血量、金币变化属于本次动作到确认之间的观测，不代表已证明因果或策略优劣。', '']
    lines += [f"请求尝试 {metrics['api_requests']}；合法选择 {metrics['valid_decisions']}；已确认动作 {metrics['confirmed_actions']}；失败请求 {metrics['failed_requests']}；重复局面请求 {metrics['duplicate_requests']}；无返回记录 {metrics['pending_requests']}。", '',
              '重复局面需结合动作判断是否浪费；请求尝试数不是服务商账单或 token 使用量。', '']
    decisions = [r for r in events if r.get('status') == 'decision']
    if not decisions:
        lines.append('尚无决策记录。')
    else:
        lines += ['| 步骤 | 楼层 / 界面 | 选择与命令 | 置信度 | 执行状态 | 血量变化 | 金币变化 | 结果证据 |',
                  '| --- | --- | --- | --- | --- | --- | --- | --- |']
        by_step = {}
        for event in events:
            by_step.setdefault(event.get('step_id'), []).append(event)
        for row in decisions:
            step = row.get('step_id')
            following = by_step.get(step, [])
            confirmation = next((r for r in following if r.get('status') == 'action_confirmed'), None)
            sent = any(r.get('status') == 'command_sent' for r in following)
            status = '已确认' if confirmation else ('已发送，未确认' if sent else '未发送')
            before = _game(row.get('before'))
            after = _game(confirmation.get('after')) if confirmation else {}
            decision = row.get('decision', {})
            action = decision.get('action', {})
            values = [step, f"{before.get('floor', '—')} / {before.get('screen_type', '—')}",
                      f"{action.get('description', '—')} ({action.get('command', '—')})",
                      decision.get('confidence'), status, _delta(before, after, 'current_hp'),
                      _delta(before, after, 'gold'), confirmation.get('evidence') if confirmation else None]
            lines.append('| ' + ' | '.join(_cell(v) for v in values) + ' |')
    return safe_text('\n'.join(lines) + '\n')
