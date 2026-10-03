# Windows 原生开发

后续在 Windows 本机开发，让 Python 与 Steam 游戏运行在同一系统。
当前只提供离线 CLI；CommunicationMod 进程接入仍需下一阶段实测。

## 准备工具

安装 Git for Windows、VS Code 及 Windows 本机 Python。项目要求 Python 3.12 或更高，建议先用 3.12 与已有验证环境对齐。
安装 Python 时确保包含 pip 和 Python Launcher。安装方法参考 [Python 官方 Windows 文档](https://docs.python.org/3.12/using/windows.html)。

VS Code 打开本机目录，在本机 PowerShell 运行命令，不使用 Remote WSL 窗口。

## 克隆与安装

仓库上传成功后，在准备存放代码的本机目录运行：

```powershell
git clone https://github.com/Lumos-exe/slay-jev-spire.git
cd slay-jev-spire
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\python.exe main.py --mode mock
.\.venv\Scripts\python.exe -m pytest -q
```

私有仓库使用 Git 的登录提示完成 GitHub 登录。已克隆后更新使用 `git pull`。
若安装的是其他受支持版本，把 `py -3.12` 改为实际安装的版本选择参数。

Linux 虚拟环境不能直接迁移到 Windows；Git 只同步源码和依赖声明，Windows 上重新创建 `.venv`。
这里直接运行环境内的 Python，不需要执行 PowerShell 激活脚本或修改脚本执行策略。
这些行为依据 [Python 官方 venv 文档](https://docs.python.org/3.12/library/venv.html)。

VS Code 执行 **Python: Select Interpreter**，选择 `.venv\Scripts\python.exe`。
项目文本统一为 UTF-8，Git 使用 LF 行尾；JSONL 读写已显式指定 UTF-8。

## 安全设置 Jev 密钥

在将要运行程序的同一个 PowerShell 中输入：

```powershell
$jevSecret = Read-Host 'Jev API key' -AsSecureString
$env:TYPESAFE_API_KEY = [System.Net.NetworkCredential]::new('', $jevSecret).Password
.\.venv\Scripts\python.exe main.py --mode jev --log logs/jev.jsonl
Remove-Item Env:TYPESAFE_API_KEY
Remove-Variable jevSecret
```

密钥通过隐藏输入传给当前进程环境，不写入命令历史、代码或 Git。
程序不自动读取 `.env`；DeepSeek 尚未接入，当前无需设置其密钥。

## 迁移后的验证顺序

1. 模拟 CLI 显示官方样本与 6 个候选，选择 `PLAY 1 0`，产生 `logs/decisions.jsonl`。
2. 测试通过，确认索引和模型返回校验，以及模拟不联网。
3. 用 Jev 密钥请求一次，检查 `logs/jev.jsonl` 的模式、返回模型和选择。
4. 再开始 CommunicationMod 传输层接入，在 Mod 配置中使用 Windows `.venv\Scripts\python.exe` 和专用协议入口；不能直接把现有人类可读 CLI 当协议进程启动。

WSL 的 `.venv`、密钥、记录和缓存不随仓库上传。
截至 2026-10-03，自动化验证仍是在 WSL2 完成，Windows 运行、真实 Jev 请求与游戏控制均尚未实测。
