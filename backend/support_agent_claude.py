"""
END-TO-END CUSTOMER SUPPORT AGENT (Claude edition)
Architecture:
Customer Ticket
       ↓
Deterministic Python
       ↓
Jev / System One
       ↓
7 semantic questions
       ↓
Python composition
       ↓
Spam / confidence / business rules
       ↓
Routing
       ↓
Specialist Claude
       ↓
Claude requests a TOOL
       ↓
Python TOOL GATEWAY
       ↓
Real business operation
       ↓
Tool result
       ↓
Claude
       ↓
Customer response
IMPORTANT:
Jev does semantic understanding.
Python owns:
    - workflow
    - policy
    - thresholds
    - routing
    - tool permissions
    - business side effects
Claude owns:
    - open-ended reasoning
    - interpreting tool results
    - natural-language responses
Claude NEVER directly executes business operations.

MEMORY (two layers, both owned by Python):
    1. Conversation memory: every customer and agent turn is
       stored in ticket_messages. A follow-up on the same ticket
       reloads the last turns, so Claude continues the thread.
    2. Customer history: a bounded summary of the customer's
       recent tickets, open cases and refunds is loaded before
       Jev runs. Jev judges whether this is a repeat contact;
       Python counts the contacts and decides priority.
"""
from dataclasses import dataclass
from typing import Any
import json
import os
import secrets
import env  # noqa: F401  loads backend/.env before any setting is read
import support_db as db
import mock_models
import groq_llm
# ------------------------------------------------------------
# OPTIONAL SDKs
#
# The pipeline runs with the real Jev and LLM when their
# SDKs and keys are present, and falls back to local mocks
# otherwise. Override with JEV_MODE = auto|live|mock and
# LLM_PROVIDER = auto|anthropic|groq|mock.
# ------------------------------------------------------------
try:
    from anthropic import Anthropic
except ImportError:  # pragma: no cover
    Anthropic = None
try:
    from typesafe_sdk import (
        Choice,
        Noul,
        NoulCriteria,
        RetryPolicy,
        Score,
        TypeSafeAuthenticationError,
        TypeSafeClient,
    )
    _HAS_TYPESAFE = True
except ImportError:
    _HAS_TYPESAFE = False
    # Lightweight stand-ins so the question definitions
    # still build (and can be shown in the UI) without the SDK.
    def Choice(**kw): return {"type": "choice", **kw}
    def Noul(**kw): return {"type": "noul", **kw}
    def NoulCriteria(**kw): return kw
    def Score(**kw): return {"type": "score", **kw}
    TypeSafeClient = None


def _mode(var: str, live_ok: bool) -> str:
    wanted = os.environ.get(var, "auto").lower()
    if wanted == "mock":
        return "mock"
    if wanted == "live":
        if not live_ok:
            raise RuntimeError(f"{var}=live but its SDK or API key is missing")
        return "live"
    return "live" if live_ok else "mock"


# ------------------------------------------------------------
# JEV (TypeSafe System One)
#   live needs typesafe-sdk and TYPESAFE_API_KEY.
#   JEV_MODE=auto (default) also checks the key once at
#   startup. If TypeSafe rejects it, Jev falls back to the
#   local stand-in and the UI says why. JEV_MODE=live never
#   falls back, so key errors show on every ticket.
# ------------------------------------------------------------
JEV_MODEL = os.environ.get("JEV_MODEL", "jev-latest")
JEV_TIMEOUT_SECONDS = 30.0


def _jev_key_rejected() -> bool:
    """One cheap call at startup. Only a 401 counts: a network
    hiccup keeps Jev live and surfaces on the ticket instead."""
    try:
        with TypeSafeClient(retry=RetryPolicy(max_retries=0), timeout=8.0) as client:
            client.models.list()
    except TypeSafeAuthenticationError:
        return True
    except Exception:
        return False
    return False


_jev_wanted = os.environ.get("JEV_MODE", "auto").lower()
_jev_key_set = bool(os.environ.get("TYPESAFE_API_KEY", "").strip())
JEV_MODE = _mode("JEV_MODE", _HAS_TYPESAFE and _jev_key_set)
JEV_KEY_REJECTED = JEV_MODE == "live" and _jev_wanted == "auto" and _jev_key_rejected()
if JEV_KEY_REJECTED:
    JEV_MODE = "mock"
# Why Jev is not live, for the UI. Empty when it is live.
if JEV_KEY_REJECTED:
    JEV_NOTE = "TypeSafe rejected TYPESAFE_API_KEY (401)"
elif JEV_MODE == "live":
    JEV_NOTE = ""
elif _jev_wanted == "mock":
    JEV_NOTE = "JEV_MODE is set to mock"
elif not _HAS_TYPESAFE:
    JEV_NOTE = "typesafe-sdk is not installed"
else:
    JEV_NOTE = "TYPESAFE_API_KEY is not set"


