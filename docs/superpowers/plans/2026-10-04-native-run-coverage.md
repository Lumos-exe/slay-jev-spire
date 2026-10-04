# 原生整局状态覆盖 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 消除基础牌白名单造成的中断，扩展整局原生选择状态，保留可验证执行和明确的中断结果。

**Architecture:** 新增通用原生战斗适配器，依赖游戏 is_playable、has_target、费用和目标存活字段。新增其他界面的纯候选/确认模块，由 journey 和 RunSession 接入。游戏文本目录只在应用边界读取并补充模型上下文；模板动态数值保持未知。

**Tech Stack:** Python 3.12、pytest、CommunicationMod 1.2.1、本机游戏 Jar。

## Global Constraints

- 保留已有脏工作树和旧单战斗/离线严格模式；不读密钥，不发真实 API，不擅自覆盖存档。
- 原生索引不可重排，选择器只能返回预生成候选。处理 X 费、不可用状态牌、消耗、虚无、能力、遗物和充能球，不声称模拟效果或计算完整伤害。
- 所有结果需对应动作证据，过渡和未知状态不得因任意 raw 变化判为成功。
- 大模型复盘与持久经验仍是总体目标，当前阶段不能声称已完整通关。

### Task 1: 通用原生战斗

- [x] 新建 `native_combat.py` 与 `catalog.py`，及对应有意义的失败测试。
- [x] 通用摘要保留完整卡牌/能力元数据和原索引；允许原生可用 X 费和免费牌，拒绝错误字段。
- [x] 原生 Potion USE/DISCARD 候选保留槽位、合法目标与可用标志；确认槽位消耗或状态变化证据。
- [x] 从游戏 Jar 读取英文卡牌、能力、遗物描述作为提示文本；标明模板未解析，不编造数值。

### Task 2: 其他选择界面

- [x] 新建 `screens.py` 及测试，输出候选和动作特定确认。
- [x] 支持 EVENT（禁用项与 choice_index）、CHEST、SHOP_ROOM、SHOP_SCREEN（仅可负担商品且原顺序含 purge）、REST、BOSS_REWARD、GRID、HAND_SELECT。
- [x] 支持原生确认、取消、离开按钮，不允许取消后无限重复进入。
- [x] 针对升级、删牌、转换、消耗/丢弃选牌使用可见卡组/选牌证据，确认后切换界面也可验证。

### Task 3: 接入与独立验证

- [x] 接入 journey、RunSession 与模型上下文，保留旧模式。
- [x] 支持奖励中的钥匙，跨章节过渡，以及局内结果确认。
- [x] 改进状态窗口的停止原因，自动导出当前局时间线。
- [x] 验证真实停止快照“无惧疼痛”已支持，全套回归通过、独立审查通过。
- [x] 不要求用户逐步等待；说明仍需游戏进程重载的边界，实机结果只按日志报告。
