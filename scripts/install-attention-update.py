#!/usr/bin/env python3
"""Dashboard-only update: preserve all connection settings and other stacks."""
import argparse
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time

TRANSFORM = '''import sys,json,yaml
p=json.load(sys.stdin); d=yaml.safe_load(p['original']); s=d['services']['dashboard']
b=s.get('build',{})
if isinstance(b,str):b={'context':b}
b['context']=p['source']; s['build']=b; s['image']=p['image']
print(yaml.safe_dump(d,sort_keys=False),end='')
'''

PROBE = '''import json,urllib.request
import app.main
from app.booking_connection import booking_snapshot
from app.planner_connection import planner_snapshot
h=json.load(urllib.request.urlopen('http://127.0.0.1:8080/api/health',timeout=4))
assert h['status']=='ok'
print(json.dumps({'version':h['version'],'booking':booking_snapshot()['status'],'planner':planner_snapshot()['status']}))
'''


def run(command, *, input=None, stream=False):
    result=subprocess.run(command,input=input,text=True,capture_output=not stream)
    if result.returncode:
        raise RuntimeError('A dashboard update command failed. Configuration diagnostics were withheld to protect secrets.')
    return '' if stream else result.stdout


def compose(folder, file=None):
    return ['docker','compose','--project-directory',str(folder),'-f',str(file or folder/'compose.yaml')]


def unrelated(config):
    result=copy.deepcopy(config)
    service=result['services']['dashboard']
    service.pop('build',None); service.pop('image',None)
    return result


def get_container(folder):
    value=run(compose(folder)+['ps','-q','dashboard']).strip()
    if not value or '\n' in value:raise RuntimeError('Expected one existing dashboard container.')
    return value


def private_file(path,text):
    path.write_text(text,encoding='utf-8');path.chmod(0o600)


def rollback_text(folder,backup):
    return '\n'.join(['#!/usr/bin/env bash','set -Eeuo pipefail',
        'cp -p '+shlex.quote(str(backup/'compose.yaml'))+' '+shlex.quote(str(folder/'compose.yaml')),
        shlex.join(compose(folder)+['-f',str(backup/'image.yaml'),'up','-d','--no-deps','--no-build','--force-recreate','dashboard']),
        'echo "Dashboard image and configuration restored. Live data preserved."',''])


def verify(folder,previous,attempts=15):
    for _ in range(attempts):
        cid=get_container(folder)
        result=subprocess.run(['docker','exec',cid,'python','-c',PROBE],text=True,capture_output=True)
        if result.returncode==0:
            status=json.loads(result.stdout)
            if status['version']=='1.4.0' and all(previous[key]!='connected' or status[key]=='connected' for key in ('booking','planner')):
                return status
        time.sleep(2)
    raise RuntimeError('Dashboard startup or an existing connection failed its verification.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--stack',type=Path,default=Path('/mnt/apps/dockge/data/newdashboard'))
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Run as root on TrueNAS.')
    os.umask(0o077)
    source=args.source.resolve();folder=args.stack.resolve();base=folder/'compose.yaml'
    if not (source/'app/static/attention.js').is_file() or not base.is_file():
        raise SystemExit('STOP: complete release source and existing dashboard compose.yaml are required.')
    cid=get_container(folder)
    previous=json.loads(run(['docker','exec',cid,'python','-c',PROBE]))
    before=json.loads(run(compose(folder)+['config','--format','json']))
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup=folder/'deployment-backups'/('attention-'+stamp);backup.mkdir(parents=True,mode=0o700)
    shutil.copy2(base,backup/'compose.yaml');(backup/'compose.yaml').chmod(0o600)
    image_id=run(['docker','inspect','--format','{{.Image}}',cid]).strip()
    old_image='dashboard-attention-rollback:'+stamp
    run(['docker','image','tag',image_id,old_image])
    private_file(backup/'image.yaml',json.dumps({'services':{'dashboard':{'image':old_image,'pull_policy':'never'}}}))
    rollback=backup/'rollback.sh';private_file(rollback,rollback_text(folder,backup))
    print('Rollback command: bash '+shlex.quote(str(rollback)),flush=True)
    release=folder/'deployment-releases'/('attention-'+stamp);shutil.copytree(source,release)
    image='dashboard-attention:'+stamp
    payload={'original':base.read_text(),'source':str(release),'image':image}
    candidate=folder/('compose.attention-'+stamp+'.yaml')
    private_file(candidate,run(['docker','exec','-i',cid,'python','-c',TRANSFORM],input=json.dumps(payload)))
    after=json.loads(run(compose(folder,candidate)+['config','--format','json']))
    if unrelated(before)!=unrelated(after):
        raise RuntimeError('STOP: runtime settings would change. Existing Compose file preserved.')
    print('1/4 Building Dashboard while the current container keeps running...',flush=True)
    run(compose(folder,candidate)+['build','dashboard'],stream=True)
    run(['docker','run','--rm','--network','none','--read-only','--tmpfs','/tmp:mode=1777',image,'python','-c',
         "from app.main import APP_VERSION; from pathlib import Path; assert APP_VERSION=='1.4.0'; assert 'DashboardAttention' in Path('/app/app/static/app.js').read_text(); assert Path('/app/app/static/attention.js').is_file()"])
    print('2/4 Backing up the dashboard database...',flush=True)
    name='control-centre-before-attention-'+stamp+'.db'
    code="import sqlite3,os; from pathlib import Path; p=Path(os.getenv('DASHBOARD_DATA_DIR','/data')); s=sqlite3.connect((p/'control-centre.db').as_uri()+'?mode=ro',uri=True); d=sqlite3.connect(p/"+repr(name)+"); s.backup(d); assert d.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; d.close(); s.close(); print(p/"+repr(name)+")"
    print('Dashboard backup:',run(['docker','exec',cid,'python','-c',code]).strip(),flush=True)
    changed=False
    try:
        print('3/4 Recreating only Dashboard; keeping all connection settings...',flush=True)
        stat=base.stat();shutil.copystat(base,candidate);os.chown(candidate,stat.st_uid,stat.st_gid)
        os.replace(candidate,base);changed=True
        run(compose(folder)+['up','-d','--no-deps','--no-build','--force-recreate','dashboard'],stream=True)
        print('4/4 Verifying Dashboard and existing read-only feeds...',flush=True)
        status=verify(folder,previous)
        print('Dashboard: healthy, version '+status['version'])
        print('Booking connection: '+status['booking']+'; Planner connection: '+status['planner'])
        print('Booking and Planner containers/configuration were not changed or restarted.')
        print('Refresh https://dashboard.weddingsbymark.uk/ to see the combined attention list.')
    except Exception:
        if changed:
            print('Verification failed; rolling back Dashboard image/configuration and preserving live data.',flush=True)
            try:run(['bash',str(rollback)],stream=True)
            except RuntimeError:print('Automatic rollback failed. Run: bash '+shlex.quote(str(rollback)),flush=True)
        raise


if __name__=='__main__':
    try:main()
    except RuntimeError as error:raise SystemExit(str(error))
