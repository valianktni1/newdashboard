from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.middleware.trustedhost import TrustedHostMiddleware


BUILD = "2026.08.20-control-centre-v1.0.0"
APP_VERSION = "1.0.0"
DATA_DIR = Path(os.getenv("DASHBOARD_DATA_DIR", "/data"))
DATABASE_PATH = DATA_DIR / "control-centre.db"
STATIC_DIR = Path(__file__).parent / "static"
COOKIE_NAME = "wbm_control_session"
COOKIE_SECURE = os.getenv("DASHBOARD_COOKIE_SECURE", "true").lower() == "true"
SESSION_HOURS = max(1, min(168, int(os.getenv("DASHBOARD_SESSION_HOURS", "12"))))
ADMIN_EMAIL = os.getenv("DASHBOARD_ADMIN_EMAIL", "mark@perfectweddingsbymark.uk").strip().lower()
ADMIN_PASSWORD = os.getenv("DASHBOARD_ADMIN_PASSWORD", "")
ALLOWED_HOSTS = [
    value.strip() for value in os.getenv(
        "DASHBOARD_ALLOWED_HOSTS",
        "dashboard.weddingsbymark.uk,192.168.24.10,localhost,127.0.0.1",
    ).split(",") if value.strip()
]

PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
DB_LOCK = threading.RLock()
RATE_LOCK = threading.Lock()
LOGIN_ATTEMPTS: dict[str, list[datetime]] = {}


DEFAULT_SETTINGS = {
    "dashboard_title": "Weddings By Mark Control Centre",
    "dashboard_subtitle": "Every part of the business, one click away.",
    "greeting_name": "Mark",
}

DEFAULT_LINKS = [
    ("Booking System", "https://booking.weddingsbymark.uk", "Bookings, enquiries, quotes and payments", "Business", "📅", "#167a70", 1, 1),
    ("Accounts", "https://accounts2026.weddingsbymark.uk", "Income, expenses, invoices and filing", "Business", "£", "#9a6a2f", 2, 1),
    ("Client Galleries", "https://weddingsbymark.uk", "Wedding galleries, downloads and favourites", "Clients", "♡", "#b45f74", 3, 1),
    ("Studio Ninja", "https://app.studioninja.co", "Legacy weddings and client records", "Business", "🥷", "#6750a4", 4, 0),
    ("Google Calendar", "https://calendar.google.com", "Wedding diary and synced bookings", "Business", "31", "#3975d4", 5, 0),
    ("Website Admin", "https://perfectweddingsbymark.uk/wp-admin/", "Edit the Weddings By Mark website", "Marketing", "W", "#315d72", 6, 0),
    ("Nginx Proxy Manager", "http://192.168.24.10:30020", "Domains, certificates and proxy hosts", "Server", "⇄", "#e5903b", 7, 1),
    ("Dockge", "http://192.168.24.10:31014", "Docker Compose applications", "Server", "▦", "#2e8064", 8, 1),
    ("TrueNAS", "http://192.168.24.10:85", "Storage, datasets, apps and system health", "Server", "◈", "#28628f", 9, 1),
    ("Ivory Digital", "https://ivorydigital.uk", "Ivory Digital website and services", "Marketing", "ID", "#34343b", 10, 0),
    ("Outreach Manager", "https://outreach.ivorydigital.uk", "Leads, campaigns and follow-ups", "Marketing", "✦", "#7b6039", 11, 0),
    ("StudioApp", "https://studioapp.uk", "Photographer gallery platform", "Clients", "S", "#bb4f55", 12, 0),
]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def initialise_database() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with DB_LOCK, connect() as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                admin_id INTEGER NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dashboard_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'Other',
                icon TEXT NOT NULL DEFAULT '↗',
                accent TEXT NOT NULL DEFAULT '#167a70',
                sort_order INTEGER NOT NULL DEFAULT 0,
                pinned INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                open_new_tab INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        admin = db.execute("SELECT id FROM admins LIMIT 1").fetchone()
        now = utcnow().isoformat()
        if not admin:
            if len(ADMIN_PASSWORD) < 12 or ADMIN_PASSWORD.startswith("CHANGE-THIS"):
                raise RuntimeError(
                    "Set DASHBOARD_ADMIN_PASSWORD in .env to a new password of at least 12 characters"
                )
            db.execute(
                "INSERT INTO admins(email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (ADMIN_EMAIL, PASSWORD_HASHER.hash(ADMIN_PASSWORD), now, now),
            )
        for key, value in DEFAULT_SETTINGS.items():
            db.execute(
                "INSERT OR IGNORE INTO dashboard_settings(key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, now),
            )
        if db.execute("SELECT COUNT(*) FROM links").fetchone()[0] == 0:
            db.executemany(
                """INSERT INTO links(name, url, description, category, icon, accent,
                   sort_order, pinned, active, open_new_tab, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?)""",
                [(*row, now, now) for row in DEFAULT_LINKS],
            )
            db.execute(
                "INSERT INTO activity(action, detail, created_at) VALUES (?, ?, ?)",
                ("dashboard_created", "Control Centre created with editable starter shortcuts", now),
            )
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        db.commit()


