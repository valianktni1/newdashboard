#!/usr/bin/env python3
"""Install the bundled Planner + Dashboard release on the existing TrueNAS stacks.

Uses Docker's existing YAML library; requires only Python's standard library on
the NAS. Existing env files and the Booking stack are never modified.
"""
import argparse
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import subprocess
import time

YAML_TRANSFORM = r'''
import sys,json,yaml
p=json.load(sys.stdin); d=yaml.safe_load(p['original'])
for name in p['services']:
    s=d['services'][name]
    b=s.get('build',{})
    if isinstance(b,str): b={'context':b}
    b['context']=p['source']; s['build']=b; s['image']=p['image']
    if name==p['credential_service']:
        env=s.get('environment') or {}
        if isinstance(env,list): env=dict((x.split('=',1)+[None])[:2] for x in env)
        for key in p['keys']: env.pop(key,None)
        s['environment']=env
        files=s.get('env_file') or []
        if isinstance(files,str):files=[files]
        if not any((f if isinstance(f,str) else f.get('path'))==p['secret'] for f in files):
            files.append(p['secret'])
        s['env_file']=files
print(yaml.safe_dump(d,sort_keys=False),end='')
'''


def run(command, *, input=None, stream=False):
    result = subprocess.run(command, input=input, text=True, capture_output=not stream)
    if result.returncode:
        # Resolved Compose diagnostics can contain passwords. Keep them private.
        raise RuntimeError('Command failed: ' + shlex.join(command[:3]) + '. See the rollback path printed above.')
    return result.stdout if not stream else ''


def unrelated(config, services, credential_service, keys):
    result = copy.deepcopy(config)
    for name in services:
        service = result['services'][name]
        service.pop('build', None)
        service.pop('image', None)
    env = result['services'][credential_service].get('environment', {})
    for key in keys:
        env.pop(key, None)
    return result


def compose(folder, file=None):
    return ['docker','compose','--project-directory',str(folder),'-f',str(file or folder/'compose.yaml')]


def container(folder, service):
    value = run(compose(folder)+['ps','-q',service]).strip()
    if not value or '\n' in value:
        raise RuntimeError('Expected one running '+service+' container. No restart attempted.')
    return value


def write_private(path, text):
    path.write_text(text, encoding='utf-8')
    path.chmod(0o600)


def booking_settings_signature(container_id):
    code = '''import sqlite3,os,json,hashlib
from pathlib import Path
p=Path(os.getenv('DATA_DIR','/data'))/'planner.sqlite3'
c=sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True)
r=c.execute("SELECT key,value FROM settings WHERE key IN ('wbm_booking_key_hash','wbm_booking_enabled') ORDER BY key").fetchall()
print(hashlib.sha256(json.dumps(r).encode()).hexdigest())
'''
    return run(['docker','exec',container_id,'python','-c',code]).strip()


def prepare(stack, *, source, services, credential_service, credentials, image, yaml_container, stamp):
    folder = stack.resolve()
    base = folder/'compose.yaml'
    if not base.is_file():
        raise RuntimeError('Existing compose.yaml missing at '+str(folder))
    before = json.loads(run(compose(folder)+['config','--format','json']))
    for name in services:
        container(folder, name)
    backup = folder/'deployment-backups'/('planner-dashboard-'+stamp)
    backup.mkdir(parents=True, mode=0o700)
    shutil.copy2(base, backup/'compose.yaml'); (backup/'compose.yaml').chmod(0o600)
    secret = folder/('.control-centre-planner-'+stamp+'.env')
    had_secret = secret.exists()
    if had_secret:
        shutil.copy2(secret,backup/'connection.env'); (backup/'connection.env').chmod(0o600)
    # A dedicated env_file adds ONLY this integration. Existing env files remain
    # byte-for-byte unchanged, including the Booking -> Planner credential.
    write_private(secret, ''.join(k+'='+v+'\n' for k,v in credentials.items()))
    release = folder/'deployment-releases'/('planner-dashboard-'+stamp)
    shutil.copytree(source,release)
    payload = dict(original=base.read_text(), services=services, credential_service=credential_service,
                   keys=list(credentials), source=str(release), image=image, secret=str(secret))
    updated = run(['docker','exec','-i',yaml_container,'python','-c',YAML_TRANSFORM],input=json.dumps(payload))
    candidate = folder/('compose.planner-candidate-'+stamp+'.yaml')
    write_private(candidate, updated)
    after = json.loads(run(compose(folder,candidate)+['config','--format','json']))
    if unrelated(before, services, credential_service, credentials) != unrelated(after, services, credential_service, credentials):
        raise RuntimeError('STOP: unrelated effective Compose settings would change. Live Compose files have not been replaced.')
    effective = after['services'][credential_service]['environment']
    if any(effective.get(key) != value for key,value in credentials.items()):
        raise RuntimeError('STOP: Compose did not load the new connection credentials.')
    rollback_images = {}
    for name in services:
        cid=container(folder,name)
        old=run(['docker','inspect','--format','{{.Image}}',cid]).strip()
        tag='control-centre-rollback-'+name+':'+stamp
        run(['docker','image','tag',old,tag])
        rollback_images[name]={'image':tag,'pull_policy':'never'}
    write_private(backup/'images.yaml',json.dumps({'services':rollback_images}))
    return dict(folder=folder,base=base,candidate=candidate,backup=backup,secret=secret,
                had_secret=had_secret,image=image,services=services,before=before)


