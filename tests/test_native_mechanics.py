import shutil
import subprocess
import pytest


def test_unknown_classes_export_inherited_callbacks_without_running_effects(tmp_path):
    java,javac=shutil.which('java'),shutil.which('javac')
    if not java or not javac or subprocess.run([javac,'-version'],capture_output=True).returncode:
        pytest.skip('Java toolchain unavailable')
    source=tmp_path/'MechanicsTest.java'
    source.write_text('''
import java.util.*;
import jevstate.NativeMechanics;
public class MechanicsTest {
    static int effects=0;
    static class Base { public void atBattleStart() {} public void onCardDraw(String card) {} }
    static class Mid extends Base { public void onCardDraw(String card) { effects++; } }
    static class NeverRegisteredRelic extends Mid { public void atBattleStart() { effects++; } }
    public static void main(String[] args) {
        Map<String,Object> data=NativeMechanics.describe(new NeverRegisteredRelic(),Base.class);
        List<?> hooks=(List<?>)data.get("overridden_callbacks");
        if (!hooks.contains("atBattleStart()") || !hooks.contains("onCardDraw(String,)")) throw new AssertionError(data);
        if (effects!=0) throw new AssertionError("Introspection executed an effect");
        if (!data.get("java_class").toString().endsWith("NeverRegisteredRelic")) throw new AssertionError(data);
    }
}
''',encoding='utf-8')
    subprocess.run([javac,'-d',str(tmp_path),'mods/jev-state/src/jevstate/NativeMechanics.java',str(source)],check=True,capture_output=True)
    subprocess.run([java,'-cp',str(tmp_path),'MechanicsTest'],check=True,capture_output=True)
