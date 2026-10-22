from datetime import datetime, timezone, timedelta
from urllib.error import HTTPError
import json
import os
import subprocess
import sys

from fastapi.testclient import TestClient
from test_dashboard import app, login, reset_data
from app import planner_connection as planner


def snapshot():
    return dict(schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(),
                business_date='2026-10-22',version='1.3.2',worker_status='ok',
                counts={key:0 for key in planner.COUNT_KEYS},
                queues={key:[] for key in planner.QUEUE_KEYS})


def clean_cache():
    planner.CACHE.update(attempted=None,data=None,error=None,checked_at=None)


def test_installer_can_import_snapshot_first_in_a_fresh_process():
    environment={**os.environ,'DASHBOARD_PLANNER_KEY':''}
    code=('from app.planner_connection import planner_snapshot; '
          'assert planner_snapshot()["status"] == "not_connected"; '
          'from app.main import app; '
          'assert any(route.path == "/api/planner/overview" for route in app.routes); '
          'assert any(route.path == "/api/planner/refresh" for route in app.routes)')
    result=subprocess.run([sys.executable,'-c',code],env=environment,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr


def test_planner_is_private_opt_in_cached_and_never_returns_key(monkeypatch):
    reset_data()
    clean_cache()
    monkeypatch.setattr(planner, 'PLANNER_KEY', '')
    calls=[]
    def read():
        calls.append(True)
        return snapshot()
    monkeypatch.setattr(planner, 'read_feed', read)
    with TestClient(app) as client:
        assert client.get('/api/planner/overview').status_code == 401
        assert client.post('/api/planner/refresh').status_code == 401
        login(client)
        assert client.get('/api/planner/overview').json()['status'] == 'not_connected'
        assert calls == []
        monkeypatch.setattr(planner, 'PLANNER_KEY', 'private-test-key-not-for-browser-'*2)
        response=client.get('/api/planner/overview')
        assert response.json()['status'] == 'connected'
        assert response.headers['cache-control'] == 'private, no-store'
        assert planner.PLANNER_KEY not in response.text
        client.get('/api/planner/overview')
        client.post('/api/planner/refresh')
        assert len(calls) == 1
        assert client.post('/api/planner/refresh',headers={'Origin':'https://attacker.example'}).status_code == 403


def test_connection_failures_keep_last_result_and_label_it_stale(monkeypatch):
    clean_cache()
    monkeypatch.setattr(planner,'PLANNER_KEY','x'*48)
    monkeypatch.setattr(planner,'read_feed',snapshot)
    assert planner.planner_snapshot()['status']=='connected'
    planner.CACHE['attempted']-=61
    def fail():
        raise HTTPError(planner.PLANNER_URL,401,'rejected',{},None)
    monkeypatch.setattr(planner,'read_feed',fail)
    result=planner.planner_snapshot()
    assert result['status']=='stale'
    assert result['data'] is not None
    assert 'rejected' in result['message']
    clean_cache()
    result=planner.planner_snapshot()
    assert result['status']=='error' and result['data'] is None
    clean_cache()
    old=snapshot()
    old['generated_at']=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()
    monkeypatch.setattr(planner,'read_feed',lambda:old)
    assert planner.planner_snapshot()['status']=='stale'


def test_feed_rejects_bad_schema_unsafe_links_and_oversized_response(monkeypatch):
    payload=snapshot()
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):return json.dumps(payload).encode()[:limit]
    class Opener:
        def open(self,request,timeout):
            assert request.get_header('X-control-centre-key')==planner.PLANNER_KEY
            assert request.get_header('Cookie') is None
            assert timeout==5
            return Response()
    monkeypatch.setattr(planner,'build_opener',lambda *args:Opener())
    assert planner.read_feed()['schema_version']==1
    payload['queues']['invitation_problems']=[dict(title='Example',wedding_date='2026-10-30',access_until='2027-01-01',status='Failed',path='https://attacker.example')]
    import pytest
    with pytest.raises(ValueError):planner.read_feed()
    payload.clear()
    payload.update(snapshot())
    payload['schema_version']=99
    with pytest.raises(ValueError):planner.read_feed()
    payload.clear()
    payload.update(snapshot())
    payload['queues']={}
    with pytest.raises(ValueError):planner.read_feed()
    monkeypatch.setattr(Response,'read',lambda self,limit:b'x'*limit)
    with pytest.raises(ValueError,match='Oversize'):planner.read_feed()
