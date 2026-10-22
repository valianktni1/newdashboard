"""Server-side read-only planner feed. Keys never enter browser responses."""
from datetime import date, datetime, timezone
import os
from http.client import HTTPException as HTTPClientError
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request as URLRequest, ProxyHandler, build_opener, HTTPRedirectHandler

from fastapi import Depends, Request, Response
from pydantic import AwareDatetime, BaseModel, Field, ValidationError
from typing import Literal, Annotated

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

PLANNER_URL = os.getenv("DASHBOARD_PLANNER_URL", "https://planner.ivorydigital.uk").rstrip("/")
PLANNER_KEY = os.getenv("DASHBOARD_PLANNER_KEY", "")
parts = urlsplit(PLANNER_URL)
if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path:
    raise ValueError("DASHBOARD_PLANNER_URL must be a complete origin without a path or credentials")
if parts.scheme == "http" and parts.hostname not in {"127.0.0.1", "localhost", "192.168.24.10", "weddingplannercouples-web-1"}:
    raise ValueError("Use HTTPS for the planner connection outside the known local server")
QUEUE_KEYS = ("awaiting_couples", "invitation_problems", "expiring_access")
COUNT_KEYS = (*QUEUE_KEYS, "active_accounts", "active_last_seven_days")
LOCK = threading.Lock()
CACHE = {"attempted": None, "data": None, "error": None, "checked_at": None}


class Item(BaseModel):
    title: str = Field(max_length=200)
    wedding_date: date | None = None
    access_until: date
    status: str = Field(max_length=80)
    path: Literal["/ivoryadmin"]


class Snapshot(BaseModel):
    schema_version: Literal[1]
    generated_at: AwareDatetime
    business_date: date
    version: str = Field(max_length=30)
    counts: dict[str, Annotated[int, Field(strict=True, ge=0, le=10**7)]] 
    queues: dict[str, list[Item]]
    worker_status: Literal["ok", "attention", "unknown"]


def read_feed():
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = URLRequest(PLANNER_URL + "/api/integrations/control-centre/overview",
                         headers={"X-Control-Centre-Key": PLANNER_KEY, "Accept": "application/json"})
    with opener.open(request, timeout=5) as response:
        raw = response.read(262145)
        if len(raw) > 262144:
            raise ValueError("Oversize feed")
        snapshot = Snapshot.model_validate_json(raw)
    if (set(snapshot.queues) != set(QUEUE_KEYS) or set(snapshot.counts) != set(COUNT_KEYS)
            or any(type(n) is not int or not 0 <= n <= 10**7 for n in snapshot.counts.values())
            or any(len(items) > 5 for items in snapshot.queues.values())):
        raise ValueError("Unsupported queues")
    return snapshot.model_dump(mode="json")


def planner_snapshot(force=False):
    if len(PLANNER_KEY) < 32:
        return {"status": "not_connected", "message": "Planner connection is not configured.", "data": None}
    with LOCK:
        now = time.monotonic()
        ttl = 15 if force else 60
        if CACHE["attempted"] is None or now - CACHE["attempted"] >= ttl:
            CACHE["attempted"] = now
            CACHE["checked_at"] = datetime.now(timezone.utc).isoformat()
            try:
                CACHE["data"] = read_feed()
                CACHE["error"] = None
            except HTTPError as exc:
                CACHE["error"] = "Planner connection key was rejected or is disabled." if exc.code in {401, 403, 503} else "Planner app returned an unexpected response."
                exc.close()
            except (URLError, OSError, ValueError, ValidationError, HTTPClientError):
                CACHE["error"] = "Planner information could not be refreshed. Check the connection."
        data = CACHE["data"]
        old = data and (datetime.now(timezone.utc) - datetime.fromisoformat(data["generated_at"])).total_seconds() > 300
        status = "stale" if data and (old or CACHE["error"]) else "error" if CACHE["error"] else "connected"
        return {"status": status, "message": CACHE["error"] or ("Saved information is more than five minutes old." if old else "Read-only planner connection."),
                "checked_at": CACHE["checked_at"], "data": data, "source_url": PLANNER_URL}


def register_planner_routes(app, current_admin, require_same_origin):
    # Dependencies are supplied by the app, so this module can also be imported
    # independently by the installer without importing the app back into itself.
    @app.get("/api/planner/overview")
    def overview(response: Response, _: dict = Depends(current_admin)):
        response.headers["Cache-Control"] = "private, no-store"
        return planner_snapshot()

    @app.post("/api/planner/refresh")
    def refresh(request: Request, response: Response, _: dict = Depends(current_admin)):
        require_same_origin(request)
        response.headers["Cache-Control"] = "private, no-store"
        return planner_snapshot(force=True)
