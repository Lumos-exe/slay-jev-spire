"""CommunicationMod 专用入口；与人类可读的离线 CLI 分开。"""

from slay_jev_spire.transport.communication_mod import main


if __name__ == '__main__':
    raise SystemExit(main())
