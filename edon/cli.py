"""EDON CLI — evaluate, audit, and manage governance from the terminal."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional


def _client(api_key: Optional[str] = None, base_url: Optional[str] = None):
    from .client import EdonClient
    return EdonClient(api_key=api_key, base_url=base_url, raise_on_block=False)


def cmd_ping(args) -> int:
    """Check if the EDON gateway is reachable."""
    c = _client(api_key=args.api_key, base_url=args.gateway)
    url = c.base_url
    ok = c.ping()
    if ok:
        print(f"✓ EDON gateway is healthy at {url}")
        return 0
    else:
        print(f"✗ EDON gateway unreachable at {url}", file=sys.stderr)
        return 1


def cmd_evaluate(args) -> int:
    """Evaluate a single action against the governance engine."""
    c = _client(api_key=args.api_key, base_url=args.gateway)

    try:
        payload = json.loads(args.payload) if args.payload else {}
    except json.JSONDecodeError as exc:
        print(f"Error: --payload must be valid JSON: {exc}", file=sys.stderr)
        return 1

    try:
        decision = c.evaluate(
            action_type=args.action_type,
            action_payload=payload,
            agent_id=args.agent_id or "edon-cli",
            intent_id=args.intent_id,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    verdict = decision.decision
    color = "\033[32m" if verdict == "ALLOW" else "\033[31m" if verdict == "BLOCK" else "\033[33m"
    reset = "\033[0m"

    print(f"\n{color}▶ {verdict}{reset}  ({decision.processing_latency_ms}ms)")
    print(f"  Reason:      {decision.decision_reason}")
    if decision.reason_code:
        print(f"  Code:        {decision.reason_code}")
    if decision.policy_version:
        print(f"  Policy:      v{decision.policy_version}")
    print(f"  Action ID:   {decision.action_id}")

    if decision.safe_alternative:
        print(f"\n  Safe alternative: {decision.safe_alternative.get('action_type')}")

    if decision.escalation_question:
        print(f"\n  Approval required: {decision.escalation_question}")

    print()
    return 0 if verdict == "ALLOW" else 1


def cmd_audit(args) -> int:
    """Query the audit trail."""
    import httpx

    api_key = args.api_key or os.environ.get("EDON_API_KEY") or os.environ.get("EDON_API_TOKEN")
    base_url = (args.gateway or os.environ.get("EDON_BASE_URL") or "https://edon-gateway.fly.dev").rstrip("/")

    params = {"limit": args.limit or 20}
    if args.agent_id:
        params["agent_id"] = args.agent_id
    if args.verdict:
        params["verdict"] = args.verdict

    try:
        with httpx.Client(base_url=base_url, headers={"X-EDON-TOKEN": api_key}, timeout=10.0) as http:
            resp = http.get("/audit/query", params=params)
        resp.raise_for_status()
        events = resp.json()
    except Exception as exc:
        print(f"Error fetching audit: {exc}", file=sys.stderr)
        return 1

    if not events:
        print("No audit events found.")
        return 0

    print(f"\n{'Timestamp':<26} {'Verdict':<10} {'Action':<30} {'Agent':<20} {'Reason Code'}")
    print("-" * 100)
    for ev in events:
        action = ev.get("action", {})
        tool = action.get("tool", ev.get("action_tool", "?"))
        op = action.get("op", ev.get("action_op", "?"))
        action_str = f"{tool}.{op}"

        verdict_raw = ev.get("verdict") or (ev.get("decision") or {}).get("verdict", "?")
        verdict = verdict_raw.upper() if verdict_raw else "?"
        color = "\033[32m" if verdict == "ALLOW" else "\033[31m" if verdict == "BLOCK" else "\033[33m"
        reset = "\033[0m"

        ts = (ev.get("timestamp") or ev.get("created_at") or "")[:19].replace("T", " ")
        agent = ev.get("agent_id") or (ev.get("context") or {}).get("agent_id", "?")
        reason = ev.get("reason_code") or (ev.get("decision") or {}).get("reason_code", "")

        print(f"{ts:<26} {color}{verdict:<10}{reset} {action_str:<30} {agent:<20} {reason}")

    print()
    return 0


def cmd_policy(args) -> int:
    """List or manage policy rules."""
    import httpx

    api_key = args.api_key or os.environ.get("EDON_API_KEY") or os.environ.get("EDON_API_TOKEN")
    base_url = (args.gateway or os.environ.get("EDON_BASE_URL") or "https://edon-gateway.fly.dev").rstrip("/")

    try:
        with httpx.Client(base_url=base_url, headers={"X-EDON-TOKEN": api_key}, timeout=10.0) as http:
            resp = http.get("/policy/rules")
        resp.raise_for_status()
        rules = resp.json()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not rules:
        print("No custom policy rules configured.")
        print("  Add rules at edoncore.com/console or via POST /policy/rules")
        return 0

    print(f"\n{'Priority':<10} {'Name':<30} {'Condition':<35} {'Action':<10} {'Enabled'}")
    print("-" * 90)
    for r in sorted(rules, key=lambda x: x.get("priority", 0)):
        tool = r.get("condition_tool", "*")
        op = r.get("condition_op", "*")
        condition = f"{tool}.{op}"
        enabled = "✓" if r.get("enabled") else "✗"
        color = "\033[32m" if r.get("action") == "ALLOW" else "\033[31m" if r.get("action") == "BLOCK" else "\033[33m"
        reset = "\033[0m"
        print(f"{r.get('priority', 0):<10} {r.get('name', ''):<30} {condition:<35} {color}{r.get('action', ''):<10}{reset} {enabled}")

    print()
    return 0


def cmd_packs(args) -> int:
    """List available policy packs."""
    import httpx

    api_key = args.api_key or os.environ.get("EDON_API_KEY") or os.environ.get("EDON_API_TOKEN")
    base_url = (args.gateway or os.environ.get("EDON_BASE_URL") or "https://edon-gateway.fly.dev").rstrip("/")

    try:
        with httpx.Client(base_url=base_url, headers={"X-EDON-TOKEN": api_key}, timeout=10.0) as http:
            resp = http.get("/policy-packs")
        resp.raise_for_status()
        packs = resp.json()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("\nAvailable policy packs:\n")
    for pack in packs:
        name = pack.get("name") or pack.get("preset_name", "unknown")
        desc = pack.get("description", "")
        risk = pack.get("risk_level", "")
        print(f"  {name:<25} [{risk}]  {desc}")
    print()
    return 0


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="edon",
        description="EDON Governance CLI — evaluate, audit, and manage AI governance",
    )
    parser.add_argument("--api-key", "-k", default=None, help="EDON API key (or set EDON_API_KEY)")
    parser.add_argument("--gateway", "-g", default=None, help="Gateway URL (or set EDON_BASE_URL)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # ping
    subparsers.add_parser("ping", help="Check gateway health")

    # evaluate
    p_eval = subparsers.add_parser("evaluate", aliases=["eval"], help="Evaluate an action")
    p_eval.add_argument("action_type", help="Action type in tool.operation format (e.g. email.send)")
    p_eval.add_argument("--payload", "-p", default=None, help="JSON action payload")
    p_eval.add_argument("--agent-id", default=None, help="Agent ID")
    p_eval.add_argument("--intent-id", default=None, help="Intent contract ID")

    # audit
    p_audit = subparsers.add_parser("audit", help="Query the audit trail")
    p_audit.add_argument("--limit", "-n", type=int, default=20, help="Number of events to show")
    p_audit.add_argument("--agent-id", default=None, help="Filter by agent")
    p_audit.add_argument("--verdict", default=None, help="Filter by verdict (ALLOW/BLOCK)")

    # policy
    subparsers.add_parser("policy", help="List custom policy rules")

    # packs
    subparsers.add_parser("packs", help="List available policy packs")

    args = parser.parse_args()

    handlers = {
        "ping": cmd_ping,
        "evaluate": cmd_evaluate,
        "eval": cmd_evaluate,
        "audit": cmd_audit,
        "policy": cmd_policy,
        "packs": cmd_packs,
    }

    handler = handlers.get(args.command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
