"""
MOCK MODELS

Used automatically when the Jev SDK or an Anthropic API key
is missing (or when JEV_MODE / CLAUDE_MODE = mock).

    simulate_jev(state)      -> same shape as a Jev response
    MockClaudeClient()       -> same interface as Anthropic().messages.create

They are simple, deterministic heuristics. They exist so the whole
pipeline, the database, the memory and the React app can be run and
demoed end to end. Everything else (policy, gateway, tools, memory)
is the real code path.
"""
from __future__ import annotations

import json
import re
from datetime import date
from types import SimpleNamespace as NS
from typing import Any

ORDER_ID = re.compile(r"\b([A-Za-z])-?(\d{3})\b")
ORG_WORDS = re.compile(r"\b(team|support|rewards?|billing|security|service|bank|admin|official|helpdesk)\b", re.I)


def _order_ids(text: str) -> list[str]:
    return [f"{a.upper()}-{b}" for a, b in ORDER_ID.findall(text or "")]


def _hits(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text))


# ============================================================
# MOCK JEV
# ============================================================
TOPIC_PATTERNS = {
    "billing": r"refund|charge|bill|invoice|payment|paid|subscription|money back|cost|fee|credit",
    "orders": r"order|deliver|ship|package|track|arriv|return|supplies|sign for|parcel",
    "account": r"log ?in|sign ?in|password|locked|account|profile|portal|permission|access|reset|username",
}


def _topic(message: str, earlier: str) -> tuple[str, float]:
    m = message.lower()
    scores = {k: _hits(p, m) for k, p in TOPIC_PATTERNS.items()}
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (best, top), (_, second) = ranked[0], ranked[1]
    if top == 0:
        # Follow-up with no keywords: lean on the conversation so far.
        e = earlier.lower()
        prev = {k: _hits(p, e) for k, p in TOPIC_PATTERNS.items()}
        pbest, ptop = max(prev.items(), key=lambda kv: kv[1])
        if ptop:
            return pbest, 0.82
        # Greetings and small talk: nothing about billing, orders or accounts.
        return "general", 0.86
    if top == second:
        return best, 0.58
    return best, min(0.97, 0.8 + 0.05 * (top - second))


def simulate_jev(state: dict[str, Any]) -> NS:
    ticket = state["ticket"]
    customer = state["customer"]
    message = ticket["message"]
    m = message.lower()
    conversation = state.get("conversation", [])
    earlier_customer = " ".join(t["content"] for t in conversation if t["role"] == "customer")
    history = customer.get("history", {})
    open_ids = {o["id"] for o in customer.get("open_orders", [])}

    choice, conf = _topic(message, earlier_customer)

    creds = bool(re.search(
        r"(send|give|share|provide|reply with|confirm|enter|tell me|verify).{0,50}"
        r"(password|security code|api key|secret key|\bpin\b|social security)", m))
    reward = bool(re.search(
        r"congratulations|you('ve| have) (won|been selected)|winner|prize|gift card|claim (it|your)", m))
    refund = bool(re.search(r"refund|money back|reimburse|credit (back|me)|charged twice|duplicate charge", m))

    display = ticket["sender"]["display_name"] or ""
    local = (ticket["sender"]["email"] or "").split("@")[0].lower()
    name_tokens = [t.lower() for t in re.findall(r"[A-Za-z]+", display)]
    mismatch = 0.03
    if ORG_WORDS.search(display) and not any(t in local for t in name_tokens if len(t) > 2):
        mismatch = 0.9

    ids_now = set(_order_ids(message))
    ids_before = set(_order_ids(earlier_customer))
    if ids_now & open_ids:
        open_order = 0.96
    elif re.search(r"\b(it|order|package|parcel|delivery)\b", m) and ids_before & open_ids:
        open_order = 0.8
    elif re.search(r"order|package", m) and re.search(r"where|track|late|arriv", m) and open_ids:
        open_order = 0.74
    else:
        open_order = 0.08

    frustration_hits = _hits(
        r"frustrat|angry|upset|ridiculous|unacceptable|again|third|three times|nobody|never|worst|"
        r"cancel my|leave|switch|still", m)
    frustration = min(2.0, 0.2 + 0.55 * frustration_hits + (0.3 if "!!" in message else 0))

    # Repeat contact: same order or same unresolved topic in recent history.
    repeat = 0.1
    past = history.get("recent_tickets", [])
    open_cases = history.get("open_cases", [])
    past_text = " ".join((t.get("customer_said") or "") for t in past) + " " + \
        " ".join(c.get("reason", "") for c in open_cases)
    ids_in_past = set(_order_ids(past_text))
    unresolved = bool(open_cases) or any(t["status"] != "closed" for t in past)
    if (ids_now | ids_before) & ids_in_past:
        repeat = 0.93 if unresolved else 0.78
    elif re.search(r"again|still|third|times|follow(ing)? up|already", m) and any(t.get("topic") == choice for t in past):
        repeat = 0.75

    answers = {
        "topic": NS(choice=choice, confidence=round(conf, 2)),
        "requests_credentials": NS(noul=0.93 if creds else 0.03),
        "sender_identity_mismatch": NS(noul=mismatch),
        "unexpected_reward": NS(noul=0.95 if reward else 0.02),
        "refund_requested": NS(noul=0.9 if refund else 0.05),
        "mentions_open_order": NS(noul=open_order),
        "frustration": NS(score=round(frustration, 2), confidence=0.84),
        "repeat_contact": NS(noul=repeat),
    }
    return NS(answers=answers)


