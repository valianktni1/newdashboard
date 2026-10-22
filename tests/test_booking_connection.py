from datetime import datetime, timezone, timedelta
from urllib.error import HTTPError
import json
import os
import subprocess
import sys

from fastapi.testclient import TestClient
from test_dashboard import app, login, reset_data
from app import booking_connection as booking


def snapshot():
    return dict(schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(),
                business_date='2026-10-22', currency='GBP', payment_amount_basis='outstanding_invoice_balance',
                queues={key:dict(count=0,total_amount_pence=0,items=[]) for key in booking.QUEUE_KEYS}, upcoming_weddings=[])


def clean_cache():
    booking.CACHE.update(attempted=None,data=None,error=None,checked_at=None)


def test_installer_can_import_snapshot_first_in_a_fresh_process():
    environment={**os.environ,'DASHBOARD_BOOKING_KEY':''}
    code=('from app.booking_connection import booking_snapshot; '
          'assert booking_snapshot()["status"] == "not_connected"; '
          'from app.main import app; '
          'assert any(route.path == "/api/booking/overview" for route in app.routes); '
          'assert any(route.path == "/api/booking/refresh" for route in app.routes)')
    result=subprocess.run([sys.executable,'-c',code],env=environment,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr


def test_booking_is_private_opt_in_cached_and_never_returns_key(monkeypatch):
    reset_data()
    clean_cache()
    monkeypatch.setattr(booking, 'BOOKING_KEY', '')
    calls=[]
    def read():
        calls.append(True)
        return snapshot()
    monkeypatch.setattr(booking, 'read_feed', read)
    with TestClient(app) as client:
        assert client.get('/api/booking/overview').status_code == 401
        assert client.post('/api/booking/refresh').status_code == 401
        login(client)
        assert client.get('/api/booking/overview').json()['status'] == 'not_connected'
        assert calls == []
        monkeypatch.setattr(booking, 'BOOKING_KEY', 'private-test-key-not-for-browser-'*2)
        response=client.get('/api/booking/overview')
        assert response.json()['status'] == 'connected'
        assert response.headers['cache-control'] == 'private, no-store'
        assert booking.BOOKING_KEY not in response.text
        client.get('/api/booking/overview')
        client.post('/api/booking/refresh')
        assert len(calls) == 1
        assert client.post('/api/booking/refresh',headers={'Origin':'https://attacker.example'}).status_code == 403


def test_connection_failures_keep_last_result_and_label_it_stale(monkeypatch):
    clean_cache()
    monkeypatch.setattr(booking,'BOOKING_KEY','x'*48)
    monkeypatch.setattr(booking,'read_feed',snapshot)
    assert booking.booking_snapshot()['status']=='connected'
    booking.CACHE['attempted']-=61
    def fail():
        raise HTTPError(booking.BOOKING_URL,401,'rejected',{},None)
    monkeypatch.setattr(booking,'read_feed',fail)
    result=booking.booking_snapshot()
    assert result['status']=='stale'
    assert result['data'] is not None
    assert 'rejected' in result['message']
    clean_cache()
    result=booking.booking_snapshot()
    assert result['status']=='error' and result['data'] is None
    clean_cache()
    old=snapshot()
    old['generated_at']=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()
    monkeypatch.setattr(booking,'read_feed',lambda:old)
    assert booking.booking_snapshot()['status']=='stale'


def test_feed_rejects_bad_schema_unsafe_links_and_oversized_response(monkeypatch):
    payload=snapshot()
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self,limit):return json.dumps(payload).encode()[:limit]
    class Opener:
        def open(self,request,timeout):
            assert request.get_header('X-control-centre-key')==booking.BOOKING_KEY
            assert request.get_header('Cookie') is None
            assert timeout==5
            return Response()
    monkeypatch.setattr(booking,'build_opener',lambda *args:Opener())
    assert booking.read_feed()['schema_version']==1
    payload['upcoming_weddings']=[dict(title='Example',event_date='2026-10-30',path='https://attacker.example')]
    import pytest
    with pytest.raises(ValueError):booking.read_feed()
    payload.clear()
    payload.update(snapshot())
    payload['schema_version']=99
    with pytest.raises(ValueError):booking.read_feed()
    payload.clear()
    payload.update(snapshot())
    payload['queues']={}
    with pytest.raises(ValueError):booking.read_feed()
    monkeypatch.setattr(Response,'read',lambda self,limit:b'x'*limit)
    with pytest.raises(ValueError,match='Oversize'):booking.read_feed()
