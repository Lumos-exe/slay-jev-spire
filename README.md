# Slay Jev Spire

Windows + Steam《杀戮尖塔》一代，需要已安装 ModTheSpire、BaseMod、CommunicationMod 和 JDK。

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe main.py configure
powershell -NoProfile -ExecutionPolicy Bypass -File tools\build_jev_state.ps1 -Install
```

先启动 Steam，正常退出已有游戏，再运行：

```powershell
# 启动后在游戏主菜单继续存档
.venv\Scripts\python.exe main.py play
# 指定种子开始新局，第一场战斗后停止；战斗方案完整枚举
.venv\Scripts\python.exe main.py play --new --combat-only --seed 12345 --beam-width 32
.venv\Scripts\python.exe main.py pause
.venv\Scripts\python.exe main.py resume --budget 100
.venv\Scripts\python.exe main.py status
.venv\Scripts\python.exe main.py report --expected 10
.venv\Scripts\python.exe main.py review
```

密钥使用当前 Windows 用户的 DPAPI 加密保存，或设置 `TYPESAFE_API_KEY` 环境变量。
`JEV_MODEL` 可固定模型；每次请求记录服务端实际返回的版本。

离线回放与测试：

```powershell
.venv\Scripts\python.exe main.py replay --state samples/quality_bash.json --mode mock
.venv\Scripts\python.exe main.py replay --state samples/quality_bash.json --mode jev --log logs/judge.jsonl
.venv\Scripts\python.exe -m pytest -q
# 在 Windows 桌面终端运行；先关闭游戏。新旧版本各跑 10 个相同种子。
.venv\Scripts\python.exe main.py benchmark --count 10
```

CommunicationMod 配置由启动脚本生成。协议入口是 `capture_game.py`，也可使用
`main.py agent --combat jev`；这些入口由游戏启动，不能把普通终端输出当协议输入。

运行事件和概率分布保存在 `logs/live/runs.jsonl`，状态快照保存在 `states.jsonl`。
`review` 为最近一局生成 JSON 复盘包，也可用 `--run-id` 或 `--log` 指定日志。
复盘包包含真实节点覆盖、未查看的卡牌奖励、未领取遗物、牌的使用情况、预测偏差及组件版本。
修改组件后先运行对应回归，再用相同条件重跑；单次输赢不直接证明改动有效。
报告中的中断不算胜利；未跑满 10 场会显示缺失数量。确定牌序逐步校验执行，抽牌、随机结果
及明确标记的未建模效果会产生观测点。真实模型概率及全卡池结算须以实际验证结果为准。

默认战斗路径使用 `native_sequences.py`：用当前原生手牌、费用、目标、药水枚举条件牌序。
完整牌序和执行后重新观察的动作段共同参选，不提供手写收益分或假定伤害结果。
后续步骤按原生动作再次验证；新增手牌、费用/能量变化、敌人意图或目标变化会停止旧队列并重新生成候选。
没有全局逐张出牌兜底。预算耗尽保留已有候选及每个原生首步，日志明确记录未枚举完的范围。
`--beam-width` 仅兼容旧命令，现已忽略。500 ms / 8000 次扩展 / 24 层是计算保护，不是战略剪枝或端到端超时。
全局枚举后由程序生成最多 32 项短名单，模型正常只做一次最终选择，不参与中间筛选。
只合并命令序列完全相同的重复项，再按首动作（含目标）、序列长度和 END/观察形式轮流取样。
剪枝不读取伤害、血量、卡牌效果或预测结果，不做致死过滤、模拟等价归并、攻击/防御排序。
全局候选与最终短名单分别记录。任何战斗模型请求均不得超过 32 项，不能绕过上限或回退成原生单张池。
最终取舍完全交给模型。当前“宽剪枝”实现与召回检查见 `docs/broad-shortlist32-20261006.md`。
非战斗保持原生选项路径；商店离开、卡牌选择后的确认由已确认的原生意图继续，不添加购买权重。
本次修复与验证边界见 `docs/strategy-fix-2026-10-05.md`。

线上完整 Jev 运行现在要求原生事务协议（JevState 0.3.x）。每条动作携带 ID、进程 epoch 和
状态 revision；`pending-action.json` 是发送前的持久化日志，不要在动作未核对时删除。
恢复先查询原生回执；已接受的动作不重发。卡牌效果检查只用于复盘，不再阻塞输入确认。
最新架构与六局实测见 `docs/native-transactions-validation.md`。
后续取消战斗评分/候选上限、信息边界及实战修复见 `docs/exhaustive-combat-validation.md`。
旧 B/C 结果编码保留用于离线 ABC 复现，历史接入记录见 `docs/b-live-rollout.md`。
当前条件牌序的覆盖统计、实际模型反例和上线验证见 `docs/native-sequences-20261006.md`；尚未证明能稳定跨幕通关。

基准运行独立保存到 `logs/benchmarks/<时间>/manifest.json`。基准专用 JVM 开关在第 1 层战斗前
固定 80 血、初始牌组、燃烧之血和空药水栏；普通游戏不启用。运行前备份存档与偏好，结束时恢复。
基准跳过涅奥奖励并开启游戏快速模式，两版使用相同条件；这些改动只在基准 JVM 开关下生效。