# ------------------------------------------------------------
# LLM PROVIDER
#   anthropic : Claude (needs ANTHROPIC_API_KEY)
#   groq      : openai/gpt-oss-20b on Groq, free tier (needs GROQ_API_KEY)
#   mock      : local stand-in, no key needed
# LLM_PROVIDER=auto (default) picks anthropic, then groq, then mock.
# CLAUDE_MODE=mock is still honoured for older setups.
# ------------------------------------------------------------
def _pick_llm_provider() -> str:
    anthropic_ok = Anthropic is not None and bool(os.environ.get("ANTHROPIC_API_KEY"))
    groq_ok = groq_llm.groq_available()
    wanted = os.environ.get("LLM_PROVIDER", "auto").lower()
    if os.environ.get("CLAUDE_MODE", "").lower() == "mock" and wanted == "auto":
        wanted = "mock"
    if wanted == "anthropic" and not anthropic_ok:
        raise RuntimeError("LLM_PROVIDER=anthropic but anthropic or ANTHROPIC_API_KEY is missing")
    if wanted == "groq" and not groq_ok:
        raise RuntimeError("LLM_PROVIDER=groq but openai or GROQ_API_KEY is missing")
    if wanted in ("anthropic", "groq", "mock"):
        return wanted
    if anthropic_ok:
        return "anthropic"
    if groq_ok:
        return "groq"
    return "mock"


LLM_PROVIDER = _pick_llm_provider()
# Kept for the API and UI: "live" when a real model answers.
CLAUDE_MODE = "mock" if LLM_PROVIDER == "mock" else "live"
# ============================================================
# CONFIGURATION
# ============================================================
CLAUDE_MODEL = "claude-sonnet-5"
CLAUDE_MAX_TOKENS = 1024
# Safety stop so a tool loop can never run forever.
MAX_TOOL_ROUNDS = 5
# Business limits for the tools.
REFUND_AUTO_APPROVE_LIMIT_CENTS = 10_000   # $100; larger refunds wait for approval
PASSWORD_RESET_TTL_MINUTES = 30
# ------------------------------------------------------------
# MEMORY LIMITS (what the models are allowed to see)
# ------------------------------------------------------------
MEMORY_MAX_TURNS = 10          # turns of this ticket replayed to Claude
HISTORY_WINDOW_DAYS = 30       # how far back customer history goes
HISTORY_MAX_TICKETS = 5        # most recent other tickets summarized
REPEAT_CONTACT_MIN = 2         # prior contacts in 7 days to count as repeat
# ------------------------------------------------------------
# JEV / APPLICATION THRESHOLDS
# ------------------------------------------------------------
TOPIC_MIN_CONFIDENCE = 0.75
SPAM_LOW = 0.40
SPAM_HIGH = 0.60
NOUL_ACTION_THRESHOLD = 0.70
HIGH_FRUSTRATION_SCORE = 1.5
HIGH_FRUSTRATION_CONFIDENCE = 0.70
# Reads ANTHROPIC_API_KEY from the environment.
if LLM_PROVIDER == "anthropic":
    claude_client = Anthropic()
    LLM_MODEL, LLM_LABEL = CLAUDE_MODEL, "Claude"
elif LLM_PROVIDER == "groq":
    # Same .messages.create interface, so the agent loop is unchanged.
    claude_client = groq_llm.GroqLLMClient()
    LLM_MODEL, LLM_LABEL = claude_client.model, "GPT-OSS"
else:
    claude_client = mock_models.MockClaudeClient()
    LLM_MODEL, LLM_LABEL = "mock", "Mock LLM"
# Creates support.db with fake data on first run.
db.init_db()
# ============================================================
# DATA MODELS
# ============================================================
@dataclass
class Ticket:
    id: str
    message: str
    sender_name: str
    sender_email: str
    links: list[str]
    status: str
@dataclass
class Customer:
    id: str
    name: str
    plan: str
    orders: list[dict[str, Any]]
# ============================================================
# DETERMINISTIC CUSTOMER DATA
# ============================================================
def get_customer(ticket: Ticket) -> Customer | None:
    """
    Looks the sender up in the customers table by email
    and loads their orders. Returns None for unknown senders.
    """
    row = db.find_customer_by_email(ticket.sender_email)
    if row is None:
        return None
    return Customer(
        id=row["id"],
        name=row["name"],
        plan=row["plan"],
        orders=db.list_orders(row["id"]),
    )
# ============================================================
# FOCUSED CONTEXT
# ============================================================
def build_focused_context(
    ticket: Ticket,
    customer: Customer,
    history: dict[str, Any],
    conversation: list[dict[str, Any]],
) -> dict[str, Any]:
    open_orders = [
        order
        for order in customer.orders
        if order["status"] != "delivered"
    ]
    return {
        "ticket": {
            "id": ticket.id,
            "message": ticket.message,
            "sender": {
                "display_name": ticket.sender_name,
                "email": ticket.sender_email,
            },
            "links": ticket.links,
        },
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "plan": customer.plan,
            "open_orders": open_orders,
            # MEMORY layer 2: bounded summary of past contacts
            "history": history,
        },
        # MEMORY layer 1: earlier turns of THIS ticket
        "conversation": [
            {"role": m["role"], "content": m["content"]}
            for m in conversation
        ],
        "policy": {
            "sensitive_credentials": [
                "password",
                "security code",
                "API key",
                "secret key",
            ]
        },
    }
