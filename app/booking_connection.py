"""Server-side read-only booking feed. Keys never enter browser responses."""
from datetime import date, datetime, timezone
import os
from http.client import HTTPException as HTTPClientError
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request as URLRequest, ProxyHandler, build_opener

from fastapi import APIRouter, Depends, Request, Response
from pydantic import AwareDatetime, BaseModel, Field, ValidationError
from typing import Literal

from .main import current_admin, require_same_origin
from .workspace import NoRedirect

router = APIRouter(prefix="/api/booking")
BOOKING_URL = os.getenv("DASHBOARD_BOOKING_URL", "https://booking.weddingsbymark.uk").rstrip("/")
BOOKING_KEY = os.getenv("DASHBOARD_BOOKING_KEY", "")
parts = urlsplit(BOOKING_URL)
if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path:
    raise ValueError("DASHBOARD_BOOKING_URL must be a complete origin without a path or credentials")
if parts.scheme == "http" and parts.hostname not in {"127.0.0.1", "localhost", "192.168.24.10", "bookingapp2026"}:
    raise ValueError("Use HTTPS for the booking connection outside the known local server")
QUEUE_KEYS = ("new_enquiries", "quotes_waiting", "accepted_payment", "forms_waiting",
              "agreements_waiting", "overdue_payments", "payments_due")
LOCK = threading.Lock()
CACHE = {"attempted": None, "data": None, "error": None, "checked_at": None}


class Item(BaseModel):
    title: str = Field(max_length=200)
    event_date: date | None = None
    due_date: date | None = None
    amount_pence: int | None = Field(default=None, ge=0, le=10**12)
    venue: str | None = Field(default=None, max_length=240)
    path: str = Field(pattern=r"^/bookings/[a-zA-Z0-9-]{1,64}/(overview|journey|payments)$")


class Queue(BaseModel):
    count: int = Field(ge=0, le=10**7)
    total_amount_pence: int = Field(ge=0, le=10**15)
    items: list[Item] = Field(max_length=5)


class Snapshot(BaseModel):
    schema_version: Literal[1]
    generated_at: AwareDatetime
    business_date: date
    currency: Literal["GBP"]
    payment_amount_basis: Literal["outstanding_invoice_balance"]
    queues: dict[str, Queue]
    upcoming_weddings: list[Item] = Field(max_length=5)


def read_feed():
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = URLRequest(BOOKING_URL + "/api/integrations/control-centre/overview",
                         headers={"X-Control-Centre-Key": BOOKING_KEY, "Accept": "application/json"})
    with opener.open(request, timeout=5) as response:
        raw = response.read(262145)
        if len(raw) > 262144:
            raise ValueError("Oversize feed")
        snapshot = Snapshot.model_validate_json(raw)
    if set(snapshot.queues) != set(QUEUE_KEYS):
        raise ValueError("Unsupported queues")
    return snapshot.model_dump(mode="json")


def booking_snapshot(force=False):
    if len(BOOKING_KEY) < 32:
        return {"status": "not_connected", "message": "Booking connection is not configured.", "data": None}
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
                CACHE["error"] = "Booking connection key was rejected or is disabled." if exc.code in {401, 403, 503} else "Booking app returned an unexpected response."
                exc.close()
            except (URLError, OSError, ValueError, ValidationError, HTTPClientError):
                CACHE["error"] = "Booking information could not be refreshed. Check the connection."
        data = CACHE["data"]
        old = data and (datetime.now(timezone.utc) - datetime.fromisoformat(data["generated_at"])).total_seconds() > 300
        status = "stale" if data and (old or CACHE["error"]) else "error" if CACHE["error"] else "connected"
        return {"status": status, "message": CACHE["error"] or ("Saved information is more than five minutes old." if old else "Read-only booking connection."),
                "checked_at": CACHE["checked_at"], "data": data, "source_url": BOOKING_URL}


@router.get("/overview")
def overview(response: Response, _: dict = Depends(current_admin)):
    response.headers["Cache-Control"] = "private, no-store"
    return booking_snapshot()


@router.post("/refresh")
def refresh(request: Request, response: Response, _: dict = Depends(current_admin)):
    require_same_origin(request)
    response.headers["Cache-Control"] = "private, no-store"
    return booking_snapshot(force=True)
