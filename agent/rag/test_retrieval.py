"""
Manual retrieval check. Run from the project root after ingesting:
    python -m agent.rag.test_retrieval

Part 1: questions the docs CAN answer. Reports whether the right document ranks
        first (hit@1) or in the top 3 (hit@3).
Part 2: questions the docs can NOT answer. Their top scores show where to set
        a "not found" threshold.
Part 3: sanity checks that the role and country filters actually exclude chunks.
"""

import sys

from .retriever import retrieve

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252

ROLE = "support_agent"

# (question, acceptable doc_ids)
ANSWERABLE = [
    ("What is the fee for an international wire transfer?", {"account_types_and_fees"}),
    ("How long does it take to get a replacement card if mine is stolen?", {"card_replacement_policy"}),
    ("Is there a monthly fee on Essential Checking and how do I avoid it?", {"account_types_and_fees"}),
    ("What happens if I overdraw my account?", {"overdraft_policy"}),
    ("How many days do I have to dispute a charge?", {"dispute_chargeback_process"}),
    ("What interest rate does the high-yield savings account pay?", {"interest_rate_faq"}),
    ("Someone used my card without my permission, what should I do?", {"fraud_policy", "dispute_chargeback_process"}),
    ("Can I get an overdraft fee refunded?", {"overdraft_policy"}),
    ("What is the penalty for withdrawing from a CD early?", {"interest_rate_faq"}),
    ("Do I need to verify my identity before freezing my card?", {"card_replacement_policy", "fraud_policy"}),
    ("How much does expedited card shipping cost?", {"card_replacement_policy"}),
    ("Would the bank ever tell me to move my money to a safe account?", {"fraud_policy"}),
]

NOT_ANSWERABLE = [
    "What's the weather like tomorrow?",
    "Who won the 2018 World Cup?",
    "How do I reset my online banking password?",
    "What are your branch opening hours?",
    "Can I trade cryptocurrency through my account?",
]


def short(result):
    return f"{result['score']:.3f}  {result['doc_id']} / {result['section']}"


def main():
    print("=" * 70)
    print(f"PART 1: answerable questions (role={ROLE})")
    print("=" * 70)
    hit1 = hit3 = 0
    top_scores_ok = []
    for question, expected in ANSWERABLE:
        results = retrieve(question, role=ROLE, top_k=3)
        ids = [r["doc_id"] for r in results]
        ok1 = bool(ids) and ids[0] in expected
        ok3 = any(i in expected for i in ids)
        hit1 += ok1
        hit3 += ok3
        top_scores_ok.append(results[0]["score"] if results else 0.0)
        print(f"\n[{'OK ' if ok1 else ('top3' if ok3 else 'MISS')}] {question}")
        print(f"       expected: {sorted(expected)}")
        for r in results:
            print(f"       {short(r)}")
    n = len(ANSWERABLE)
    print(f"\nhit@1: {hit1}/{n}   hit@3: {hit3}/{n}")

    print()
    print("=" * 70)
    print("PART 2: questions the docs cannot answer (top score should be LOW)")
    print("=" * 70)
    top_scores_bad = []
    for question in NOT_ANSWERABLE:
        results = retrieve(question, role=ROLE, top_k=1)
        top_scores_bad.append(results[0]["score"] if results else 0.0)
        print(f"\n{question}\n       {short(results[0]) if results else '(no results)'}")

    print(f"\nanswerable     top scores: min {min(top_scores_ok):.3f}  mean {sum(top_scores_ok)/len(top_scores_ok):.3f}")
    print(f"not answerable top scores: max {max(top_scores_bad):.3f}  mean {sum(top_scores_bad)/len(top_scores_bad):.3f}")
    if min(top_scores_ok) > max(top_scores_bad):
        mid = (min(top_scores_ok) + max(top_scores_bad)) / 2
        print(f"Scores separate cleanly. A starting threshold would be about {mid:.2f}.")
    else:
        print("Scores overlap: a single score threshold will misclassify some questions. Look at the lists above.")

    print()
    print("=" * 70)
    print("PART 3: filter checks")
    print("=" * 70)
    q = "What is the fee for a wire transfer?"
    checks = [
        ("role=support_agent, no country filter", retrieve(q, role="support_agent"), True),
        ("role=support_agent, country=US", retrieve(q, role="support_agent", country="US"), True),
        ("role=support_agent, country=MX (no MX docs yet)", retrieve(q, role="support_agent", country="MX"), False),
        ("role=intern (not allowed on any doc)", retrieve(q, role="intern"), False),
    ]
    for label, results, should_have_results in checks:
        passed = bool(results) == should_have_results
        print(f"[{'PASS' if passed else 'FAIL'}] {label}: {len(results)} result(s)")


if __name__ == "__main__":
    main()