def audit(db: sqlite3.Connection, action: str, detail: str) -> None:
    db.execute(
        "INSERT INTO activity(action, detail, created_at) VALUES (?, ?, ?)",
        (action, detail[:300], utcnow().isoformat()),
    )


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_url(value: str) -> str:
    cleaned = value.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Enter a complete http:// or https:// address")
    return cleaned


def verify_accent(value: str) -> str:
    cleaned = value.strip().lower()
    if not re.fullmatch(r"#[0-9a-f]{6}", cleaned):
        raise ValueError("Choose a valid six-digit colour")
    return cleaned


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginIn(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class LinkIn(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    url: str = Field(min_length=8, max_length=500)
    description: str = Field(default="", max_length=180)
    category: str = Field(default="Other", min_length=1, max_length=40)
    icon: str = Field(default="↗", min_length=1, max_length=12)
    accent: str = Field(default="#167a70", min_length=7, max_length=7)
    pinned: bool = False
    active: bool = True
    open_new_tab: bool = True

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        return verify_url(value)

    @field_validator("accent")
    @classmethod
    def valid_accent(cls, value: str) -> str:
        return verify_accent(value)


class LinkPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    url: str | None = Field(default=None, min_length=8, max_length=500)
    description: str | None = Field(default=None, max_length=180)
    category: str | None = Field(default=None, min_length=1, max_length=40)
    icon: str | None = Field(default=None, min_length=1, max_length=12)
    accent: str | None = Field(default=None, min_length=7, max_length=7)
    pinned: bool | None = None
    active: bool | None = None
    open_new_tab: bool | None = None

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str | None) -> str | None:
        return verify_url(value) if value is not None else None

    @field_validator("accent")
    @classmethod
    def valid_accent(cls, value: str | None) -> str | None:
        return verify_accent(value) if value is not None else None


class ReorderIn(StrictModel):
    link_ids: list[int] = Field(min_length=1, max_length=500)


class SettingsIn(StrictModel):
    dashboard_title: str = Field(min_length=1, max_length=80)
    dashboard_subtitle: str = Field(min_length=1, max_length=180)
    greeting_name: str = Field(min_length=1, max_length=40)


class PasswordIn(StrictModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


def row_link(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "name": row["name"], "url": row["url"],
        "description": row["description"], "category": row["category"],
        "icon": row["icon"], "accent": row["accent"],
        "sort_order": row["sort_order"], "pinned": bool(row["pinned"]),
        "active": bool(row["active"]), "open_new_tab": bool(row["open_new_tab"]),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def settings_from(db: sqlite3.Connection) -> dict[str, str]:
    values = dict(DEFAULT_SETTINGS)
    values.update({row["key"]: row["value"] for row in db.execute(
        "SELECT key, value FROM dashboard_settings"
    )})
    return values


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    parsed = urlparse(origin)
    if parsed.netloc.lower() != request.headers.get("host", "").lower():
        raise HTTPException(status_code=403, detail="Request origin was not accepted")


def current_admin(session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None) -> dict:
    if not session:
        raise HTTPException(status_code=401, detail="Please sign in")
    now = utcnow().isoformat()
    with DB_LOCK, connect() as db:
        row = db.execute(
            """SELECT admins.id, admins.email FROM sessions
               JOIN admins ON admins.id = sessions.admin_id
               WHERE sessions.token_hash = ? AND sessions.expires_at > ?""",
            (token_digest(session), now),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Your session has expired")
    return {"id": row["id"], "email": row["email"]}


def enforce_login_rate(ip: str) -> None:
    now = utcnow()
    cutoff = now - timedelta(minutes=15)
    with RATE_LOCK:
        recent = [item for item in LOGIN_ATTEMPTS.get(ip, []) if item > cutoff]
        LOGIN_ATTEMPTS[ip] = recent
        if len(recent) >= 8:
            raise HTTPException(status_code=429, detail="Too many attempts. Please wait 15 minutes.")


def record_failed_login(ip: str) -> None:
    with RATE_LOCK:
        LOGIN_ATTEMPTS.setdefault(ip, []).append(utcnow())


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialise_database()
    yield


app = FastAPI(
    title="Weddings By Mark Control Centre",
    version=APP_VERSION,
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS or ["*"])
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "newdashboard", "version": APP_VERSION, "build": BUILD}


@app.post("/api/auth/login")
def login(payload: LoginIn, request: Request, response: Response):
    require_same_origin(request)
    ip = request.client.host if request.client else "unknown"
    enforce_login_rate(ip)
    with DB_LOCK, connect() as db:
        admin = db.execute("SELECT * FROM admins WHERE email = ?", (payload.email.lower(),)).fetchone()
        valid = False
        if admin:
            try:
                valid = PASSWORD_HASHER.verify(admin["password_hash"], payload.password)
            except VerifyMismatchError:
                valid = False
        if not valid:
            record_failed_login(ip)
            raise HTTPException(status_code=401, detail="Email or password is incorrect")
        with RATE_LOCK:
            LOGIN_ATTEMPTS.pop(ip, None)
        token = secrets.token_urlsafe(48)
        now = utcnow()
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(),))
        db.execute(
            "INSERT INTO sessions(token_hash, admin_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token_digest(token), admin["id"], now.isoformat(),
             (now + timedelta(hours=SESSION_HOURS)).isoformat()),
        )
        audit(db, "login", "Control Centre sign-in")
        db.commit()
    response.set_cookie(
        COOKIE_NAME, token, max_age=SESSION_HOURS * 3600, httponly=True,
        secure=COOKIE_SECURE, samesite="strict", path="/",
    )
    return {"ok": True, "email": admin["email"]}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response,
           session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
           _: dict = Depends(current_admin)):
    require_same_origin(request)
    if session:
        with DB_LOCK, connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_digest(session),))
            db.commit()
    response.delete_cookie(COOKIE_NAME, path="/", secure=COOKIE_SECURE, samesite="strict")
    return {"ok": True}


