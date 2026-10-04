# 整局代理：奖励与地图衔接 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 将已有单战斗控制器扩展成跨奖励、选牌、地图和下一场受支持战斗的有界控制器，并记录每个决策的执行结果。

**Architecture:** 保留单战斗模式。新增纯函数界面适配器与独立 RunSession，复用现有暂停、超时、密钥和选择器边界。模型只选择程序生成的候选，动作发送前刷新校验，发送后等待具有动作含义的结果证据。

**Tech Stack:** Python 3.12、pytest、CommunicationMod 1.2.1、现有 Jev SDK。

## Global Constraints

- 最终产品目标：用户发起新局；代理处理所有战斗、地图、事件、奖励、商店、营火和特殊选牌，直到胜利或死亡；导出完整决策与结果；大模型复盘；下一局检索持久经验并影响决策。
- 当前里程碑只覆盖已支持战斗、COMBAT_REWARD、CARD_REWARD、MAP、COMPLETE。未支持状态明确停止，不能宣称整局能力已完成。
- 保留所有既有修改，不提交密钥，不输出密钥，不启动真实 API 测试作为单元测试。
- 不根据未知卡牌或遗物编造效果；现有战斗支持限制仍然生效。无指令的过渡态等待，超时停止。
- 原生 choice_list 的索引是零基索引，过滤候选之后不得重新编号。摘要包含卡组、遗物、药水、血量、金币和地图路线信息。
- 每次决策需关联运行 ID、步骤 ID、前状态、选择、实际发送、后状态、确认或停止原因。随机种子不能独自充当运行 ID。
- 原生 GAME_OVER 才确认整局结束；用户暂停、决策预算耗尽或不支持状态属于中断。
- 真实测试仍采用有界请求预算，暂停文件立即阻止后续发送；旧状态或仅无关字段变化不能确认动作成功。

### Task 1: 跨界面控制与记录

**Files:** Create `slay_jev_spire/journey.py`, `slay_jev_spire/run_session.py`, `tests/test_journey.py`, `tests/test_run_session.py`; modify transport entry, selectors instructions and setup script; add usage documentation.

**Interfaces:** `prepare_journey(raw: dict) -> tuple[dict, list[Action]]`; `RunSession` exposes `receive`, `tick`, `command_sent` compatible with CombatSession; CLI `--run {mock,jev}` mutually exclusive with existing execution modes, budget 1–50.

- [x] Write meaningful failing tests for reward choice indices, full potion slots, optional skip, map label/node alignment, unsupported screens, and model route context.
- [x] Implement pure adapter, keeping card and reward data as data rather than instructions.
- [x] Write failing controller tests for rewards → card reward → map → combat, duplicate state, changed state before send, action confirmation, unsupported state after confirmed action, run identity changes, final game-over result, pause and call limit.
- [x] Implement controller and append-only correlated input/output outcome records; failed/unconfirmed execution cannot silently proceed.
- [x] Wire CLI and setup script, keeping existing capture/once/combat behavior; update Jev instructions for run-wide choices.
- [x] Document final roadmap and implemented limits, and run full pytest plus git diff check.
- [x] Independent task review and fix important findings; independent final review of new milestone with regression context.

## Subsequent milestones

1. Expand combat card/power/relic/potion coverage and implement events, shops, rests, grid/hand selection, boss rewards and new-run initiation.
2. Complete real run ending at GAME_OVER and export human-readable timeline with observed results; preserve interrupted runs without claiming completion.
3. Hierarchical run review with evidence-linked lessons, alternatives marked as hypotheses, and explicit strategy changes.
4. Persist and retrieve conditional experience for next-run decisions; version policies and compare across multiple seeds to assess improvements.
5. Release application with start/pause/resume, API configuration, cost budgets and run/review browsing.
