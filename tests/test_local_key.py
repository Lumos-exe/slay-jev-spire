import os
import sys

import pytest


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows DPAPI')
def test_local_key_encrypted_roundtrip_and_corrupt_file_rejected(tmp_path, monkeypatch):
    from slay_jev_spire.config import load_jev_key, save_jev_key
    from slay_jev_spire.selectors import SelectionError
    path = tmp_path / 'key.dpapi'
    secret = 'test-only-secret-铁甲战士'
    save_jev_key(secret, path)
    assert secret.encode('utf-8') not in path.read_bytes()
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    load_jev_key(path)
    assert os.environ['TYPESAFE_API_KEY'] == secret
    monkeypatch.delenv('TYPESAFE_API_KEY')
    path.write_bytes(b'invalid encrypted file')
    with pytest.raises(SelectionError):
        load_jev_key(path)


def test_environment_key_has_priority_and_missing_key_is_clear(tmp_path, monkeypatch):
    from slay_jev_spire.config import load_jev_key
    from slay_jev_spire.selectors import SelectionError
    missing = tmp_path / 'missing.dpapi'
    monkeypatch.setenv('TYPESAFE_API_KEY', 'existing-test-key')
    load_jev_key(missing)
    assert os.environ['TYPESAFE_API_KEY'] == 'existing-test-key'
    monkeypatch.delenv('TYPESAFE_API_KEY')
    with pytest.raises(SelectionError):
        load_jev_key(missing)
