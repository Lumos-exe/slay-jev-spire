"""项目启动入口：把命令行交给 cli.main，并将返回值作为退出码。"""

from slay_jev_spire.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
