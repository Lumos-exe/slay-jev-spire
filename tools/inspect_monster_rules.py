"""Read installed native bytecode; export evidence, never start or control a game."""
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile

GAME=Path(r'C:\Program Files (x86)\Steam\steamapps\common\SlayTheSpire\desktop-1.0.jar')
ROOT=Path(__file__).resolve().parents[1]
names={'Looter','Looter$1','Looter$2','Mugger','Mugger$1','Mugger$2','TheGuardian','SlimeBoss','AcidSlime_L','SpikeSlime_L','Hexaghost','ModeShiftPower','DamageAction'}
with ZipFile(GAME) as jar:
    classes = [p.removesuffix('.class').replace('/','.').removeprefix('com.megacrit.cardcrawl.')
               for p in jar.namelist() if Path(p).stem in names and p.endswith('.class')]
out={}
for name in classes:
    out[name]=subprocess.check_output(['javap','-classpath',str(GAME),'-c','-p','-constants',
                                      'com.megacrit.cardcrawl.'+name],text=True,encoding='utf-8',errors='replace')
path=ROOT/'logs/strategy-audit/native-monster-rules.json'
path.parent.mkdir(parents=True,exist_ok=True)
path.write_text(json.dumps(out,indent=2),encoding='utf-8')
print(path)
