"""Execute the Java identity contract without a game/Jev dependency."""
from pathlib import Path
import shutil
import subprocess
import pytest


def test_native_identity_lifecycle(tmp_path):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('Java toolchain unavailable')
    if subprocess.run([javac, '-version'], capture_output=True).returncode:
        pytest.skip('Java toolchain unavailable')
    source = tmp_path / 'IdentityTest.java'
    source.write_text('''
import jevstate.IdentityLedger;
public class IdentityTest {
    public static void main(String[] args) {
        IdentityLedger ledger = new IdentityLedger();
        String run = ledger.runId();
        Object room = new Object();
        String first = ledger.identify(room);
        if (!first.equals(ledger.identify(room))) throw new AssertionError("same instance");
        if (first.equals(ledger.identify(new Object()))) throw new AssertionError("different source");
        if (ledger.identify(null) != null) throw new AssertionError("unknown object");
        ledger.reset(run);
        if (!run.equals(ledger.runId())) throw new AssertionError("save reload lost run");
        if (first.equals(ledger.identify(room))) throw new AssertionError("reconstructed source reused");
        ledger.reset(null);
        if (run.equals(ledger.runId())) throw new AssertionError("new game reused run");
    }
}
''', encoding='utf-8')
    subprocess.run([javac, '-d', str(tmp_path),
        'mods/jev-state/src/jevstate/IdentityLedger.java', str(source)], check=True, capture_output=True)
    subprocess.run([java, '-cp', str(tmp_path), 'IdentityTest'], check=True, capture_output=True)
