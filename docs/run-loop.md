# 有界跨界面执行

`--run mock|jev` 使用游戏报告的可用标志处理铁甲战士的卡牌、能力、遗物和药水，支持战斗、奖励、地图、事件、商店、营火、宝箱、首领奖励、网格和手牌选择。旧的 `--combat` 和离线模式仍保留原型阶段的严格范围。错误字段或无法确认的执行仍会停止；覆盖这些原生界面不代表已完成整局实机验证。

默认在主菜单等待用户“继续”；明确传入 `--start-new` 时，程序刷新主菜单状态后发送一次 `START IRONCLAD 0` 开始新局。双击 `play_new_jev.cmd` 使用这个选项；它会开始新局，可能替换现有铁甲存档，所以继续已有存档使用 `play_jev.cmd`。

新版进程中，双击 `resume_jev.cmd` 会先暂停，再重载本地业务代码、刷新局面，并提供额外一段请求预算。恢复保留同一 run_id 与连续步骤编号，不重发旧动作。旧版已经启动的进程尚无这个入口，需要重启一次才能加载它。每次停止或整局结束会自动导出 `logs/live/run-report.md` 和按运行 ID 命名的时间线。

模型摘要可选读取本机游戏 Jar 的英文卡牌、能力、遗物文本；未解析的 `!D!`、`!B!`、`!M!` 等动态值保持未知，不用名字猜数值。原生 canUse 仍是动作可用性的依据，游戏负责计算真实效果。

```powershell
.venv\Scripts\python.exe -X utf8 -u capture_game.py --run mock --max-decisions 5
powershell -ExecutionPolicy Bypass -File tools\setup_communication_mod.ps1 -Run -Mode jev -MaxDecisions 5
```

setup 的 `-Run`、`-Combat`、`-ExecuteOnce` 互斥；CLI 三个模式也互斥。整局请求预算默认 500，可配置 1–2000；旧单场模式仍为 1–50。整局还有默认 90 分钟、2000 动作上限，恢复沿用这两个上限。Jev 密钥沿用安全本地配置；单元测试不调用真实 API。配置脚本修改游戏 CommunicationMod 配置并保存备份；新模式需重启对应通信进程才生效。

新控制器保留已确认动作及单组奖励拒绝记忆，从同局日志重建，恢复时继承。相同摘要与候选最多允许两次请求，第三次在联网前停止。新的 JevState Mod 补充游戏当前卡牌字段，标准数值模板可解析，但不声称获得每目标的完整伤害预测。首次加载需正常重启游戏。完整说明见 [独立测试](independent-testing.md)。

根据稳定状态选择候选后，发送动作前请求 STATE 并精确比较快照。暂停文件 `logs/live/pause.flag` 阻止后续选择和发送，模型返回后再次检查。无指令或未准备好的过渡状态最多等待 15 秒；发送动作后最多等待 30 秒证据。请让代理作为唯一操作方，避免同时手动操作。仅无关字段变化不会确认成功。

`runs.jsonl` 追加 UUID run_id、step_id、选择输入、原生候选、决策、实际发送、确认后状态及 evidence。command_sent 只表示传输发送；action_confirmed 才表示观察到对应结果。金币需增加且奖励项移除，卡牌需进入卡组且选择界面关闭；地图仅确认同一局楼层前进，原生后状态不直接报告目的节点，因此不能宣称验证了精确 x/y。未确认动作不会继续决策；超时、暂停和不支持状态保留中断记录。只有原生 GAME_OVER 的 victory/score 才记录 complete。

导出已有记录：

```powershell
.venv\Scripts\python.exe export_run.py --run-id UUID --log logs/live/runs.jsonl --output logs/live/run-report.md
```

本里程碑的验证是本地原生捕获夹具和协议模拟，不等同于真实完整通关。最终目标和后续扩展见 [产品目标](product-goal.md) 与 [实现计划](superpowers/plans/2026-10-04-run-continuation.md)：扩大规则覆盖、支持所有界面与新局、完整局结束、证据关联复盘、持久经验检索及应用操作界面。
