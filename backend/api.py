"""
JEVA SUPPORT API (FastAPI)

Thin HTTP layer over the support pipeline. All policy stays in
support_agent_claude.py; this file only moves data in and out.

Run:
    uvicorn api:app --reload --port 8000
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import env  # noqa: F401  loads backend/.env before any setting is read
import support_db as db
import support_agent_claude as agent

app = FastAPI(title="Jeva Support API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# MODELS
# ============================================================
class ChatIn(BaseModel):
    ticket_id: str | None = Field(default=None, description="Omit to start a new ticket")
    message: str = Field(min_length=1, max_length=4000)
    sender_name: str = Field(min_length=1, max_length=120)
    sender_email: str = Field(min_length=3, max_length=254)


# ============================================================
# HELPERS
# ============================================================
def next_ticket_id() -> str:
    with db.connect() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM tickets WHERE id LIKE 'TICKET-%'")]
    nums = [int(m.group(1)) for i in ids if (m := re.fullmatch(r"TICKET-(\d+)", i))]
    return f"TICKET-{max([12344, *nums]) + 1}"


def ticket_summary(ticket_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            """SELECT t.*, c.name AS customer_name,
                      (SELECT COUNT(*) FROM ticket_messages m WHERE m.ticket_id = t.id) AS message_count,
                      (SELECT content FROM ticket_messages m WHERE m.ticket_id = t.id
                        ORDER BY m.id DESC LIMIT 1) AS last_message
               FROM tickets t LEFT JOIN customers c ON c.id = t.customer_id
               WHERE t.id = ?""",
            (ticket_id,),
        ).fetchone()
    return dict(row) if row else None


def all_messages(ticket_id: str) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, role, content, created_at FROM ticket_messages WHERE ticket_id = ? ORDER BY id",
            (ticket_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ============================================================
# ROUTES
# ============================================================
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "jev_mode": agent.JEV_MODE,
        "jev_model": agent.JEV_MODEL if agent.JEV_MODE == "live" else "local stand-in",
        "jev_note": agent.JEV_NOTE,
        "jev_key_rejected": agent.JEV_KEY_REJECTED,
        "claude_mode": agent.CLAUDE_MODE,
        "claude_model": agent.CLAUDE_MODEL,
        "llm_provider": agent.LLM_PROVIDER,
        "llm_model": agent.LLM_MODEL,
        "llm_label": agent.LLM_LABEL,
    }


@app.get("/api/customers")
def customers() -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute("SELECT id, name, email, plan FROM customers ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/customers/{customer_id}/history")
def customer_history(customer_id: str) -> dict[str, Any]:
    if db.get_customer_by_id(customer_id) is None:
        raise HTTPException(404, "Customer not found")
    return db.get_customer_history(
        customer_id,
        days=agent.HISTORY_WINDOW_DAYS,
        max_tickets=agent.HISTORY_MAX_TICKETS,
    )


@app.get("/api/tickets")
def tickets(customer_id: str | None = None) -> list[dict[str, Any]]:
    sql = """SELECT t.*, c.name AS customer_name,
                    (SELECT COUNT(*) FROM ticket_messages m WHERE m.ticket_id = t.id) AS message_count,
                    (SELECT content FROM ticket_messages m WHERE m.ticket_id = t.id
                      ORDER BY m.id DESC LIMIT 1) AS last_message
             FROM tickets t LEFT JOIN customers c ON c.id = t.customer_id"""
    args: tuple = ()
    if customer_id:
        sql += " WHERE t.customer_id = ?"
        args = (customer_id,)
    sql += " ORDER BY t.updated_at DESC LIMIT 100"
    with db.connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/tickets/{ticket_id}")
def ticket(ticket_id: str) -> dict[str, Any]:
    summary = ticket_summary(ticket_id)
    if summary is None:
        raise HTTPException(404, "Ticket not found")
    return {"ticket": summary, "messages": all_messages(ticket_id)}


@app.get("/api/tickets/{ticket_id}/audit")
def ticket_audit(ticket_id: str) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT id, tool_name, arguments_json, allowed, result_json, created_at
               FROM tool_audit_log WHERE ticket_id = ? ORDER BY id""",
            (ticket_id,),
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/api/tickets/{ticket_id}/close")
def close_ticket(ticket_id: str) -> dict[str, Any]:
    if db.get_ticket(ticket_id) is None:
        raise HTTPException(404, "Ticket not found")
    db.update_ticket(ticket_id, status="closed")
    db.add_message(ticket_id, "system", "Ticket closed.")
    return {"ticket": ticket_summary(ticket_id)}


@app.post("/api/chat")
def chat(body: ChatIn) -> dict[str, Any]:
    ticket_id = body.ticket_id or next_ticket_id()
    stored = db.get_ticket(ticket_id)
    ticket = agent.Ticket(
        id=ticket_id,
        message=body.message.strip(),
        sender_name=body.sender_name.strip(),
        sender_email=body.sender_email.strip(),
        links=re.findall(r"https?://\S+", body.message),
        status=stored["status"] if stored else "open",
    )
    try:
        result = agent.handle_customer_ticket(ticket)
    except Exception as exc:  # surface a clean error to the UI
        raise HTTPException(502, f"Pipeline error: {type(exc).__name__}: {exc}") from exc
    trace = result.pop("trace", None)
    return {
        "ticket_id": ticket_id,
        "result": result,
        "trace": trace,
        "ticket": ticket_summary(ticket_id),
        "messages": all_messages(ticket_id) if db.get_ticket(ticket_id) else [],
    }


@app.post("/api/reset")
def reset() -> dict[str, Any]:
    db.init_db(reset=True)
    return {"ok": True}


# ============================================================
# SERVE THE BUILT REACT APP (optional, after `npm run build`)
# ============================================================
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="app")
