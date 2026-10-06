import shutil
import subprocess
import pytest


def test_unknown_native_subclasses_export_data_without_invoking_effects(tmp_path):
    java,javac=shutil.which('java'),shutil.which('javac')
    if not java or not javac or subprocess.run([javac,'-version'],capture_output=True).returncode:
        pytest.skip('Java toolchain unavailable')
    source=tmp_path/'FieldsTest.java'
    source.write_text('''
import java.util.*;
import jevstate.NativeFields;
public class FieldsTest {
    static int effects;
    enum Phase { CHARGING; public String toString() { throw new AssertionError("Called enum display code"); } }
    static class Base { private int sharedEngineValue=999; }
    static class Mid extends Base { private int charge=2; }
    static class CardRef { String uuid="actual-card"; }
    static class NewMonster extends Mid {
        private int charge=7;
        private static final int THRESHOLD=11;
        private Phase phase=Phase.CHARGING;
        private int[] damages={4,9};
        private double unset=Double.NaN;
        private CardRef card=new CardRef();
        private Object objectGraph=new Object();
        public void takeTurn() { effects++; }
    }
    public static void main(String[] args) {
        NewMonster monster=new NewMonster();
        Map<String,Object> data=NativeFields.snapshot(monster,Base.class,(type,value)->
            type==CardRef.class ? Collections.singletonMap("card_uuid",((CardRef)value).uuid) : null);
        Map<?,?> instance=(Map<?,?>)data.get("instance_fields");
        Map<?,?> constants=(Map<?,?>)data.get("class_fields");
        if (!instance.get("charge").equals(7) || !instance.get("FieldsTest$Mid#charge").equals(2)) throw new AssertionError(data);
        if (!constants.get("THRESHOLD").equals(11) || !instance.get("phase").equals("CHARGING")) throw new AssertionError(data);
        if (!instance.get("damages").equals(Arrays.asList(4,9))) throw new AssertionError(data);
        if (!(instance.get("unset") instanceof Map)) throw new AssertionError("Non-finite JSON number");
        if (instance.containsKey("sharedEngineValue")) throw new AssertionError("Crossed native base boundary");
        if (!((List<?>)data.get("unexported_object_fields")).contains("objectGraph")) throw new AssertionError(data);
        if (!((Map<?,?>)data.get("references")).containsKey("card")) throw new AssertionError(data);
        monster.charge=10;
        Map<?,?> refreshed=(Map<?,?>)NativeFields.snapshot(monster,Base.class,null).get("instance_fields");
        if (!refreshed.get("charge").equals(10) || effects!=0) throw new AssertionError("Cached value or executed effect");
        Map<String,Object> boundary=NativeFields.atRevision(monster,Base.class,5,null);
        monster.charge=12;
        if (NativeFields.atRevision(monster,Base.class,5,null)!=boundary) throw new AssertionError("Same revision changed");
        Map<?,?> next=(Map<?,?>)NativeFields.atRevision(monster,Base.class,6,null).get("instance_fields");
        if (!next.get("charge").equals(12)) throw new AssertionError("New revision not captured");
    }
}
''',encoding='utf-8')
    subprocess.run([javac,'--release','8','-d',str(tmp_path),
        'mods/jev-state/src/jevstate/NativeFields.java',str(source)],check=True,capture_output=True)
    subprocess.run([java,'-cp',str(tmp_path),'FieldsTest'],check=True,capture_output=True)


def test_new_monster_data_preserves_native_thief_context():
    from slay_jev_spire.monsters import encounter_context
    monster={'id':'Looter','move_id':2,'intent':'DEFEND','powers':[],
             'native_fields':{'instance_fields':{'stolenGold':30,'goldAmt':15}}}
    context=encounter_context([monster])[0]
    assert context['stolen_gold']==30 and context['steals_per_attack']==15


def test_arbitrary_relic_card_reference_is_effect_evidence():
    from tests.test_bottled_selection import example
    from slay_jev_spire.screens import confirm_screen
    r=example();uid=r['action']['card']['uuid']
    for which in ('before','after'):
        relic=r[which]['game_state']['relics'][1]
        relic.update(id='FutureRelic',native_fields={'references':{'chosen':{
            'card_uuid':uid if which=='after' else None}}})
        relic.pop('bottled_card_uuid',None)
    assert 'native relic field' in confirm_screen(r['before'],r['after'],r['action'])
    r['after']['game_state']['relics'][1]['native_fields']['references']['chosen']['card_uuid']='wrong'
    assert confirm_screen(r['before'],r['after'],r['action']) is None
