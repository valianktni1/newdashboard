"""Daily workspace data and bounded, administrator-triggered availability checks."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import json
import os
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request as URLRequest, build_opener

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import Field, field_validator
from typing import Literal

from .main import StrictModel, audit, connect, current_admin, DB_LOCK, require_same_origin, utcnow, verify_url, DEFAULT_LINKS

router = APIRouter(prefix="/api")
WORKSPACES = ("Weddings By Mark", "Ivory Digital", "Marketing", "Accounts", "Systems", "Other")
CHECK_LOCK = threading.Lock()
# Only these exact addresses are checked. Editing a shortcut cannot expand this list.
CHECK_URLS = frozenset([item[1] for item in DEFAULT_LINKS] + ["https://planner.ivorydigital.uk"])
extra_urls = json.loads(os.getenv("DASHBOARD_CHECK_URLS", "[]"))
if not isinstance(extra_urls, list) or any(not isinstance(url, str) for url in extra_urls):
    raise ValueError("DASHBOARD_CHECK_URLS must be a JSON array of complete URLs")
CHECK_URLS = CHECK_URLS | frozenset(verify_url(url) for url in extra_urls)


def initialise_workspace(db, now):
    columns = {row[1] for row in db.execute("PRAGMA table_info(links)")}
    if "workspace" not in columns:
        db.execute("ALTER TABLE links ADD COLUMN workspace TEXT NOT NULL DEFAULT 'Other'")
        for row in db.execute("SELECT id, name, category, url FROM links").fetchall():
            name, category, url = row["name"].lower(), row["category"].lower(), row["url"].lower()
            area = "Other"
            if category == "server":
                area = "Systems"
            elif "account" in name:
                area = "Accounts"
            elif "ivorydigital" in url or "studioapp" in url or "outreach" in name:
                area = "Ivory Digital"
            elif category == "marketing":
                area = "Marketing"
            elif category in {"business", "clients"}:
                area = "Weddings By Mark"
            db.execute("UPDATE links SET workspace = ? WHERE id = ?", (area, row["id"]))
    # A recorded migration respects later deletion, hiding and renaming of this shortcut.
    if not db.execute("SELECT 1 FROM dashboard_settings WHERE key = '_workspace_v2'").fetchone():
        if not db.execute("SELECT 1 FROM links WHERE rtrim(url, '/') = ?", ("https://planner.ivorydigital.uk",)).fetchone():
            db.execute("""INSERT INTO links(name,url,description,category,icon,accent,sort_order,
                       pinned,active,open_new_tab,created_at,updated_at,workspace)
                       VALUES (?,?,?,?,?,?,(SELECT COALESCE(MAX(sort_order),0)+1 FROM links),1,1,1,?,?,?)""",
                       ("Couples' Wedding Planner", "https://planner.ivorydigital.uk",
                        "Couples, invitations and wedding planning", "Clients", "WP", "#9a6a2f", now, now, "Weddings By Mark"))
        db.execute("INSERT INTO dashboard_settings(key,value,updated_at) VALUES ('_workspace_v2','1',?)", (now,))
    db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            workspace TEXT NOT NULL DEFAULT 'Weddings By Mark',
            due_date TEXT,
            priority TEXT NOT NULL DEFAULT 'normal',
            url TEXT NOT NULL DEFAULT '',
            completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS service_checks (
            link_id INTEGER PRIMARY KEY REFERENCES links(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            status TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            response_ms INTEGER,
            http_status INTEGER
        );
    """)


class TaskIn(StrictModel):
    title: str = Field(min_length=1, max_length=180)
    workspace: Literal["Weddings By Mark", "Ivory Digital", "Marketing", "Accounts", "Systems", "Other"] = "Weddings By Mark"
    due_date: date | None = None
    priority: Literal["normal", "high"] = "normal"
    url: str = Field(default="", max_length=500)

    @field_validator("url")
    @classmethod
    def valid_task_url(cls, value):
        return verify_url(value) if value else ""


class TaskState(StrictModel):
    completed: bool


def task_dict(row):
    result = dict(row)
    result["completed"] = bool(result["completed"])
    return result


@router.get("/tasks")
def tasks(_: dict = Depends(current_admin)):
    with DB_LOCK, connect() as db:
        return [task_dict(row) for row in db.execute(
            "SELECT * FROM tasks ORDER BY completed, CASE WHEN due_date IS NULL THEN 1 ELSE 0 END, due_date, CASE priority WHEN 'high' THEN 0 ELSE 1 END, id DESC")]


