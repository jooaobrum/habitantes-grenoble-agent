"""Manual smoke test — runs against real OpenAI + Qdrant.

Each scenario uses an isolated chat_id so session state never bleeds.

Usage:
    QDRANT_URL=http://localhost:6333 python smoke_test.py

    # Run a single scenario by name substring:
    QDRANT_URL=http://localhost:6333 python smoke_test.py "number"
"""

import os
import sys
import uuid

sys.path.insert(0, "api/src")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")

import habitantes.domain.agent as agent  # noqa: E402


# ── Helpers ────────────────────────────────────────────────────────────────────


def _turn(chat_id: str, message: str, label: str = "") -> dict:
    tag = f"[{label}]  " if label else ""
    print(f"\n  👤  {tag}{message!r}")
    result = agent.run(
        chat_id=chat_id,
        message=message,
        message_id=f"msg-{uuid.uuid4().hex[:6]}",
        trace_id=f"trace-{uuid.uuid4().hex[:6]}",
    )
    print(
        f"  🤖  intent={result['intent']}  "
        f"category={result['category'] or '—'}  "
        f"confidence={result['confidence']:.2f}  "
        f"sources={len(result['sources'])}"
    )
    if result.get("error"):
        print(f"  ⚠️  ERROR: {result['error']}")
    # Print answer, indented
    for line in result["answer"].splitlines():
        print(f"      {line}")
    return result


# ── Scenarios ──────────────────────────────────────────────────────────────────
#
# Each scenario is a list of (label, message) turns that share one chat_id,
# so the memory/category selected in turn N is visible in turn N+1.

SCENARIOS = [
    {
        "name": "A — Greeting",
        "desc": "Bot shows the numbered category menu.",
        "turns": [
            ("greeting", "Olá, tudo bem?"),
        ],
    },
    {
        "name": "B — Direct question (no category selection)",
        "desc": "User skips the menu and asks directly. Search runs with no category filter.",
        "turns": [
            ("direct-qa", "Como renovar o titre de séjour em Grenoble?"),
        ],
    },
    {
        "name": "C — Number selection → question",
        "desc": "User picks a category by number, bot asks for the question; "
        "second turn uses the selected category as Qdrant filter.",
        "turns": [
            ("pick category 1 (Visa)", "1"),
            ("ask question", "Como renovar o titre de séjour?"),
        ],
    },
    {
        "name": "D — Greeting → number → question",
        "desc": "Full 3-turn happy path: greeting, category pick, question.",
        "turns": [
            ("greeting", "Olá!"),
            ("pick category 3 (CAF)", "3"),
            ("ask question", "Como conseguir a CAF?"),
        ],
    },
    {
        "name": "E — Category switch mid-conversation",
        "desc": "User picks one category, then picks a different one before asking.",
        "turns": [
            ("pick category 1 (Visa)", "1"),
            ("change mind → category 4", "4"),
            ("ask question", "Como registrar na Sécurité Sociale?"),
        ],
    },
    {
        "name": "F — Out of scope",
        "desc": "Bot declines questions unrelated to life in Grenoble.",
        "turns": [
            ("off-topic", "Qual é a capital do Japão?"),
        ],
    },
    {
        "name": "G — Feedback",
        "desc": "Emoji or text feedback is acknowledged without search.",
        "turns": [
            ("feedback", "👍"),
        ],
    },
    {
        "name": "H — Short message (clarification)",
        "desc": "Message too short for meaningful search → bot asks for more detail.",
        "turns": [
            ("too-short", "visto"),
        ],
    },
    {
        "name": "I — Greeting resets category",
        "desc": "After picking a category, a new greeting clears the selection.",
        "turns": [
            ("pick category 1", "1"),
            ("new greeting", "Olá novamente!"),
            ("direct question", "Como abrir conta no banco?"),
        ],
    },
]


# ── Runner ─────────────────────────────────────────────────────────────────────


def main(filter_name: str = "") -> None:
    selected = [s for s in SCENARIOS if filter_name.lower() in s["name"].lower()]
    if not selected:
        print(f"No scenarios matching {filter_name!r}")
        sys.exit(1)

    print("=" * 70)
    print("SMOKE TEST — habitantes-grenoble-agent")
    print("=" * 70)

    passed = failed = 0
    for scenario in selected:
        chat_id = f"smoke-{uuid.uuid4().hex[:8]}"
        print(f"\n{'─' * 70}")
        print(f"  {scenario['name']}")
        print(f"  {scenario['desc']}")
        print(f"  chat_id = {chat_id}")
        print(f"{'─' * 70}")
        try:
            for label, message in scenario["turns"]:
                _turn(chat_id=chat_id, message=message, label=label)
            passed += 1
        except Exception as exc:
            print(f"\n  ❌ EXCEPTION: {exc}")
            failed += 1

    print(f"\n{'═' * 70}")
    print(f"  {passed} passed  {failed} failed  ({len(selected)} scenarios total)")
    print("=" * 70)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    filter_name = sys.argv[1] if len(sys.argv) > 1 else ""
    main(filter_name)
