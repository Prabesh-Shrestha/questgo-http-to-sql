"""ESP hotspot -> HTTPS ingestion -> Tiger Data PostgreSQL."""
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

DATABASE_URL = os.environ.get("DATABASE_URL", "")
INGEST_TOKEN = os.environ.get("INGEST_TOKEN", "")
if not DATABASE_URL:
    raise RuntimeError("Set DATABASE_URL to your Tiger Data PostgreSQL connection URL")
if len(INGEST_TOKEN) < 32:
    raise RuntimeError("Set INGEST_TOKEN to a random token at least 32 characters long")


def connect():
    # Preserve stronger TLS settings from the supplied URL; disallow plaintext.
    mode = conninfo_to_dict(DATABASE_URL).get("sslmode", "require")
    if mode not in {"require", "verify-ca", "verify-full"}:
        raise RuntimeError("DATABASE_URL must use sslmode=require or certificate verification")
    return psycopg.connect(DATABASE_URL, sslmode=mode, connect_timeout=8,
                           options="-c statement_timeout=8000", row_factory=dict_row)


@asynccontextmanager
async def lifespan(app):
    # Works with the earlier simple proximity_events table too. DDL is additive.
    try:
        with connect() as conn:
            conn.execute(Path(__file__).with_name("schema.sql").read_text())
    except psycopg.Error as exc:
        # Do not expose credentials or connection strings through application logs.
        logging.error("Database initialization failed (%s)", type(exc).__name__)
        raise RuntimeError("Database initialization failed; check connection settings") from None
    yield


app = FastAPI(title="HackTX proximity API", version="1.0", lifespan=lifespan)
bearer = HTTPBearer(auto_error=False)


def authorize(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]):
    if credentials is None or not secrets.compare_digest(credentials.credentials, INGEST_TOKEN):
        raise HTTPException(401, "Invalid ingestion token", headers={"WWW-Authenticate": "Bearer"})


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"example": {
        "event_id": "2-1234abcd-1", "device_id": 2, "peer_id": 1,
        "event_type": "test", "state": "near", "rssi_dbm": -49,
        "boot_id": 305441741, "sequence": 1, "uptime_ms": 1000
    }})
    event_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    device_id: int = Field(ge=1, le=65535)
    peer_id: int = Field(ge=1, le=65535)
    event_type: Literal["hotspot_connected", "peer_detected", "peer_near", "peer_far", "peer_missing", "test"]
    state: Literal["missing", "uncertain", "near", "far"]
    rssi_dbm: int | None = Field(default=None, ge=-127, le=0)
    boot_id: int = Field(ge=0, le=4294967295)
    sequence: int = Field(ge=0, le=4294967295)
    uptime_ms: int = Field(ge=0, le=4294967295)


@app.get("/health")
def health():
    return {"status": "ok"}  # Process health; GET /events also checks DB access.


@app.post("/events", dependencies=[Depends(authorize)])
def insert_event(event: Event, idempotency_key: Annotated[str | None, Header()] = None):
    if idempotency_key is not None and idempotency_key != event.event_id:
        raise HTTPException(400, "Idempotency-Key must match event_id")
    if event.device_id == event.peer_id:
        raise HTTPException(422, "device_id and peer_id must differ")
    payload = event.model_dump()
    try:
        with connect() as conn:
            row = conn.execute("""
                INSERT INTO proximity_events
                    (event_id, device_id, peer_id, event_type, rssi_dbm, payload, state, boot_id, sequence, uptime_ms)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING RETURNING event_id
                """, (event.event_id, event.device_id, event.peer_id,
                      event.event_type, event.rssi_dbm, Jsonb(payload), event.state,
                      event.boot_id, event.sequence, event.uptime_ms)).fetchone()
            if row is None:
                old = conn.execute("SELECT payload FROM proximity_events WHERE event_id=%s",
                                   (event.event_id,)).fetchone()
                if old is None or old["payload"] != payload:
                    raise HTTPException(409, "Event ID already exists with different content")
        # Exiting the connection context commits before this success response.
        return {"ok": True, "event_id": event.event_id, "duplicate": row is None}
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(422, "Register both device IDs in devices first") from None
    except psycopg.Error as exc:
        logging.error("Database write failed (%s)", type(exc).__name__)
        raise HTTPException(503, "Database unavailable; retry the same event ID") from None


@app.get("/events", dependencies=[Depends(authorize)])
def list_events(limit: Annotated[int, Query(ge=1, le=100)] = 20):
    try:
        with connect() as conn:
            return conn.execute("""
                SELECT *
                FROM proximity_history ORDER BY received_at DESC LIMIT %s
                """, (limit,)).fetchall()
    except psycopg.Error as exc:
        logging.error("Database read failed (%s)", type(exc).__name__)
        raise HTTPException(503, "Database unavailable") from None