# ============================================================
# JEV QUESTIONS
# ============================================================
def build_jev_questions():
    return {
        # ====================================================
        # 1. CHOICE
        # ====================================================
        "topic": Choice(
            instructions={
                "question": (
                    "Which team should handle the ticket?"
                ),
                "focus": (
                    "Classify the customer's primary request."
                ),
            },
            criteria={
                "billing": {
                    "what": (
                        "Charges, invoices, refunds, "
                        "subscriptions, or payments"
                    ),
                    "not_for": (
                        "Order tracking or account access"
                    ),
                },
                "orders": {
                    "what": (
                        "Order status, delivery, "
                        "cancellation, or returns"
                    ),
                    "not_for": (
                        "Charges or account access"
                    ),
                },
                "account": {
                    "what": (
                        "Login, profile, permissions, "
                        "or account security"
                    ),
                    "not_for": (
                        "Charges or order tracking"
                    ),
                },
            },
        ),
        # ====================================================
        # 2. NOUL
        # ====================================================
        "requests_credentials": Noul(
            instructions={
                "question": (
                    "Does the message request "
                    "a sensitive credential?"
                ),
                "compare": [
                    "`ticket.message`",
                    "`policy.sensitive_credentials`",
                ],
            },
            criteria=NoulCriteria(
                true={
                    "what": (
                        "Asks the recipient to disclose "
                        "a sensitive credential"
                    ),
                },
                false={
                    "what": (
                        "Does not ask for a credential"
                    ),
                },
            ),
        ),
        # ====================================================
        # 3. NOUL
        # ====================================================
        "sender_identity_mismatch": Noul(
            instructions={
                "question": (
                    "Does the claimed sender identity "
                    "conflict with its domain?"
                ),
                "compare": [
                    "`ticket.sender.display_name`",
                    "`ticket.sender.email`",
                ],
            },
            criteria=NoulCriteria(
                true={
                    "what": (
                        "Organization claim conflicts "
                        "with email domain"
                    ),
                },
                false={
                    "what": (
                        "Identity and domain agree "
                        "or there is no conflict"
                    ),
                },
            ),
        ),
        # ====================================================
        # 4. NOUL
        # ====================================================
        "unexpected_reward": Noul(
            instructions={
                "question": (
                    "Does the message announce "
                    "an unexpected reward?"
                ),
                "inspect": "`ticket.message`",
            },
            criteria=NoulCriteria(
                true={
                    "what": (
                        "Unsolicited prize, payment, "
                        "or reward"
                    ),
                },
                false={
                    "what": (
                        "No unexpected reward claim"
                    ),
                },
            ),
        ),
        # ====================================================
        # 5. NOUL
        # ====================================================
        "refund_requested": Noul(
            instructions={
                "question": (
                    "Does the customer explicitly "
                    "request a refund or credit?"
                ),
                "inspect": "`ticket.message`",
            },
            criteria=NoulCriteria(
                true={
                    "what": (
                        "Directly asks for money back "
                        "or account credit"
                    ),
                },
                false={
                    "what": (
                        "Does not request a refund"
                    ),
                },
            ),
        ),
        # ====================================================
        # 6. NOUL
        # ====================================================
        "mentions_open_order": Noul(
            instructions={
                "question": (
                    "Does the message refer "
                    "to a supplied open order?"
                ),
                "compare": [
                    "`ticket.message`",
                    "`customer.open_orders`",
                ],
            },
            criteria=NoulCriteria(
                true={
                    "what": (
                        "Identifies an open order "
                        "by ID or details"
                    ),
                },
                false={
                    "what": (
                        "Does not identify "
                        "a supplied open order"
                    ),
                },
            ),
        ),
        # ====================================================
        # 7. SCORE
        # ====================================================
        "frustration": Score(
            instructions={
                "question": (
                    "How frustrated does the "
                    "customer appear?"
                ),
                "inspect": "`ticket.message`",
            },
            criteria=[
                {
                    "what": "Calm and matter-of-fact",
                },
                {
                    "what": "Frustrated but civil",
                },
                {
                    "what": (
                        "Very angry or threatening "
                        "to leave"
                    ),
                },
            ],
        ),
        # ====================================================
        # 8. NOUL (uses memory)
        # ====================================================
        "repeat_contact": Noul(
            instructions={
                "question": (
                    "Is this a repeat contact about the "
                    "same unresolved issue?"
                ),
                "compare": [
                    "`ticket.message`",
                    "`customer.history.recent_tickets`",
                    "`customer.history.open_cases`",
                ],
            },
            criteria=NoulCriteria(
                true={
                    "what": (
                        "A recent ticket or open case is "
                        "about the same issue and it is "
                        "still unresolved"
                    ),
                },
                false={
                    "what": (
                        "New issue, or earlier contacts "
                        "were about something else or "
                        "were resolved"
                    ),
                },
            ),
        ),
    }
# ============================================================
# RUN JEV
# ============================================================
def analyze_with_jev(
    state: dict[str, Any],
):
    questions = build_jev_questions()
    if JEV_MODE == "mock":
        return mock_models.simulate_jev(state)
    with TypeSafeClient(timeout=JEV_TIMEOUT_SECONDS) as client:
        response = client.system_one(
            model=JEV_MODEL,
            state=state,
            questions=questions,
        )
    return response
# ============================================================
# SPAM COMPOSITION
# ============================================================
def calculate_spam_risk(
    answers,
) -> float:
    credential_risk = answers["requests_credentials"].noul
    identity_risk = answers["sender_identity_mismatch"].noul
    reward_risk = answers["unexpected_reward"].noul
    return (
        0.45 * credential_risk
        + 0.30 * identity_risk
        + 0.25 * reward_risk
    )
