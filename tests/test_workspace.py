import sqlite3
from urllib.error import HTTPError

from fastapi.testclient import TestClient
from test_dashboard import app, login, reset_data, DATA_DIR
from app import workspace


def test_tasks_are_private_persistent_validated_and_exported():
    reset_data()
    with TestClient(app) as client:
        assert client.get('/api/tasks').status_code == 401
        assert client.post('/api/tasks', json={'title': 'Private'}).status_code == 401
        assert client.get('/api/services').status_code == 401
        assert client.post('/api/services/check').status_code == 401
        login(client)
        payload = dict(title='Follow up wedding quote', due_date='2026-10-22', priority='high', workspace='Weddings By Mark', url='https://booking.weddingsbymark.uk')
        assert client.post('/api/tasks', json=payload, headers={'Origin': 'https://attacker.example'}).status_code == 403
        assert client.post('/api/tasks', json={**payload, 'url': 'javascript:alert(1)'}).status_code == 422
        assert client.post('/api/tasks', json={**payload, 'due_date': '2026-02-30'}).status_code == 422
        assert client.post('/api/tasks', json={**payload, 'workspace': 'Invalid'}).status_code == 422
        task = client.post('/api/tasks', json=payload).json()
        assert task['completed'] is False
        task_id = task['id']
        assert client.put(f'/api/tasks/{task_id}', json={**payload, 'title': 'Updated follow-up'}).status_code == 200
        assert client.post(f'/api/tasks/{task_id}/complete', json={'completed': True}).status_code == 200
        assert client.get('/api/tasks').json()[0]['completed'] is True
        assert client.get('/api/export').json()['tasks'][0]['title'] == 'Updated follow-up'
    with TestClient(app) as client:
        login(client)
        assert client.get('/api/tasks').json()[0]['completed'] is True
        assert client.post(f'/api/tasks/{task_id}/complete', json={'completed': False}).status_code == 200
        assert client.delete(f'/api/tasks/{task_id}').status_code == 204
        assert client.get('/api/tasks').json() == []
        assert client.put('/api/tasks/99999', json=payload).status_code == 404


def test_upgrade_preserves_existing_links_settings_and_does_not_readd_deleted_planner():
    reset_data()
    DATA_DIR.mkdir(parents=True)
    db = sqlite3.connect(DATA_DIR/'control-centre.db')
    db.executescript('''CREATE TABLE links (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'Other',
        icon TEXT NOT NULL DEFAULT 'X', accent TEXT NOT NULL DEFAULT '#167a70',
        sort_order INTEGER NOT NULL DEFAULT 0, pinned INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1, open_new_tab INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO links(id,name,url,category,sort_order,pinned,active,open_new_tab,created_at,updated_at)
        VALUES(7,'My custom booking','https://custom.example','Business',91,0,0,0,'original','original');
        CREATE TABLE dashboard_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL,updated_at TEXT NOT NULL);
        INSERT INTO dashboard_settings VALUES('dashboard_title','My custom heading','original');''')
    db.commit()
    db.close()
    with TestClient(app) as client:
        login(client)
        data = client.get('/api/dashboard').json()
        assert data['settings']['dashboard_title'] == 'My custom heading'
        original = next(link for link in data['links'] if link['id'] == 7)
        assert original['name'] == 'My custom booking'
        assert original['url'] == 'https://custom.example'
        assert original['sort_order'] == 91
        assert original['active'] is False and original['pinned'] is False
        assert original['open_new_tab'] is False
        assert original['created_at'] == 'original'
        assert original['workspace'] == 'Weddings By Mark'
        planner = next(link for link in data['links'] if link['url'] == 'https://planner.ivorydigital.uk')
        assert client.delete(f"/api/links/{planner['id']}").status_code == 204
    with TestClient(app) as client:
        login(client)
        assert len(client.get('/api/dashboard').json()['links']) == 1


def test_checks_only_probe_allowed_addresses_cache_results_and_discard_changed_urls(monkeypatch):
    reset_data()
    probes = []
    def probe(link):
        probes.append(link['url'])
        return dict(link_id=link['id'], url=link['url'], status='reachable', checked_at=workspace.utcnow().isoformat(), response_ms=12, http_status=200)
    monkeypatch.setattr(workspace, 'check_service', probe)
    with TestClient(app) as client:
        login(client)
        assert client.get('/api/services').json() == []
        custom = client.post('/api/links', json=dict(name='Unapproved',url='http://169.254.169.254/latest/meta-data/')).json()
        assert client.post('/api/services/check', headers={'Origin':'https://attacker.example'}).status_code == 403
        first = client.post('/api/services/check')
        assert first.status_code == 200
        assert probes and all(url in workspace.CHECK_URLS for url in probes)
        assert custom['url'] not in probes
        assert all(check['status'] == 'reachable' for check in first.json())
        count = len(probes)
        assert client.post('/api/services/check').status_code == 200
        assert len(probes) == count
        changed = first.json()[0]['link_id']
        assert client.patch(f'/api/links/{changed}', json={'url':'https://changed.example'}).status_code == 200
        assert all(check['link_id'] != changed for check in client.get('/api/services').json())
        assert client.patch(f'/api/links/{changed}', json={'workspace':None}).status_code == 422
        workspace.CHECK_LOCK.acquire()
        try:
            assert client.post('/api/services/check').status_code == 409
        finally:
            workspace.CHECK_LOCK.release()


def test_probe_labels_http_responses_and_does_not_follow_redirects(monkeypatch):
    class Opener:
        def open(self, request, timeout):
            assert timeout == 3
            assert request.get_header('Cookie') is None
            raise HTTPError(request.full_url, 302, 'Found', {'Location':'http://169.254.169.254/'}, None)
    monkeypatch.setattr(workspace, 'build_opener', lambda *args: Opener())
    result = workspace.check_service({'id':1,'url':'https://booking.weddingsbymark.uk'})
    assert result['status'] == 'redirected'
    assert result['http_status'] == 302
    assert workspace.NoRedirect().redirect_request(None,None,302,'Found',{},'http://169.254.169.254/') is None
