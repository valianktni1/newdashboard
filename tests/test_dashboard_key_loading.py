import importlib.util
from pathlib import Path
import subprocess
import sys
import json
import pytest

import yaml

path=Path(__file__).parents[1]/'scripts/repair-dashboard-connection.py'
spec=importlib.util.spec_from_file_location('repair_dashboard',path)
repair=importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def transform(text):
    result=subprocess.run([sys.executable,'-c',repair.TRANSFORM],input=text,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    return yaml.safe_load(result.stdout)


def test_repair_only_changes_the_two_dashboard_connection_fields():
    before={'name':'newdashboard','services':{'dashboard':{
        'image':'keep-current-image','ports':['30046:8080'],
        'volumes':['/mnt/apps/newdashboard:/data'],
        'environment':{'DASHBOARD_ADMIN_PASSWORD':'keep-private','DASHBOARD_DATA_DIR':'/data'},
        'read_only':True},'another-service':{'image':'untouched'}}}
    after=transform(yaml.safe_dump(before))
    assert repair.unrelated(before)==repair.unrelated(after)
    environment=after['services']['dashboard']['environment']
    assert environment['DASHBOARD_BOOKING_KEY']=='${DASHBOARD_BOOKING_KEY:?Dashboard booking key missing}'
    assert environment['DASHBOARD_ADMIN_PASSWORD']=='keep-private'
    assert after['services']['another-service']==before['services']['another-service']


def test_environment_list_and_env_file_are_preserved():
    data={'services':{'dashboard':{'env_file':['.env'],'environment':['DASHBOARD_DATA_DIR=/data','EXISTING_VALUE=one=two','FROM_HOST']}}}
    after=transform(yaml.safe_dump(data))
    service=after['services']['dashboard']
    assert service['env_file']==['.env']
    assert service['environment']['EXISTING_VALUE']=='one=two'
    assert service['environment']['FROM_HOST'] is None


def test_verifier_detects_any_unrelated_setting_change():
    before={'services':{'dashboard':{'ports':['30046:8080'],'environment':{}}}}
    after=transform(yaml.safe_dump(before))
    after['services']['dashboard']['ports']=['9999:8080']
    assert repair.unrelated(before)!=repair.unrelated(after)


@pytest.mark.parametrize('unexpected_change',[False,True])
def test_configuration_repair_backs_up_or_refuses_unrelated_changes(tmp_path,monkeypatch,capsys,unexpected_change):
    original='services:\n  dashboard:\n    image: keep-current\n    ports: ["30046:8080"]\n    environment:\n      DASHBOARD_DATA_DIR: /data\n'
    compose=tmp_path/'compose.yaml'
    compose.write_text(original,encoding='utf-8')
    saved='DASHBOARD_BOOKING_KEY='+'x'*48+'\n'
    (tmp_path/'.env').write_text(saved,encoding='utf-8')
    def fake_run(command,*,input=None,environment=None):
        if command[:2]==['docker','exec']:
            result=subprocess.run([sys.executable,'-c',repair.TRANSFORM],input=input,text=True,capture_output=True)
            assert result.returncode==0
            return result.stdout
        if 'config' in command:
            path=Path(command[command.index('-f')+1])
            data=yaml.safe_load(path.read_text(encoding='utf-8'))
            if path!=compose:
                env=data['services']['dashboard']['environment']
                for key in repair.KEYS:env[key]=environment[key]
                if unexpected_change:data['services']['dashboard']['ports']=['9999:8080']
            return json.dumps(data)
        if 'ps' in command:return 'dashboard-container\n'
        raise AssertionError('Unexpected operation')
    monkeypatch.setattr(repair,'run',fake_run)
    monkeypatch.setattr(sys,'argv',['repair','--stack',str(tmp_path),'--configure-only'])
    if unexpected_change:
        with pytest.raises(RuntimeError,match='unrelated'):repair.main()
        assert compose.read_text(encoding='utf-8')==original
    else:
        repair.main()
        assert '${DASHBOARD_BOOKING_KEY:' in compose.read_text(encoding='utf-8')
        backups=list(tmp_path.glob('deployment-backups/*/compose.yaml'))
        assert len(backups)==1
        assert backups[0].read_text(encoding='utf-8')==original
    assert (tmp_path/'.env').read_text(encoding='utf-8')==saved
    assert 'x'*48 not in capsys.readouterr().out
    assert not list(tmp_path.glob('compose.connection-check.*'))