# ============================================================
# HUMAN REVIEW GATE
# ============================================================
def requires_human_review(
    answers,
    spam_risk: float,
) -> bool:
    spam_uncertain = SPAM_LOW < spam_risk < SPAM_HIGH
    topic_uncertain = (
        answers["topic"].confidence < TOPIC_MIN_CONFIDENCE
    )
    return spam_uncertain or topic_uncertain
# ============================================================
# ROUTING
# ============================================================
def determine_specialist(
    answers,
) -> str:
    topic = answers["topic"].choice
    if topic == "billing":
        return "billing_specialist"
    if topic == "orders":
        return "orders_specialist"
    if topic == "account":
        return "account_specialist"
    return "general_support"
def is_repeat_contact(
    answers,
    history: dict[str, Any],
) -> bool:
    """
    Jev judges "same unresolved issue" (semantic).
    Python counts the contacts (deterministic).
    Both must agree.
    """
    return (
        answers["repeat_contact"].noul >= NOUL_ACTION_THRESHOLD
        and history["contacts_last_7_days"] >= REPEAT_CONTACT_MIN
    )
def determine_priority(
    answers,
    history: dict[str, Any],
) -> str:
    frustration = answers["frustration"]
    if (
        frustration.score >= HIGH_FRUSTRATION_SCORE
        and frustration.confidence >= HIGH_FRUSTRATION_CONFIDENCE
    ):
        return "high"
    if is_repeat_contact(answers, history):
        return "high"
    return "normal"
# ============================================================
# BUSINESS TOOLS
#
# IMPORTANT:
#
# These functions are owned by YOUR APPLICATION.
#
# Claude cannot directly execute them.
# ============================================================
# TOOL 1
# GET ORDER STATUS
# ============================================================
def get_order_status(
    customer_id: str,
    order_id: str,
) -> dict[str, Any]:
    """
    Reads the orders table.
    The query filters by customer_id, so asking for
    another member's order returns found: False.
    """
    order = db.get_order_for_customer(customer_id, order_id)
    if order is None:
        return {
            "found": False,
            "order": None,
        }
    return {
        "found": True,
        "order": order,
    }
# ============================================================
# TOOL 2
# CREATE REFUND
# ============================================================
def create_refund(
    customer_id: str,
    order_id: str,
    reason: str,
    ticket_id: str,
) -> dict[str, Any]:
    """
    Writes to the refunds table.
    Production guardrails implemented here:
        - ownership: the order must belong to the customer
        - idempotency: one refund per ticket and order
        - amount limit: large refunds wait for approval
        - audit logging: handled by execute_tool
    """
    order = db.get_order_for_customer(customer_id, order_id)
    if order is None:
        return {
            "success": False,
            "error": "Order not found for this customer.",
        }
    existing = db.get_refund_for_ticket(ticket_id, order["id"])
    if existing is not None:
        return {
            "success": True,
            "already_submitted": True,
            "refund_id": existing["refund_ref"],
            "order_id": existing["order_id"],
            "amount": round(existing["amount_cents"] / 100, 2),
            "status": existing["status"],
        }
    charge = db.find_refundable_charge(customer_id, order["id"])
    if charge is None:
        return {
            "success": False,
            "error": "No refundable charge found on this order.",
        }
    status = (
        "submitted"
        if charge["amount_cents"] <= REFUND_AUTO_APPROVE_LIMIT_CENTS
        else "pending_approval"
    )
    refund = db.insert_refund(
        customer_id=customer_id,
        order_id=order["id"],
        charge_id=charge["id"],
        amount_cents=charge["amount_cents"],
        reason=reason,
        status=status,
        ticket_id=ticket_id,
    )
    return {
        "success": True,
        "refund_id": refund["refund_ref"],
        "order_id": refund["order_id"],
        "amount": round(refund["amount_cents"] / 100, 2),
        "reason": refund["reason"],
        "status": refund["status"],
    }
# ============================================================
# TOOL 3
# RESET PASSWORD
# ============================================================
def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:1]}***@{domain}"
def reset_password(
    customer_id: str,
) -> dict[str, Any]:
    """
    Writes to the password_resets table.
    Only a hash of the token is stored.
    The raw token goes to the email service,
    never to Claude and never into the result.
    """
    customer = db.get_customer_by_id(customer_id)
    if customer is None:
        return {
            "success": False,
            "error": "Customer not found.",
        }
    raw_token = secrets.token_urlsafe(32)
    reset = db.insert_password_reset(
        customer_id=customer_id,
        sent_to=customer["email"],
        raw_token=raw_token,
        ttl_minutes=PASSWORD_RESET_TTL_MINUTES,
    )
    # Real implementation: email_service.send_reset_link(customer["email"], raw_token)
    del raw_token
    return {
        "success": True,
        "action": "password_reset_link_sent",
        "sent_to": mask_email(reset["sent_to"]),
        "expires_in_minutes": PASSWORD_RESET_TTL_MINUTES,
        "status": "completed",
    }
# ============================================================
# TOOL 4
# CREATE HUMAN CASE
# ============================================================
def create_human_case(
    ticket_id: str,
    reason: str,
    priority: str,
    customer_id: str | None = None,
) -> dict[str, Any]:
    """
    Writes to the human_cases table.
    Real implementation would also push the case to
    CRM / ServiceNow / Zendesk / Salesforce etc.
    """
    if priority not in ("normal", "high"):
        priority = "normal"
    case = db.insert_human_case(
        ticket_id=ticket_id,
        customer_id=customer_id,
        reason=reason,
        priority=priority,
    )
    return {
        "success": True,
        "case_id": case["case_ref"],
        "ticket_id": case["ticket_id"],
        "reason": case["reason"],
        "priority": case["priority"],
        "status": case["status"],
    }
