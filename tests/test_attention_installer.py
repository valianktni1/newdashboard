import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

spec=importlib.util.spec_from_file_location('attention_installer',Path(__file__).parents[1]/'scripts/install-attention-update.py')
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def test_only_image_and_build_context_change_with_both_connections_preserved():
    original={'name':'newdashboard','services':{'dashboard':{
        'build':{'context':'/mnt/old','args':{'EXISTING':'value'}},'image':'previous:tag',
        'env_file':['.env','/mnt/private/planner.env'],
        'environment':{'DASHBOARD_BOOKING_KEY':'booking-secret','DASHBOARD_PLANNER_KEY':'planner-secret','DASHBOARD_DATA_DIR':'/data'},
        'volumes':['/mnt/apps/newdashboard:/data'],'ports':['30046:8080'],
        'read_only':True,'cap_drop':['ALL'],'tmpfs':['/tmp:size=64m,mode=1777']}}}
    payload={'original':yaml.safe_dump(original),'source':'/mnt/releases/new','image':'new:tag'}
    result=subprocess.run([sys.executable,'-c',installer.TRANSFORM],input=json.dumps(payload),text=True,capture_output=True,check=True)
    after=yaml.safe_load(result.stdout)
    assert installer.unrelated(original)==installer.unrelated(after)
    assert after['services']['dashboard']['build']=={'context':'/mnt/releases/new','args':{'EXISTING':'value'}}
    assert after['services']['dashboard']['env_file']==original['services']['dashboard']['env_file']
    for key in ('DASHBOARD_BOOKING_KEY','DASHBOARD_PLANNER_KEY'):
        bad=copy.deepcopy(after);bad['services']['dashboard']['environment'][key]='changed'
        assert installer.unrelated(original)!=installer.unrelated(bad)


def test_rollback_restarts_only_dashboard_and_does_not_restore_live_data(tmp_path):
    script=installer.rollback_text(tmp_path,tmp_path/'backup')
    assert '--no-deps --no-build --force-recreate dashboard' in script
    assert 'worker' not in script and 'bookingsystem2026' not in script
    assert 'planner.sqlite3' not in script and 'control-centre.db' not in script


def test_verification_requires_new_version_and_preserves_connected_feeds(monkeypatch):
    results=iter([{'version':'1.3.0','booking':'connected','planner':'connected'},
                  {'version':'1.4.1','booking':'connected','planner':'error'},
                  {'version':'1.4.1','booking':'connected','planner':'connected'}])
    monkeypatch.setattr(installer,'get_container',lambda _: 'dashboard-container')
    monkeypatch.setattr(installer.time,'sleep',lambda _:None)
    monkeypatch.setattr(installer.subprocess,'run',lambda *a,**k:subprocess.CompletedProcess(a,0,json.dumps(next(results)),''))
    status=installer.verify(Path('/existing'),{'booking':'connected','planner':'connected'},attempts=3)
    assert status['planner']=='connected'


def test_failed_existing_connection_rejects_release(monkeypatch):
    monkeypatch.setattr(installer,'get_container',lambda _: 'dashboard-container')
    monkeypatch.setattr(installer.time,'sleep',lambda _:None)
    monkeypatch.setattr(installer.subprocess,'run',lambda *a,**k:subprocess.CompletedProcess(a,0,json.dumps({'version':'1.4.1','booking':'error','planner':'connected'}),''))
    with pytest.raises(RuntimeError,match='connection'):
        installer.verify(Path('/existing'),{'booking':'connected','planner':'connected'},attempts=1)


def test_private_diagnostics_are_not_printed(monkeypatch):
    monkeypatch.setattr(installer.subprocess,'run',lambda *a,**k:subprocess.CompletedProcess(a,1,'secret-value','secret-value'))
    with pytest.raises(RuntimeError) as error:installer.run(['docker','compose','config'])
    assert 'secret-value' not in str(error.value)
