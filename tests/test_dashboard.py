import os
import shutil
from pathlib import Path


TEST_ROOT = Path(__file__).parent
DATA_DIR = TEST_ROOT / "data"
os.environ["DASHBOARD_DATA_DIR"] = str(DATA_DIR)
os.environ["DASHBOARD_ADMIN_EMAIL"] = "mark@example.com"
os.environ["DASHBOARD_ADMIN_PASSWORD"] = "Secure-Dashboard-Test-Password-123!"
os.environ["DASHBOARD_COOKIE_SECURE"] = "false"
os.environ["DASHBOARD_ALLOWED_HOSTS"] = "testserver,localhost,127.0.0.1"

from fastapi.testclient import TestClient

from app.main import BUILD, app


def reset_data():
    shutil.rmtree(DATA_DIR, ignore_errors=True)


def login(client: TestClient, password: str = "Secure-Dashboard-Test-Password-123!"):
    return client.post("/api/auth/login", json={"email": "mark@example.com", "password": password})


def test_complete_control_centre_flow_is_private_editable_and_exportable():
    reset_data()
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {
            "status": "ok", "service": "newdashboard", "version": "1.0.0", "build": BUILD,
        }
        assert client.get("/api/dashboard").status_code == 401
        assert login(client, "wrong-password").status_code == 401
        signed_in = login(client)
        assert signed_in.status_code == 200
        assert signed_in.cookies.get("wbm_control_session")

        dashboard = client.get("/api/dashboard").json()
        assert dashboard["settings"]["greeting_name"] == "Mark"
        assert len(dashboard["links"]) == 12
        urls = {item["url"] for item in dashboard["links"]}
        assert "https://booking.weddingsbymark.uk" in urls
        assert "https://accounts2026.weddingsbymark.uk" in urls
        assert "https://weddingsbymark.uk" in urls
        assert "https://app.studioninja.co" in urls
        assert "http://192.168.24.10:30020" in urls

        unsafe = client.post("/api/links", json={
            "name": "Unsafe", "url": "javascript:alert(1)", "description": "No",
            "category": "Other", "icon": "X", "accent": "#123456",
        })
        assert unsafe.status_code == 422

        created = client.post("/api/links", json={
            "name": "New Service", "url": "https://service.example.com/dashboard",
            "description": "A future business service", "category": "Future", "icon": "N",
            "accent": "#345678", "pinned": True, "active": True, "open_new_tab": False,
        })
        assert created.status_code == 201
        link = created.json()
        assert link["name"] == "New Service"
        assert link["pinned"] is True
        assert link["open_new_tab"] is False

        changed = client.patch(f"/api/links/{link['id']}", json={
            "name": "Changed Service", "url": "http://192.168.24.10:39999",
            "description": "Changed safely", "category": "Server", "icon": "CS",
            "accent": "#654321", "pinned": False, "active": False,
            "open_new_tab": True,
        })
        assert changed.status_code == 200
        assert changed.json()["name"] == "Changed Service"
        assert changed.json()["active"] is False

        ids = [item["id"] for item in client.get("/api/dashboard").json()["links"]]
        reordered = client.put("/api/links/reorder", json={"link_ids": list(reversed(ids))})
        assert reordered.status_code == 200

        settings = client.patch("/api/settings", json={
            "dashboard_title": "Mark's New Control Room",
            "dashboard_subtitle": "Everything important, ready when I need it.",
            "greeting_name": "Mark",
        })
        assert settings.status_code == 200
        assert settings.json()["dashboard_title"] == "Mark's New Control Room"

        activity = client.get("/api/activity?limit=3")
        assert activity.status_code == 200
        assert len(activity.json()) == 3
        assert activity.json()[0]["action"] == "settings_updated"

        exported = client.get("/api/export")
        assert exported.status_code == 200
        assert exported.headers["content-disposition"].startswith("attachment")
        assert exported.json()["format"] == "Weddings By Mark Control Centre configuration"
        exported_text = exported.text
        assert "password_hash" not in exported_text
        assert "wbm_control_session" not in exported_text
        assert "Secure-Dashboard-Test-Password" not in exported_text

        removed = client.delete(f"/api/links/{link['id']}")
        assert removed.status_code == 204
        assert all(item["id"] != link["id"] for item in client.get("/api/dashboard").json()["links"])

        password = client.post("/api/admin/password", json={
            "current_password": "Secure-Dashboard-Test-Password-123!",
            "new_password": "New-Secure-Dashboard-Password-456!",
        })
        assert password.status_code == 200
        assert client.get("/api/dashboard").status_code == 401
        assert login(client).status_code == 401
        assert login(client, "New-Secure-Dashboard-Password-456!").status_code == 200


def test_frontend_contains_responsive_editor_search_and_future_ready_activity_api():
    root = Path(__file__).parents[1]
    html = (root / "app" / "static" / "index.html").read_text()
    css = (root / "app" / "static" / "app.css").read_text()
    javascript = (root / "app" / "static" / "app.js").read_text()
    compose = (root / "compose.yaml").read_text()

    assert "Edit dashboard" in html
    assert "Add shortcut" in html
    assert "mobile-nav" in html
    assert "noindex,nofollow,noarchive" in html
    assert "@media(max-width:700px)" in css
    assert "openLinkModal" in javascript
    assert 'api("/api/links/reorder"' in javascript
    assert "/api/activity" in (root / "app" / "main.py").read_text()
    assert '"30046:8080"' in compose
    assert "/mnt/apps/newdashboard:/data" in compose
    assert "no-new-privileges:true" in compose