# ============================================================
# TOOL DEFINITIONS GIVEN TO CLAUDE
#
# Anthropic format: name, description, input_schema.
#
# customer_id and ticket_id are NOT exposed to Claude.
# The gateway injects them from the session, so the
# model can never act on a different customer.
# ============================================================
TOOL_DEFINITIONS = [
    {
        "name": "get_order_status",
        "description": (
            "Get the current status, carrier, tracking "
            "number and estimated delivery date of one "
            "of the customer's orders. Use this whenever "
            "the customer asks where an order is."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "Order ID, for example A-104.",
                },
            },
            "required": ["order_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_refund",
        "description": (
            "Submit a refund request for one of the "
            "customer's orders. Only use this when the "
            "customer has explicitly asked for money back "
            "or account credit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "description": "Order ID to refund.",
                },
                "reason": {
                    "type": "string",
                    "description": "Short reason, in plain words.",
                },
            },
            "required": ["order_id", "reason"],
            "additionalProperties": False,
        },
    },
    {
        "name": "reset_password",
        "description": (
            "Send the customer a secure password reset "
            "link through the approved workflow. Never "
            "ask the customer for their password."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "create_human_case",
        "description": (
            "Create a case so a human support agent "
            "follows up with the customer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why a person needs to help.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["normal", "high"],
                },
            },
            "required": ["reason", "priority"],
            "additionalProperties": False,
        },
    },
]
# ============================================================
# TOOL GATEWAY
#
# THIS IS THE SECURITY / POLICY BOUNDARY.
# ============================================================
def _dispatch_tool(
    tool_name: str,
    arguments: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """
    Claude asks for a tool.
    Python decides whether Claude is allowed
    to execute that tool.
    Claude does NOT call these functions directly.
    Denials carry "blocked": True so the audit log
    can tell a policy block from a normal failure.
    """
    customer_id = context["customer_id"]
    ticket_id = context["ticket_id"]
    allowed_tools = {
        "get_order_status",
        "create_refund",
        "reset_password",
        "create_human_case",
    }
    if tool_name not in allowed_tools:
        return {
            "success": False,
            "blocked": True,
            "error": "Tool is not allowed.",
        }
    # ========================================================
    # GET ORDER STATUS
    # ========================================================
    if tool_name == "get_order_status":
        return get_order_status(
            customer_id=customer_id,
            order_id=arguments["order_id"],
        )
    # ========================================================
    # CREATE REFUND
    # ========================================================
    if tool_name == "create_refund":
        # ----------------------------------------------------
        # IMPORTANT:
        #
        # Claude cannot decide by itself that a refund
        # is authorized.
        #
        # Python checks the Jev signal.
        # ----------------------------------------------------
        if not context["refund_requested"]:
            return {
                "success": False,
                "blocked": True,
                "error": (
                    "Refund request was not detected "
                    "by the routing layer."
                ),
            }
        return create_refund(
            customer_id=customer_id,
            order_id=arguments["order_id"],
            reason=arguments["reason"],
            ticket_id=ticket_id,
        )
    # ========================================================
    # RESET PASSWORD
    # ========================================================
    if tool_name == "reset_password":
        if context["topic"] != "account":
            return {
                "success": False,
                "blocked": True,
                "error": (
                    "Password reset tool is only "
                    "available for account requests."
                ),
            }
        return reset_password(
            customer_id=customer_id
        )
    # ========================================================
    # HUMAN CASE
    # ========================================================
    if tool_name == "create_human_case":
        return create_human_case(
            ticket_id=ticket_id,
            reason=arguments["reason"],
            priority=arguments.get(
                "priority",
                context["priority"],
            ),
            customer_id=customer_id,
        )
    return {
        "success": False,
        "blocked": True,
        "error": "Unknown tool.",
    }
def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    context: dict[str, Any],
    tool_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Gateway entry point: run the policy check and the
    tool, then write every request to tool_audit_log,
    allowed or blocked.
    """
    try:
        result = _dispatch_tool(tool_name, arguments, context)
    except Exception as exc:  # never leak a stack trace to the model
        result = {
            "success": False,
            "error": f"Tool failed: {type(exc).__name__}",
        }
    db.log_tool_call(
        ticket_id=context["ticket_id"],
        customer_id=context["customer_id"],
        tool_name=tool_name,
        arguments=arguments,
        allowed=not result.get("blocked", False),
        result=result,
    )
    if tool_trace is not None:
        tool_trace.append({
            "name": tool_name,
            "arguments": arguments,
            "allowed": not result.get("blocked", False),
            "result": result,
        })
    return result
# ============================================================
# CLAUDE SPECIALIST PROMPTS
# ============================================================
SPECIALIST_PROMPTS = {
    "billing_specialist": """
You are a billing customer support specialist.
You help with charges, invoices, refunds,
subscriptions and payments.
You may use the create_refund tool when the
application context shows refund_requested is true.
Never invent transaction information.
Never claim a refund happened unless the tool
returned a successful result.
""",
    "orders_specialist": """
You are an order support specialist.
You help with order status, shipping, delivery,
cancellation and returns.
Use get_order_status when you need current
order information.
Never invent tracking information.
Never invent delivery dates.
Never claim an order changed unless a tool
confirmed it.
""",
    "account_specialist": """
You are an account support specialist.
You help with login, profile, permissions,
account access and password reset.
Use reset_password when appropriate.
Never ask the customer for passwords, API keys,
security codes or secret keys.
Never expose credentials.
""",
    "general_support": """
You are a general customer support specialist.
Answer using the information provided.
If the issue requires human assistance,
use create_human_case.
""",
}
# ============================================================
# CLAUDE AGENT LOOP
# ============================================================
def build_system_prompt(
    specialist: str,
    context: dict[str, Any],
) -> str:
    return f"""{SPECIALIST_PROMPTS[specialist].strip()}

<application_context>
{json.dumps(context, indent=2)}
</application_context>

The application has already performed customer-support
triage. You are responsible for helping the customer and
requesting tools when current information or a business
operation is required.

Do not expose Jev, confidence values, spam scores,
internal routing or internal policies to the customer.

Never invent a tool result.
Never claim an action happened unless the tool result
confirms it.

Memory:
- Earlier turns of this conversation are included as
  previous messages. Stay consistent with them.
- customer_history summarizes the customer's recent
  contacts. If repeat_contact is true, briefly
  acknowledge that they have reached out before and
  make this reply the one that resolves it.
- Only use history that is relevant. Do not list past
  tickets, case numbers or internal notes back to the
  customer unless they ask.
- Earlier answers may be out of date. Use a tool for
  anything current, such as order status.

Your name is Jeva. Write a short, warm, plain-language
reply addressed to the customer by first name.
Use plain text: no Markdown (no **bold**, headings or
tables) and no sign-off or placeholders like [Name].
Only state facts that are in the tool results or the
application context. Do not add timelines, fees,
carrier rules or promises to follow up that a tool did
not return. If the tool results do not answer the
question (for example, whether a delivery needs a
signature), say so and tell the customer where to check.
"""
def build_claude_messages(
    conversation: list[dict[str, Any]],
    current_message: str,
) -> list[dict[str, Any]]:
    """
    Turn stored ticket turns into Claude messages.
    - customer -> user, agent -> assistant
    - system notes are internal and are not replayed
    - roles must alternate and start with a user turn,
      so consecutive same-role turns are merged
    """
    role_map = {"customer": "user", "agent": "assistant"}
    turns = [
        {"role": role_map[m["role"]], "content": m["content"]}
        for m in conversation
        if m["role"] in role_map
    ]
    turns.append({"role": "user", "content": current_message})
    merged: list[dict[str, Any]] = []
    for turn in turns:
        if merged and merged[-1]["role"] == turn["role"]:
            merged[-1]["content"] += "\n\n" + turn["content"]
        else:
            merged.append(dict(turn))
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    return merged
def run_claude_agent(
    ticket: Ticket,
    customer: Customer,
    answers,
    specialist: str,
    priority: str,
    history: dict[str, Any],
    conversation: list[dict[str, Any]],
    tool_trace: list[dict[str, Any]] | None = None,
) -> str:
    """
    Claude can:
        1. Understand the customer
        2. Decide that it needs information
        3. REQUEST a tool
        4. Receive tool result
        5. Write final answer
    But Claude cannot execute the underlying
    business function.
    """
    topic = answers["topic"]
    context = {
        "customer_id": customer.id,
        "customer_first_name": customer.name.split()[0],
        "ticket_id": ticket.id,
        "topic": topic.choice,
        "topic_confidence": topic.confidence,
        "priority": priority,
        "refund_requested": (
            answers["refund_requested"].noul
            >= NOUL_ACTION_THRESHOLD
        ),
        "mentions_open_order": (
            answers["mentions_open_order"].noul
            >= NOUL_ACTION_THRESHOLD
        ),
        "repeat_contact": is_repeat_contact(answers, history),
        "customer_history": {
            "contacts_last_7_days": history["contacts_last_7_days"],
            "recent_tickets": history["recent_tickets"],
            "open_cases": history["open_cases"],
            "recent_refunds": history["recent_refunds"],
        },
    }
    system_prompt = build_system_prompt(
        specialist=specialist,
        context=context,
    )
    # The customer's words go in user turns,
    # the application's rules go in the system prompt.
    # Earlier turns of this ticket are replayed first.
    messages = build_claude_messages(
        conversation=conversation,
        current_message=ticket.message,
    )
    # --------------------------------------------------------
    # TOOL LOOP
    # --------------------------------------------------------
    for _ in range(MAX_TOOL_ROUNDS):
        response = claude_client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            system=system_prompt,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )
        tool_calls = [
            block
            for block in response.content
            if block.type == "tool_use"
        ]
        # ----------------------------------------------------
        # NO TOOL REQUIRED: RETURN CLAUDE'S TEXT
        # ----------------------------------------------------
        if response.stop_reason != "tool_use" or not tool_calls:
            return "".join(
                block.text
                for block in response.content
                if block.type == "text"
            ).strip()
        # Keep Claude's turn (including tool_use blocks)
        # in the history so tool results can reference it.
        messages.append({
            "role": "assistant",
            "content": response.content,
        })
        tool_results = []
        # ----------------------------------------------------
        # EXECUTE REQUESTED TOOLS
        # ----------------------------------------------------
        for tool_call in tool_calls:
            # -----------------------------------------------
            # PYTHON TOOL GATEWAY
            # -----------------------------------------------
            result = execute_tool(
                tool_name=tool_call.name,
                arguments=tool_call.input,
                context=context,
                tool_trace=tool_trace,
            )
            # -----------------------------------------------
            # SEND RESULT BACK TO CLAUDE
            # -----------------------------------------------
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_call.id,
                "content": json.dumps(result),
                "is_error": result.get("success") is False,
            })
        # All tool results go back in one user turn.
        messages.append({
            "role": "user",
            "content": tool_results,
        })
    # --------------------------------------------------------
    # SAFETY STOP: TOO MANY TOOL ROUNDS
    # --------------------------------------------------------
    create_human_case(
        ticket_id=ticket.id,
        reason="Agent exceeded maximum tool rounds",
        priority=priority,
        customer_id=customer.id,
    )
    return (
        "Thanks for your patience. I've passed your "
        "message to our support team, and a member of "
        "the team will follow up with you shortly."
    )
# ============================================================
# TRACE HELPERS (what the UI shows, never sent to the models)
# ============================================================
def serialize_answers(answers) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in answers.items():
        out[key] = {
            attr: getattr(value, attr)
            for attr in ("choice", "confidence", "noul", "score")
            if getattr(value, attr, None) is not None
        }
    return out
def new_trace(ticket: Ticket) -> dict[str, Any]:
    return {
        "modes": {"jev": JEV_MODE, "claude": CLAUDE_MODE, "llm": LLM_PROVIDER, "llm_model": LLM_MODEL},
        "ticket": {"id": ticket.id, "status_check": "open"},
        "customer": None,
        "memory": None,
        "jev": None,
        "jev_meta": None,
        "policy": None,
        "route": None,
        "specialist": None,
        "priority": None,
        "tool_calls": [],
        "human_case": None,
        "reply": None,
    }
# ============================================================
# MAIN CUSTOMER SUPPORT PIPELINE
# ============================================================
def handle_customer_ticket(
    ticket: Ticket,
) -> dict[str, Any]:
    trace = new_trace(ticket)
    # ========================================================
    # 1. DETERMINISTIC CHECK
    #    A ticket can be closed by the caller or in memory.
    # ========================================================
    stored = db.get_ticket(ticket.id)
    if ticket.status == "closed" or (
        stored is not None and stored["status"] == "closed"
    ):
        trace["ticket"]["status_check"] = "closed"
        trace["route"] = "no_action"
        return {
            "route": "no_action",
            "ticket_id": ticket.id,
            "action": "ticket_already_closed",
            "trace": trace,
        }
    # ========================================================
    # 2. GET CUSTOMER
    # ========================================================
    customer = get_customer(ticket)
    if customer is None:
        db.ensure_ticket(ticket.id, None)
        db.add_message(ticket.id, "customer", ticket.message)
        human_case = create_human_case(
            ticket_id=ticket.id,
            reason="Sender email does not match a customer",
            priority="normal",
        )
        db.update_ticket(ticket.id, status="escalated", route="unknown_customer")
        db.add_message(ticket.id, "system", f"Escalated to a person: case {human_case['case_id']}.")
        trace["route"] = "unknown_customer"
        trace["human_case"] = human_case
        return {
            "route": "unknown_customer",
            "ticket_id": ticket.id,
            "human_case": human_case,
            "trace": trace,
        }
    open_orders = [o for o in customer.orders if o["status"] not in ("delivered", "cancelled", "returned")]
    trace["customer"] = {
        "id": customer.id,
        "name": customer.name,
        "plan": customer.plan,
        "open_orders": [o["id"] for o in open_orders],
    }
    # ========================================================
    # 3. LOAD MEMORY
    #    Read BEFORE saving the new message, so "conversation"
    #    means earlier turns and history excludes this ticket.
    # ========================================================
    db.ensure_ticket(ticket.id, customer.id)
    conversation = db.get_messages(ticket.id, limit=MEMORY_MAX_TURNS)
    history = db.get_customer_history(
        customer_id=customer.id,
        exclude_ticket_id=ticket.id,
        days=HISTORY_WINDOW_DAYS,
        max_tickets=HISTORY_MAX_TICKETS,
    )
    db.add_message(ticket.id, "customer", ticket.message)
    trace["memory"] = {
        "turns_remembered": len(conversation),
        "conversation": conversation,
        "history": history,
    }
    # ========================================================
    # 4. BUILD FOCUSED CONTEXT
    # ========================================================
    state = build_focused_context(
        ticket=ticket,
        customer=customer,
        history=history,
        conversation=conversation,
    )
    # ========================================================
    # 5. JEV
    # ========================================================
    jev_response = analyze_with_jev(state)
    answers = jev_response.answers
    trace["jev"] = serialize_answers(answers)
    usage = getattr(jev_response, "usage", None)
    trace["jev_meta"] = {
        "model": getattr(jev_response, "model", None) or "local stand-in",
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
    }
    # ========================================================
    # 6. PYTHON COMPOSITION
    # ========================================================
    spam_risk = calculate_spam_risk(answers)
    repeat_contact = is_repeat_contact(answers, history)
    human_review = requires_human_review(answers, spam_risk)
    trace["policy"] = {
        "spam_risk": round(spam_risk, 4),
        "spam_weights": {"requests_credentials": 0.45, "sender_identity_mismatch": 0.30, "unexpected_reward": 0.25},
        "topic_ok": answers["topic"].confidence >= TOPIC_MIN_CONFIDENCE,
        "spam_uncertain": SPAM_LOW < spam_risk < SPAM_HIGH,
        "quarantine": (not human_review) and spam_risk >= SPAM_HIGH,
        "human_review": human_review,
        "repeat_contact": repeat_contact,
        "contacts_last_7_days": history["contacts_last_7_days"],
        "refund_ok": answers["refund_requested"].noul >= NOUL_ACTION_THRESHOLD,
        "priority": determine_priority(answers, history),
        "thresholds": {
            "topic_min_confidence": TOPIC_MIN_CONFIDENCE,
            "spam_low": SPAM_LOW,
            "spam_high": SPAM_HIGH,
            "noul_action": NOUL_ACTION_THRESHOLD,
            "high_frustration_score": HIGH_FRUSTRATION_SCORE,
            "repeat_contact_min": REPEAT_CONTACT_MIN,
        },
    }
    # ========================================================
    # 7. CONFIDENCE GATE
    # ========================================================
    if human_review:
        human_case = create_human_case(
            ticket_id=ticket.id,
            reason=(
                "Low-confidence classification "
                "or ambiguous spam risk"
            ),
            priority="high" if repeat_contact else "normal",
            customer_id=customer.id,
        )
        db.update_ticket(
            ticket.id,
            status="escalated",
            topic=answers["topic"].choice,
            route="human_review",
            priority=human_case["priority"],
        )
        db.add_message(ticket.id, "system", f"Escalated to a person: case {human_case['case_id']}.")
        trace["route"] = "human_review"
        trace["priority"] = human_case["priority"]
        trace["human_case"] = human_case
        return {
            "route": "human_review",
            "ticket_id": ticket.id,
            "spam_risk": spam_risk,
            "topic": answers["topic"].choice,
            "topic_confidence": answers["topic"].confidence,
            "repeat_contact": repeat_contact,
            "human_case": human_case,
            "trace": trace,
        }
    # ========================================================
    # 8. SPAM
    # ========================================================
    if spam_risk >= SPAM_HIGH:
        db.update_ticket(ticket.id, status="quarantined", route="spam_quarantine")
        db.add_message(ticket.id, "system", "Quarantined as likely spam or phishing.")
        trace["route"] = "spam_quarantine"
        return {
            "route": "spam_quarantine",
            "ticket_id": ticket.id,
            "spam_risk": spam_risk,
            "action": "quarantined",
            "trace": trace,
        }
    # ========================================================
    # 9. SPECIALIST
    # ========================================================
    specialist = determine_specialist(answers)
    # ========================================================
    # 10. PRIORITY (frustration OR verified repeat contact)
    # ========================================================
    priority = determine_priority(answers, history)
    trace["route"] = "specialist"
    trace["specialist"] = specialist
    trace["priority"] = priority
    # ========================================================
    # 11. CLAUDE + TOOLS
    # ========================================================
    customer_response = run_claude_agent(
        ticket=ticket,
        customer=customer,
        answers=answers,
        specialist=specialist,
        priority=priority,
        history=history,
        conversation=conversation,
        tool_trace=trace["tool_calls"],
    )
    trace["reply"] = customer_response
    # ========================================================
    # 12. SAVE TO MEMORY
    # ========================================================
    db.add_message(ticket.id, "agent", customer_response)
    db.update_ticket(
        ticket.id,
        status="awaiting_customer",
        topic=answers["topic"].choice,
        route="specialist",
        specialist=specialist,
        priority=priority,
    )
    # ========================================================
    # 13. FINAL RESPONSE
    # ========================================================
    return {
        "route": "specialist",
        "ticket_id": ticket.id,
        "specialist": specialist,
        "priority": priority,
        "topic": answers["topic"].choice,
        "topic_confidence": answers["topic"].confidence,
        "spam_risk": spam_risk,
        "repeat_contact": repeat_contact,
        "contacts_last_7_days": history["contacts_last_7_days"],
        "turns_remembered": len(conversation),
        "customer_response": customer_response,
        "trace": trace,
    }
# ============================================================
# EXAMPLE: two turns on the same ticket
# ============================================================
def print_result(title: str, result: dict[str, Any]) -> None:
    print("\n==============================")
    print(title)
    print("==============================")
    for key, value in result.items():
        if key != "trace":
            print(f"{key}: {value}")
if __name__ == "__main__":
    # Turn 1: Jane's history already has three contacts about
    # A-104 this week, so memory can confirm the repeat contact.
    first = Ticket(
        id="TICKET-12345",
        message=(
            "I've contacted support three times "
            "about order A-104. Nobody has helped me. "
            "I'm extremely frustrated. "
            "Can you please tell me where my order is?"
        ),
        sender_name="Jane Smith",
        sender_email="jane@example.com",
        links=[],
        status="open",
    )
    print_result("TURN 1", handle_customer_ticket(first))
    # Turn 2: a follow-up on the SAME ticket. "it" only makes
    # sense because the earlier turns are replayed to Claude.
    follow_up = Ticket(
        id="TICKET-12345",
        message="Thanks! Will I need to sign for it when it arrives?",
        sender_name="Jane Smith",
        sender_email="jane@example.com",
        links=[],
        status="open",
    )
    print_result("TURN 2", handle_customer_ticket(follow_up))
