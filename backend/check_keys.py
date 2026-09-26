"""
KEY CHECK

Makes one small live call to each provider with the keys in
backend/.env, so you know before starting the app whether
Jev and the LLM will run live.

    python check_keys.py

Exits with status 1 if any configured key fails.
"""
from __future__ import annotations

import os
import sys

import env  # noqa: F401  loads backend/.env
import groq_llm

TICKET = "I was charged twice for order A-101. Please refund the duplicate."


def check_jev() -> tuple[bool, str]:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        return False, "TYPESAFE_API_KEY is not set in backend/.env"
    try:
        from typesafe_sdk import Noul, RetryPolicy, TypeSafeClient, TypeSafeError
    except ImportError:
        return False, "typesafe-sdk is not installed: pip install -r requirements.txt"
    try:
        with TypeSafeClient(retry=RetryPolicy(max_retries=1), timeout=30.0) as client:
            response = client.system_one(
                model=os.environ.get("JEV_MODEL", "jev-latest"),
                state=TICKET,
                questions={"refund": Noul(instructions="Does the customer ask for a refund?")},
            )
    except TypeSafeError as exc:
        return False, str(exc)
    return True, f"{response.model}, refund noul {response.answers['refund'].noul:.2f}"


def check_groq() -> tuple[bool, str]:
    if not groq_llm.groq_available():
        return False, "GROQ_API_KEY is not set in backend/.env (or openai is not installed)"
    try:
        client = groq_llm.GroqLLMClient(max_retries=1)
        reply = client.messages.create(
            max_tokens=256,
            system="Reply in five words or fewer.",
            messages=[{"role": "user", "content": "Greet a customer named Jane."}],
        )
    except Exception as exc:  # openai raises several error types
        return False, f"{type(exc).__name__}: {exc}"
    text = " ".join(b.text for b in reply.content if b.type == "text").strip()
    return True, f"{client.model}: {text[:80]}"


if __name__ == "__main__":
    failed = False
    for label, check in (("Jev (TypeSafe)", check_jev), ("LLM (Groq)", check_groq)):
        ok, detail = check()
        failed |= not ok
        print(f"{label:<16}{'OK  ' if ok else 'FAIL'}  {detail}")
    sys.exit(1 if failed else 0)
