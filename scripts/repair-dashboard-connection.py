#!/usr/bin/env python3
"""Load the dashboard's saved Booking key, preserving unrelated Compose settings."""
import argparse
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import time

KEYS=('DASHBOARD_BOOKING_KEY','DASHBOARD_BOOKING_URL')

TRANSFORM=r'''
import sys,yaml,json
doc=yaml.safe_load(sys.stdin.read())
assert isinstance(doc,dict) and isinstance(doc.get('services'),dict)
service=doc['services']['dashboard']
environment=service.get('environment') or {}
if isinstance(environment,list):
    environment=dict((item.split('=',1)+[None])[:2] for item in environment)
assert isinstance(environment,dict)
environment['DASHBOARD_BOOKING_KEY']='${DASHBOARD_BOOKING_KEY:?Dashboard booking key missing}'
environment['DASHBOARD_BOOKING_URL']='${DASHBOARD_BOOKING_URL:-https://booking.weddingsbymark.uk}'
service['environment']=environment
print(yaml.safe_dump(doc,sort_keys=False),end='')
'''


def value(text,key):
    found=re.search(r'^'+re.escape(key)+r'=(.*)$',text,re.M)
    return found.group(1).strip().strip('"\'') if found else ''


def unrelated(config):
    result=copy.deepcopy(config)
    environment=result['services']['dashboard'].get('environment',{})
    for key in KEYS:environment.pop(key,None)
    return result


def run(command,*,input=None,environment=None):
    result=subprocess.run(command,input=input,text=True,capture_output=True,env=environment)
    if result.returncode:
        # Do not echo Compose/YAML diagnostics: they may contain inline secrets.
        raise RuntimeError('A dashboard configuration check failed. No diagnostic secrets were printed.')
    return result.stdout


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stack',default='/mnt/apps/dockge/data/newdashboard')
    parser.add_argument('--configure-only',action='store_true')
    args=parser.parse_args()
    folder=Path(args.stack).resolve()
    compose=folder/'compose.yaml'
    if not compose.is_file() or not (folder/'.env').is_file():
        raise SystemExit('STOP: existing dashboard compose.yaml and .env are required.')
    env_text=(folder/'.env').read_text(encoding='utf-8')
    key=value(env_text,KEYS[0])
    if len(key)<32:
        raise SystemExit('STOP: the dashboard has no saved connection key. No files changed.')
    environment=dict(os.environ)
    environment[KEYS[0]]=key
    environment[KEYS[1]]=value(env_text,KEYS[1]) or 'https://booking.weddingsbymark.uk'
    command=['docker','compose','--project-directory',str(folder),'-f',str(compose)]
    before=json.loads(run(command+['config','--format','json'],environment=environment))
    container=run(command+['ps','-q','dashboard'],environment=environment).strip()
    if not container or '\n' in container:
        raise SystemExit('STOP: expected one existing dashboard container. No files changed.')
    original=compose.read_text(encoding='utf-8')
    updated=run(['docker','exec','-i',container,'python','-c',TRANSFORM],input=original)
    descriptor,filename=tempfile.mkstemp(prefix='compose.connection-check.',suffix='.yaml',dir=folder)
    candidate=Path(filename)
    backup=None
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8',newline='\n') as handle:handle.write(updated)
        candidate_command=['docker','compose','--project-directory',str(folder),'-f',str(candidate)]
        after=json.loads(run(candidate_command+['config','--format','json'],environment=environment))
        if unrelated(before)!=unrelated(after):
            raise RuntimeError('STOP: unrelated effective settings would change. Original configuration preserved.')
        effective=after['services']['dashboard']['environment']
        if effective.get(KEYS[0])!=key or effective.get(KEYS[1])!=environment[KEYS[1]]:
            raise RuntimeError('STOP: the candidate does not load the saved connection settings. Original preserved.')
        backup_dir=folder/'deployment-backups'/('dashboard-key-loading-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        backup_dir.mkdir(parents=True,mode=0o700)
        backup=backup_dir/'compose.yaml'
        shutil.copy2(compose,backup)
        backup.chmod(0o600)
        stat=compose.stat()
        shutil.copystat(compose,candidate)
        if hasattr(os,'chown'):os.chown(candidate,stat.st_uid,stat.st_gid)
        os.replace(candidate,compose)
    finally:
        candidate.unlink(missing_ok=True)
    print('Dashboard configuration backed up:',backup)
    print('Verified: only the two dashboard Booking connection settings changed.')
    print('Booking and Planner configurations were not accessed or modified.')
    if args.configure_only:return
    print('Rollback if needed: cp '+shlex.quote(str(backup))+' '+shlex.quote(str(compose)))
    print('Restarting only the existing dashboard container; no image build...')
    run(command+['up','-d','--no-deps','--no-build','--force-recreate','dashboard'],environment=environment)
    probe=('import json,urllib.request; '
           'h=json.load(urllib.request.urlopen("http://127.0.0.1:8080/api/health",timeout=4)); '
           'assert h["status"]=="ok"; import app.main; '
           'from app.booking_connection import booking_snapshot; '
           's=booking_snapshot(); print(json.dumps({"status":s["status"],"message":s["message"]}))')
    for attempt in range(15):
        current=run(command+['ps','-q','dashboard'],environment=environment).strip()
        result=subprocess.run(['docker','exec',current,'python','-c',probe],capture_output=True,text=True)
        if result.returncode==0:
            status=json.loads(result.stdout)
            print('Dashboard: ok')
            print('Booking connection:',status['status'])
            print(status['message'])
            return
        time.sleep(2)
    raise SystemExit('Dashboard has not passed its startup check. Share this message and the backup path above.')


if __name__=='__main__':
    try:main()
    except RuntimeError as error:raise SystemExit(str(error))
