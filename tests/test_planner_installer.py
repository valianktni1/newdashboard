import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

spec=importlib.util.spec_from_file_location('planner_installer',Path(__file__).parents[1]/'scripts/install-planner-connection.py')
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_compose_transform_keeps_existing_connections_and_runtime_settings():
    original={'name':'existing','services':{'web':{'build':{'context':'old','args':{'X':'yes'}},
        'image':'old:local','env_file':['/mnt/apps/planner.env'],
        'environment':['APP_URL=https://planner.ivorydigital.uk','EXISTING_KEY=keep-this',
                       'PLANNER_CONTROL_CENTRE_KEY=obsolete'],
        'volumes':['/mnt/private:/data'],'ports':['30063:8000']},
        'worker':{'image':'old:local','command':['python','-m','app.worker'],
                  'env_file':['/mnt/apps/planner.env']}}}
    payload=dict(original=yaml.safe_dump(original),services=['web','worker'],credential_service='web',
                 keys=['PLANNER_CONTROL_CENTRE_KEY','PLANNER_CONTROL_CENTRE_ENABLED'],
                 source='/mnt/release',image='new:release',secret='/mnt/separate.env')
    result=subprocess.run([sys.executable,'-c',installer.YAML_TRANSFORM],input=json.dumps(payload),
                          text=True,capture_output=True,check=True)
    after=yaml.safe_load(result.stdout)
    web=after['services']['web']
    assert web['environment']=={'APP_URL':'https://planner.ivorydigital.uk','EXISTING_KEY':'keep-this'}
    assert web['env_file']==['/mnt/apps/planner.env','/mnt/separate.env']
    assert web['volumes']==original['services']['web']['volumes']
    assert web['ports']==original['services']['web']['ports']
    assert web['build']=={'context':'/mnt/release','args':{'X':'yes'}}
    assert after['services']['worker']['env_file']==['/mnt/apps/planner.env']
    assert 'environment' not in after['services']['worker']


def test_guard_rejects_any_unrelated_effective_change():
    before={'services':{'dashboard':{'build':{'context':'old'},'image':'old',
        'environment':{'DASHBOARD_BOOKING_KEY':'existing-booking-secret','DASHBOARD_COOKIE_SECURE':'true'},
        'volumes':[{'source':'/mnt/data','target':'/data'}]}}}
    after=copy.deepcopy(before)
    after['services']['dashboard']['build']['context']='new'
    after['services']['dashboard']['image']='new'
    after['services']['dashboard']['environment']['DASHBOARD_PLANNER_KEY']='newkey'
    strip=lambda v:installer.unrelated(v,['dashboard'],'dashboard',['DASHBOARD_PLANNER_KEY'])
    assert strip(before)==strip(after)
    after['services']['dashboard']['environment']['DASHBOARD_BOOKING_KEY']='changed'
    assert strip(before)!=strip(after)
    after=copy.deepcopy(before)
    after['services']['dashboard']['volumes'][0]['source']='/wrong/data'
    assert strip(before)!=strip(after)


def test_rollback_restores_original_paths_and_only_named_services(tmp_path):
    stack=dict(folder=tmp_path,base=tmp_path/'compose.yaml',backup=tmp_path/'backups',
               secret=tmp_path/'new.env',had_secret=False,services=['dashboard'])
    script=installer.rollback_script([stack])
    assert 'cp -p' in script and 'rm -f --' in script
    assert '--no-build --force-recreate dashboard' in script
    assert '--project-directory' in script
    assert 'bookingsystem2026' not in script
    assert 'backup' not in script.splitlines()[-1]  # No live data restore.


def test_failed_private_command_never_echoes_secret_diagnostics(monkeypatch):
    monkeypatch.setattr(installer.subprocess,'run',lambda *a,**k:subprocess.CompletedProcess(a,1,'SECRET','SECRET'))
    with pytest.raises(RuntimeError) as error:
        installer.run(['docker','compose','config'])
    assert 'SECRET' not in str(error.value)


def test_live_check_requires_healthy_status_not_just_successful_inspect(monkeypatch):
    replies=iter(['starting','unhealthy','healthy'])
    monkeypatch.setattr(installer.subprocess,'run',lambda *a,**k:subprocess.CompletedProcess(a,0,next(replies),''))
    monkeypatch.setattr(installer.time,'sleep',lambda _:None)
    assert installer.check(['docker','inspect'],expected='healthy').strip()=='healthy'