@router.post("/tasks", status_code=201)
def create_task(payload: TaskIn, request: Request, _: dict = Depends(current_admin)):
    require_same_origin(request)
    now = utcnow().isoformat()
    with DB_LOCK, connect() as db:
        cursor = db.execute("INSERT INTO tasks(title,workspace,due_date,priority,url,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                            (payload.title, payload.workspace, payload.due_date.isoformat() if payload.due_date else None,
                             payload.priority, payload.url, now, now))
        audit(db, "task_added", f"Added task: {payload.title}")
        db.commit()
        return task_dict(db.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone())


@router.put("/tasks/{task_id}")
def update_task(task_id: int, payload: TaskIn, request: Request, _: dict = Depends(current_admin)):
    require_same_origin(request)
    with DB_LOCK, connect() as db:
        if not db.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone():
            raise HTTPException(404, "Task not found")
        db.execute("UPDATE tasks SET title=?, workspace=?, due_date=?, priority=?, url=?, updated_at=? WHERE id=?",
                   (payload.title, payload.workspace, payload.due_date.isoformat() if payload.due_date else None,
                    payload.priority, payload.url, utcnow().isoformat(), task_id))
        audit(db, "task_updated", f"Updated task: {payload.title}")
        db.commit()
        return task_dict(db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())


@router.post("/tasks/{task_id}/complete")
def complete_task(task_id: int, payload: TaskState, request: Request, _: dict = Depends(current_admin)):
    require_same_origin(request)
    with DB_LOCK, connect() as db:
        if not db.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone():
            raise HTTPException(404, "Task not found")
        db.execute("UPDATE tasks SET completed=?,updated_at=? WHERE id=?", (int(payload.completed), utcnow().isoformat(), task_id))
        audit(db, "task_completed" if payload.completed else "task_reopened", f"Task {task_id}")
        db.commit()
    return {"ok": True}


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, request: Request, _: dict = Depends(current_admin)):
    require_same_origin(request)
    with DB_LOCK, connect() as db:
        if not db.execute("DELETE FROM tasks WHERE id=?", (task_id,)).rowcount:
            raise HTTPException(404, "Task not found")
        audit(db, "task_deleted", f"Deleted task {task_id}")
        db.commit()
    return Response(status_code=204)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_service(link):
    start = time.monotonic()
    code = None
    try:
        # Never follow redirects, use environment proxies, read page bodies or send cookies.
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(URLRequest(link["url"], headers={"User-Agent": "WBM-Control-Centre/1.1"}), timeout=3) as response:
            code = response.status
    except HTTPError as exc:
        code = exc.code
        exc.close()
    except (URLError, OSError, ValueError):
        pass
    status = "unavailable"
    if code is not None:
        if 200 <= code < 300:
            status = "reachable"
        elif 300 <= code < 400:
            status = "redirected"
        elif code in (401, 403):
            status = "restricted"
        else:
            status = "http_error"
    return {"link_id": link["id"], "url": link["url"], "status": status,
            "checked_at": utcnow().isoformat(), "response_ms": round((time.monotonic()-start)*1000), "http_status": code}


@router.get("/services")
def services(_: dict = Depends(current_admin)):
    with DB_LOCK, connect() as db:
        return [dict(row) for row in db.execute("SELECT c.* FROM service_checks c JOIN links l ON l.id=c.link_id AND l.url=c.url")]


@router.post("/services/check")
def check_services(request: Request, _: dict = Depends(current_admin)):
    require_same_origin(request)
    if not CHECK_LOCK.acquire(blocking=False):
        raise HTTPException(409, "Service checks are already running")
    try:
        with DB_LOCK, connect() as db:
            rows = [dict(row) for row in db.execute("SELECT id,url FROM links WHERE active=1")]
            recent = {row["link_id"]: dict(row) for row in db.execute("SELECT * FROM service_checks")}
        now = utcnow()
        pending = [row for row in rows if row["url"] in CHECK_URLS and not (
            row["id"] in recent and recent[row["id"]]["url"] == row["url"] and
            (now - datetime.fromisoformat(recent[row["id"]]["checked_at"])).total_seconds() < 60)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(check_service, pending))
        with DB_LOCK, connect() as db:
            for result in results:
                db.execute("""INSERT INTO service_checks(link_id,url,status,checked_at,response_ms,http_status)
                    SELECT :link_id,:url,:status,:checked_at,:response_ms,:http_status
                    WHERE EXISTS (SELECT 1 FROM links WHERE id=:link_id AND url=:url)
                    ON CONFLICT(link_id) DO UPDATE SET url=excluded.url,status=excluded.status,
                    checked_at=excluded.checked_at,response_ms=excluded.response_ms,http_status=excluded.http_status""", result)
            db.commit()
        return services(_)
    finally:
        CHECK_LOCK.release()