# ============================================================
# MOCK CLAUDE
# ============================================================
def _context(system: str) -> dict[str, Any]:
    match = re.search(r"<application_context>\s*(\{.*?\})\s*</application_context>", system, re.S)
    return json.loads(match.group(1)) if match else {}


def _specialist(system: str) -> str:
    s = system.lower()
    if "billing customer support specialist" in s:
        return "billing"
    if "order support specialist" in s:
        return "orders"
    if "account support specialist" in s:
        return "account"
    return "general"


def _nice_date(iso: str | None) -> str | None:
    if not iso:
        return None
    d = date.fromisoformat(iso[:10])
    return d.strftime("%A, %B ") + str(d.day)


def _text_of(content: Any) -> str:
    return content if isinstance(content, str) else ""


class _Messages:
    def create(self, *, model: str, max_tokens: int, system: str,
               tools: list[dict[str, Any]], messages: list[dict[str, Any]]) -> NS:
        ctx = _context(system)
        spec = _specialist(system)
        last = messages[-1]["content"]

        if isinstance(last, list):  # tool results came back
            calls = {b.id: b for b in messages[-2]["content"] if getattr(b, "type", "") == "tool_use"}
            results = [(calls[r["tool_use_id"]].name, json.loads(r["content"])) for r in last]
            return self._reply(ctx, spec, results, messages)

        text = _text_of(last)
        all_user = " ".join(_text_of(m["content"]) for m in messages if m["role"] == "user")
        ids = _order_ids(text) or _order_ids(all_user)[-1:]
        order_id = ids[0] if ids else None

        call = None
        if spec == "orders" and order_id:
            call = ("get_order_status", {"order_id": order_id})
        elif spec == "billing" and order_id and re.search(r"refund|money back|charged twice|duplicate", all_user.lower()):
            reason = "Duplicate charge" if re.search(r"twice|duplicate|double", all_user.lower()) else "Customer requested a refund"
            call = ("create_refund", {"order_id": order_id, "reason": reason})
        elif spec == "account" and re.search(r"log ?in|sign ?in|password|locked|reset|access", text.lower()):
            call = ("reset_password", {})
        elif spec == "general" and re.search(r"\b(human|person|someone|agent|representative)\b", text.lower()):
            call = ("create_human_case", {"reason": "Customer needs help from a person", "priority": ctx.get("priority", "normal")})

        if call:
            return NS(stop_reason="tool_use", content=[NS(type="tool_use", id="toolu_mock_1", name=call[0], input=call[1])])
        return self._reply(ctx, spec, [], messages)

    def _reply(self, ctx: dict[str, Any], spec: str, results: list, messages: list) -> NS:
        first = ctx.get("customer_first_name", "there")
        opener = ""
        # Earlier text replies (not this turn's tool-call step) mean a follow-up.
        followup = any(m["role"] == "assistant" and isinstance(m["content"], str) for m in messages)
        if followup:
            pass  # already acknowledged earlier in this conversation
        elif ctx.get("repeat_contact"):
            opener = "I can see you've reached out about this before, and I'm sorry it's taken this long. "
        elif ctx.get("priority") == "high":
            opener = "I'm sorry for the frustration. "
        body = self._body(spec, results)
        last_user = next((m["content"] for m in reversed(messages)
                          if m["role"] == "user" and isinstance(m["content"], str)), "")
        order = next((r["order"] for n, r in results if n == "get_order_status" and r.get("found")), None)
        if order and re.search(r"\bsign(ature)?\b|sign for", last_user.lower()):
            # Only use facts the tool returned; don't invent delivery rules.
            body = (f"the order details don't say whether a signature is needed. Order {order['id']} is with "
                    f"{order['carrier']} (tracking {order['tracking_number']}), and {order['carrier']}'s tracking "
                    "page will show any signature requirement.")
        if opener:
            body = body[0].upper() + body[1:]
        text = f"Hi {first}, {opener}{body}"
        return NS(stop_reason="end_turn", content=[NS(type="text", text=text)])

    @staticmethod
    def _body(spec: str, results: list) -> str:
        if not results:
            return {
                "orders": "I'd be glad to help with your order. Could you share the order number? It starts with the letter A, like A-123.",
                "billing": "I can help with that. Which charge or invoice are you asking about, and what's the order number?",
                "account": "happy to help with your account. What would you like to change or check?",
                "general": "thanks for reaching out. I can help with orders, billing and your account. What can I do for you today?",
            }[spec]
        name, r = results[0]
        if r.get("blocked") or (r.get("success") is False and "error" in r):
            return "I wasn't able to complete that here, so I'd like a member of our team to take a look. Could you confirm the details and I'll make sure it gets to the right person?"
        if name == "get_order_status":
            if not r.get("found"):
                return "I couldn't find that order on your account. Could you double-check the number?"
            o = r["order"]
            item = f" ({o['item_summary']})" if o.get("item_summary") else ""
            if o["status"] == "shipped":
                when = _nice_date(o.get("estimated_delivery"))
                return (f"order {o['id']}{item} has shipped with {o['carrier']}, tracking number "
                        f"{o['tracking_number']}, and is expected to arrive on {when}. "
                        "If it hasn't arrived by then, just reply here.")
            if o["status"] == "delivered":
                return f"order {o['id']}{item} was delivered on {_nice_date(o.get('delivered_at'))}."
            if o["status"] == "processing":
                when = _nice_date(o.get("estimated_delivery"))
                return f"order {o['id']}{item} is being prepared now, with delivery expected around {when}."
            return f"order {o['id']}{item} is currently marked as {o['status']}."
        if name == "create_refund":
            if r.get("already_submitted"):
                return f"your refund for order {r['order_id']} is already in progress under reference {r['refund_id']}."
            if r["status"] == "pending_approval":
                return (f"I've submitted a refund of ${r['amount']:.2f} for order {r['order_id']} (reference {r['refund_id']}). "
                        "Because of the amount, a team member will approve it before it's processed.")
            return (f"I've submitted a refund of ${r['amount']:.2f} for order {r['order_id']}. "
                    f"Your reference number is {r['refund_id']}, and you'll get an email once it's processed.")
        if name == "reset_password":
            return (f"I've sent a secure password reset link to {r['sent_to']}. It expires in "
                    f"{r['expires_in_minutes']} minutes. We'll never ask you to share your password or a security code.")
        if name == "create_human_case":
            return f"I've passed your message to our support team (case {r['case_id']}), and someone will follow up soon."
        return "thanks, that's done."


class MockClaudeClient:
    def __init__(self) -> None:
        self.messages = _Messages()