def rollback_script(stacks):
    lines=['#!/usr/bin/env bash','set -Eeuo pipefail','umask 077']
    for s in stacks:
        q=lambda p:shlex.quote(str(p))
        lines.append('cp -p '+q(s['backup']/'compose.yaml')+' '+q(s['base']))
        lines.append(('cp -p '+q(s['backup']/'connection.env')+' '+q(s['secret'])) if s['had_secret'] else 'rm -f -- '+q(s['secret']))
        cmd=compose(s['folder'])+['-f',str(s['backup']/'images.yaml'),'up','-d','--no-build','--force-recreate',*s['services']]
        lines.append(shlex.join(cmd))
    lines.append('echo "Planner and dashboard images/configuration rolled back. Live data was preserved."')
    return '\n'.join(lines)+'\n'


def check(command, attempts=30, expected=None):
    for _ in range(attempts):
        result=subprocess.run(command,text=True,capture_output=True)
        if result.returncode==0 and (expected is None or result.stdout.strip()==expected):
            return result.stdout
        time.sleep(2)
    raise RuntimeError('Live startup/connection check failed.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',required=True,type=Path)
    parser.add_argument('--planner',type=Path,default=Path('/mnt/apps/weddingplannercouples'))
    parser.add_argument('--dashboard',type=Path,default=Path('/mnt/apps/dockge/data/newdashboard'))
    args=parser.parse_args()
    if os.geteuid()!=0:raise SystemExit('Run this installer as root on TrueNAS.')
    os.umask(0o077)
    root=args.bundle.resolve()
    for repo in ('newdashboard','weddingplannercouples'):
        if not (root/repo/'Dockerfile').is_file():raise SystemExit('Incomplete source bundle: '+repo)
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    # A new dedicated key; existing Booking keys are neither read nor rotated.
    key=secrets.token_urlsafe(48)
    dashboard_id=container(args.dashboard,'dashboard')
    planner_id=container(args.planner,'web')
    signature=booking_settings_signature(planner_id)
    print('1/6 Preparing private local source builds and rollback files...',flush=True)
    planner=prepare(args.planner,source=root/'weddingplannercouples',services=['web','worker'],
                    credential_service='web',credentials={'PLANNER_CONTROL_CENTRE_ENABLED':'true','PLANNER_CONTROL_CENTRE_KEY':key},
                    image='planner-control-centre:'+stamp,yaml_container=dashboard_id,stamp=stamp)
    dashboard=prepare(args.dashboard,source=root/'newdashboard',services=['dashboard'],
                      credential_service='dashboard',credentials={'DASHBOARD_PLANNER_KEY':key,'DASHBOARD_PLANNER_URL':'https://planner.ivorydigital.uk'},
                      image='dashboard-planner:'+stamp,yaml_container=dashboard_id,stamp=stamp)
    stacks=[planner,dashboard]
    rollback=dashboard['backup']/'rollback.sh'
    write_private(rollback,rollback_script(stacks))
    print('Rollback command: bash '+shlex.quote(str(rollback)),flush=True)
    print('2/6 Building both images while the old containers keep running...',flush=True)
    for s,service in ((planner,'web'),(dashboard,'dashboard')):
        run(compose(s['folder'],s['candidate'])+['build',service],stream=True)
    run(['docker','run','--rm','--network','none','--read-only','--tmpfs','/tmp:mode=1777',planner['image'],
         'python','-c',"from app.server import create_app,VERSION; assert VERSION=='1.3.2'; a=create_app({'DATA_DIR':'/tmp/check','BACKUP_DIR':'/tmp/backups'}); assert any(r.rule=='/api/integrations/control-centre/overview' for r in a.url_map.iter_rules())"])
    run(['docker','run','--rm','--network','none','--read-only','--tmpfs','/tmp:mode=1777',dashboard['image'],
         'python','-c',"from app.planner_connection import planner_snapshot; import app.main; assert app.main.APP_VERSION=='1.3.0'; assert any(r.path=='/api/planner/overview' for r in app.main.app.routes)"])
    print('3/6 Backing up planner data and testing recovery in isolation...',flush=True)
    run(compose(args.planner)+['exec','-T','worker','python','manage.py','backup'])
    archive=run(['docker','exec',container(args.planner,'worker'),'python','-c',
                 "from pathlib import Path; import os; print(max(Path(os.getenv('BACKUP_DIR','/backups')).glob('planner-*.tar.gz'),key=lambda p:p.stat().st_mtime))"]).strip()
    snapshot=planner['backup']/'planner-before.tar.gz'
    run(['docker','cp',container(args.planner,'worker')+':'+archive,str(snapshot)])
    snapshot.chmod(0o600)
    run(['docker','run','--rm','--network','none','--read-only','--user','0:0','--tmpfs','/tmp:mode=1777',
         '--mount','type=bind,src='+str(planner['backup'])+',dst=/snapshot,readonly',planner['image'],
         'python','scripts/test_restore.py','/snapshot/planner-before.tar.gz','--work-dir','/tmp'],stream=True)
    print('Planner backup:',snapshot,flush=True)
    print('4/6 Backing up the dashboard database...',flush=True)
    backup_name='control-centre-before-planner-'+stamp+'.db'
    code="import sqlite3,os; from pathlib import Path; p=Path(os.getenv('DASHBOARD_DATA_DIR','/data')); s=sqlite3.connect((p/'control-centre.db').as_uri()+'?mode=ro',uri=True); d=sqlite3.connect(p/"+repr(backup_name)+"); s.backup(d); assert d.execute('PRAGMA integrity_check').fetchone()[0]=='ok'; d.close(); s.close(); print(p/"+repr(backup_name)+")"
    print('Dashboard backup:',run(['docker','exec',dashboard_id,'python','-c',code]).strip(),flush=True)
    changed=False
    try:
        print('5/6 Updating only Planner web/worker and Dashboard...',flush=True)
        for s in stacks:
            shutil.copystat(s['base'],s['candidate'])
            stat=s['base'].stat(); os.chown(s['candidate'],stat.st_uid,stat.st_gid)
            os.replace(s['candidate'],s['base']); changed=True
            run(compose(s['folder'])+['up','-d','--no-deps','--no-build','--force-recreate',*s['services']],stream=True)
        print('6/6 Checking running apps, the new feed and existing Booking settings...',flush=True)
        planner_id=container(args.planner,'web')
        check(['docker','exec',planner_id,'python','-c',
               "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4)); assert d['status']=='ok' and d['version']=='1.3.2'"])
        if booking_settings_signature(planner_id)!=signature:raise RuntimeError('Existing Booking invitation settings changed unexpectedly.')
        worker_id=container(args.planner,'worker')
        check(['docker','inspect','--format','{{.State.Health.Status}}',worker_id], expected='healthy')
        dashboard_id=container(args.dashboard,'dashboard')
        check(['docker','exec',dashboard_id,'python','-c',
               "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8080/api/health',timeout=4)); assert d['status']=='ok' and d['version']=='1.3.0'"])
        # Each probe is a fresh process: no cached failure can mask recovery.
        check(['docker','exec',dashboard_id,'python','-c',
               "from app.planner_connection import planner_snapshot; s=planner_snapshot(); assert s['status']=='connected',s['message']; print('Planner connection: connected (read only)')"],attempts=6)
        print('Planner connection: connected (read only). Dashboard: healthy. Planner worker: healthy.')
        print('Verified: the existing Booking invitation settings are unchanged. Booking was not restarted.')
        print('Open https://dashboard.weddingsbymark.uk/ and refresh the page.')
    except Exception:
        if changed:
            print('Update checks failed. Rolling back application images and configuration; preserving live data.',flush=True)
            try:run(['bash',str(rollback)],stream=True)
            except RuntimeError:print('Automatic rollback failed. Run: bash '+shlex.quote(str(rollback)),flush=True)
        raise


if __name__=='__main__':
    try:main()
    except RuntimeError as error:raise SystemExit(str(error))