@app.get("/api/me")
def me(admin: dict = Depends(current_admin)):
    return admin


@app.get("/api/dashboard")
def dashboard(_: dict = Depends(current_admin)):
    with DB_LOCK, connect() as db:
        links = [row_link(row) for row in db.execute(
            "SELECT * FROM links ORDER BY pinned DESC, sort_order, name COLLATE NOCASE"
        )]
        return {"settings": settings_from(db), "links": links, "build": BUILD}


@app.post("/api/links", status_code=201)
def create_link(payload: LinkIn, request: Request, _: dict = Depends(current_admin)):
    require_same_origin(request)
    now = utcnow().isoformat()
    with DB_LOCK, connect() as db:
        order = db.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM links").fetchone()[0]
        cursor = db.execute(
            """INSERT INTO links(name, url, description, category, icon, accent, sort_order,
               pinned, active, open_new_tab, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (payload.name, payload.url, payload.description, payload.category, payload.icon,
             payload.accent, order, int(payload.pinned), int(payload.active),
             int(payload.open_new_tab), now, now),
        )
        audit(db, "link_added", f"Added shortcut: {payload.name}")
        db.commit()
        row = db.execute("SELECT * FROM links WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return row_link(row)


@app.patch("/api/links/{link_id}")
def update_link(link_id: int, payload: LinkPatch, request: Request,
                _: dict = Depends(current_admin)):
    require_same_origin(request)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing was changed")
    with DB_LOCK, connect() as db:
        existing = db.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Shortcut not found")
        changes["updated_at"] = utcnow().isoformat()
        columns = []
        values = []
        for key, value in changes.items():
            columns.append(f"{key} = ?")
            values.append(int(value) if key in {"pinned", "active", "open_new_tab"} else value)
        values.append(link_id)
        db.execute(f"UPDATE links SET {', '.join(columns)} WHERE id = ?", values)
        updated_name = changes.get("name", existing["name"])
        audit(db, "link_updated", f"Updated shortcut: {updated_name}")
        db.commit()
        row = db.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()
    return row_link(row)


@app.delete("/api/links/{link_id}", status_code=204)
def delete_link(link_id: int, request: Request, _: dict = Depends(current_admin)):
    require_same_origin(request)
    with DB_LOCK, connect() as db:
        row = db.execute("SELECT name FROM links WHERE id = ?", (link_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Shortcut not found")
        db.execute("DELETE FROM links WHERE id = ?", (link_id,))
        audit(db, "link_deleted", f"Deleted shortcut: {row['name']}")
        db.commit()
    return Response(status_code=204)


@app.put("/api/links/reorder")
def reorder_links(payload: ReorderIn, request: Request, _: dict = Depends(current_admin)):
    require_same_origin(request)
    if len(payload.link_ids) != len(set(payload.link_ids)):
        raise HTTPException(status_code=400, detail="A shortcut was listed more than once")
    with DB_LOCK, connect() as db:
        existing = {row[0] for row in db.execute("SELECT id FROM links")}
        if set(payload.link_ids) != existing:
            raise HTTPException(status_code=400, detail="The shortcut list has changed; please refresh")
        for order, link_id in enumerate(payload.link_ids, start=1):
            db.execute("UPDATE links SET sort_order = ?, updated_at = ? WHERE id = ?",
                       (order, utcnow().isoformat(), link_id))
        audit(db, "links_reordered", "Reordered dashboard shortcuts")
        db.commit()
    return {"ok": True}


@app.patch("/api/settings")
def update_settings(payload: SettingsIn, request: Request, _: dict = Depends(current_admin)):
    require_same_origin(request)
    now = utcnow().isoformat()
    with DB_LOCK, connect() as db:
        for key, value in payload.model_dump().items():
            db.execute(
                """INSERT INTO dashboard_settings(key, value, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
                (key, value, now),
            )
        audit(db, "settings_updated", "Updated Control Centre heading and greeting")
        db.commit()
        return settings_from(db)


@app.post("/api/admin/password")
def change_password(payload: PasswordIn, request: Request,
                    admin: dict = Depends(current_admin)):
    require_same_origin(request)
    with DB_LOCK, connect() as db:
        row = db.execute("SELECT password_hash FROM admins WHERE id = ?", (admin["id"],)).fetchone()
        try:
            PASSWORD_HASHER.verify(row["password_hash"], payload.current_password)
        except VerifyMismatchError as exc:
            raise HTTPException(status_code=400, detail="Current password is incorrect") from exc
        if payload.current_password == payload.new_password:
            raise HTTPException(status_code=400, detail="Choose a different new password")
        db.execute("UPDATE admins SET password_hash = ?, updated_at = ? WHERE id = ?",
                   (PASSWORD_HASHER.hash(payload.new_password), utcnow().isoformat(), admin["id"]))
        db.execute("DELETE FROM sessions WHERE admin_id = ?", (admin["id"],))
        audit(db, "password_changed", "Control Centre password changed; sessions revoked")
        db.commit()
    response = JSONResponse({"ok": True, "signed_out": True})
    response.delete_cookie(COOKIE_NAME, path="/", secure=COOKIE_SECURE, samesite="strict")
    return response


@app.get("/api/activity")
def recent_activity(limit: int = 10, _: dict = Depends(current_admin)):
    limit = max(1, min(50, limit))
    with DB_LOCK, connect() as db:
        rows = db.execute(
            "SELECT id, action, detail, created_at FROM activity ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/export")
def export_configuration(_: dict = Depends(current_admin)):
    with DB_LOCK, connect() as db:
        payload = {
            "format": "Weddings By Mark Control Centre configuration",
            "version": 1,
            "exported_at": utcnow().isoformat(),
            "build": BUILD,
            "settings": settings_from(db),
            "links": [row_link(row) for row in db.execute(
                "SELECT * FROM links ORDER BY sort_order, id"
            )],
        }
    filename = f"WBM-Control-Centre-{utcnow().strftime('%Y%m%d-%H%M%S')}.json"
    return JSONResponse(
        payload,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/favicon.svg", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.exception_handler(404)
async def spa_fallback(request: Request, exc: HTTPException):
    if request.method == "GET" and not request.url.path.startswith("/api/"):
        return FileResponse(STATIC_DIR / "index.html")
    return JSONResponse({"detail": exc.detail}, status_code=404)
