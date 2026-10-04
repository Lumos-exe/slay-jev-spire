"""本机隐藏输入并加密保存 Jev API 密钥。"""

from getpass import getpass

from slay_jev_spire.config import save_jev_key
from slay_jev_spire.selectors import SelectionError


if __name__ == '__main__':
    try:
        save_jev_key(getpass('Jev API key (hidden): '))
        print('Jev key saved with Windows user encryption.')
    except (SelectionError, EOFError, KeyboardInterrupt):
        print('Unable to save Jev key; no key value was printed.')
        raise SystemExit(1)
