#!/usr/bin/env python3
"""Run one arbitrary question through the full agent and dump everything.

See tests/eval/EVAL_GUIDE.md step 2 (root-causing a failure). Useful when a case's
pass/fail flag isn't enough — you need to see the actual retrieved chunks, whether the
web tool fired, and the exact answer text, to tell a real behavior change from a
metric artifact (see the golden_v2_review.md and CHECKPOINT.md `travel-kbweb-01` story
for why this matters: an eval bucket can flip PASS/FAIL from a rewording alone).

Usage:
    python tests/eval/checkpoints/debug_single_question.py "Sua pergunta aqui?"
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT / "api" / "src"))

import uuid  # noqa: E402
from habitantes.domain import agent as agent_mod  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: debug_single_question.py "question text"')
        sys.exit(1)

    question = sys.argv[1]
    state = agent_mod.run(
        chat_id=f"debug-{uuid.uuid4().hex[:8]}",
        message=question,
        message_id=uuid.uuid4().hex,
        trace_id=uuid.uuid4().hex,
    )

    print("QUESTION:", question)
    print("INTENT:", state.get("intent"))
    print("\nANSWER:\n", state.get("answer"))
    print("\nSOURCES:")
    for s in state.get("sources", []):
        print(" -", s.get("category"), "|", s.get("text_snippet", "")[:150])
    print("\nCONTEXT CHUNKS (KB retrieval, excludes web):")
    for c in state.get("context_chunks", []):
        print(
            " -",
            c.get("thread_id"),
            c.get("category"),
            "|",
            (c.get("text") or "")[:200],
        )


if __name__ == "__main__":
    main()
