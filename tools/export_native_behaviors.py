"""Export versioned installed-game behavior sources for review, never execute them.

This is a source inventory, not an automatically verified semantic rule library.
Runtime patches may differ from the base JAR and must be audited separately.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile

DEFAULT_PREFIXES=('cards','relics','potions','powers','monsters','events','actions',
                  'characters','core','dungeons','rooms','helpers')


def export(jar,output,prefixes):
    output.mkdir(parents=True,exist_ok=True)
    jar_hash=sha256(jar.read_bytes()).hexdigest()
    manifest_path=output/'manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {}
    if manifest and manifest.get('jar_sha256')!=jar_hash:
        raise ValueError('Use a fresh directory for a changed game JAR')
    entries=manifest.get('classes',{})
    with ZipFile(jar) as source:
        wanted={name[:-6].replace('/','.') : sha256(source.read(name)).hexdigest()
                for name in source.namelist() if name.endswith('.class')
                and any(name.startswith(prefix.replace('.','/')+'/') for prefix in prefixes)}
    pending=[name for name,digest in wanted.items() if name not in entries
             or entries[name].get('bytecode_sha256')!=digest
             or not (output/entries[name]['file']).exists()]
    command=['javap','-J-Dfile.encoding=UTF-8','-sysinfo','-p','-c','-constants','-classpath',str(jar)]
    chunks=[];chunk=[];length=sum(len(v)+3 for v in command)
    for name in sorted(pending):
        if chunk and length+len(name)+3>24000: # Below Windows' 32767-character process limit.
            chunks.append(chunk);chunk=[];length=sum(len(v)+3 for v in command)
        chunk.append(name);length+=len(name)+3
    if chunk:chunks.append(chunk)
    errors=[]
    for group in chunks:
        result=subprocess.run(command+group,capture_output=True,text=True,encoding='utf-8',timeout=120)
        if result.returncode:
            errors.append({'classes':group,'error':result.stderr});continue
        matches=list(re.finditer(r'^Classfile .*!/(.+)\.class\s*$',result.stdout,re.M))
        found=set()
        for i,match in enumerate(matches):
            name=match[1].replace('/','.')
            if name not in wanted:continue
            text=result.stdout[match.start():matches[i+1].start() if i+1<len(matches) else None]
            filename=sha256(name.encode()).hexdigest()+'.txt'
            (output/filename).write_text(text,encoding='utf-8')
            entries[name]={'file':filename,'bytecode_sha256':wanted[name],
                           'text_sha256':sha256(text.encode()).hexdigest()}
            found.add(name)
        if found!=set(group):errors.append({'missing':sorted(set(group)-found),'error':'Unparsed javap class headers'})
    manifest={'jar_sha256':jar_hash,'jar_name':jar.name,'prefixes':prefixes,'expected':len(wanted),
        'exported':len(set(wanted)&entries.keys()),'complete':not errors and set(wanted)<=entries.keys(),
        'scope':__doc__,'classes':entries,'errors':errors}
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k not in {'classes','scope'}},ensure_ascii=True))
    return 0 if manifest['complete'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jar',type=Path,default=Path(r'C:\Program Files (x86)\Steam\steamapps\common\SlayTheSpire\desktop-1.0.jar'))
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prefix',action='append')
    args=parser.parse_args()
    raise SystemExit(export(args.jar,args.output,args.prefix or ['com.megacrit.cardcrawl.'+p for p in DEFAULT_PREFIXES]))
