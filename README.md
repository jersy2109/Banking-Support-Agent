# Banking Support Agent — RAG + Tool-Calling AI Agent

A fictional-bank customer support agent that answers policy questions, pulls live account data, and knows when to escalate to a human — built to mirror how production AI customer-support systems are actually architected.

> ⚠️ **This project uses 100% synthetic data.** No real bank, customer, or account information is used anywhere. "Vedranta Bank" and all accounts/transactions are fictional, generated for demonstration purposes only.

---

## Why this project

Most "AI chatbot" demos are a single LLM call with a system prompt. Real production support agents need to:
- **Ground answers in approved sources** instead of letting the model guess at policy details
- **Call live systems** (account balances, card status, disputes) rather than hallucinate them
- **Know their own limits** — verify identity before sharing sensitive data, and escalate what they shouldn't handle alone
- **Be measurable** — "it seems to work" isn't good enough; routing and retrieval accuracy need to be tested like any other system

This project builds that full loop end-to-end: retrieval, tool-calling, guardrails, evaluation, and deployment — entirely with free, self-hosted tools.

---

## What it does

A customer messages the agent in a chat interface. The agent routes each message into one of four paths:

| Path | Example | What happens |
|---|---|---|
| **Answer from knowledge** | "What's your overdraft policy?" | Retrieves the relevant policy chunk via RAG and answers *only* from that source |
| **Needs account data** | "What's my balance?" | Verifies identity first (if not already verified this session), then calls the live mock bank API |
| **Needs escalation** | "I think someone stole my card" | Recognized as fraud/high-risk and handed off to a human, no attempt to resolve it directly |
| **Out of scope** | Anything not covered by policy docs or tools | Declines honestly instead of guessing |

Every decision the agent makes — which path it took, which document or tool it used — is logged, so the system's behavior can be inspected and evaluated, not just trusted.

---

## Architecture

```
┌─────────────────┐
│  Streamlit Chat  │
└────────┬─────────┘
         │
┌────────▼─────────────────────────────┐
│   LangGraph Agent (local Mistral)     │
│   Router: knowledge / data / escalate │
│          / out-of-scope               │
└───┬─────────────┬─────────────┬──────┘
    │              │              │
┌───▼────┐   ┌─────▼──────┐  ┌───▼─────────┐
│ Qdrant │   │  FastAPI    │  │  Neo4j      │
│ (RAG:  │   │  Mock Bank  │  │  (fraud     │
│ policy │   │  API        │  │  graph —    │
│ docs)  │   │  ┌────────┐ │  │  stretch    │
│        │   │  │Postgres│ │  │  goal)      │
│        │   │  └────────┘ │  │             │
└────────┘   └─────────────┘  └─────────────┘
```

All services run locally via Docker Compose — no paid APIs required.

---

## Tech stack

| Layer | Tool | Why |
|---|---|---|
| LLM | Mistral (local, via Ollama) | Free, runs entirely offline |
| Agent orchestration | LangGraph | Explicit state machine for routing, tool calls, and multi-turn identity verification |
| Vector database | Qdrant | Self-hosted, container-based retrieval for policy documents |
| Relational data | PostgreSQL | Accounts, customers, transactions, cards (seeded with synthetic data via Faker) |
| Mock banking API | FastAPI | Simulates the CRM/core-banking endpoints a real agent would call, with API-key auth and rate limiting |
| Graph database (stretch) | Neo4j | Fraud-pattern detection across linked accounts/devices |
| UI | Streamlit | Minimal chat interface |
| Eval | Custom harness (+ optional Ragas) | Scores routing accuracy, tool-call correctness, and retrieval relevance |
| Infra | Docker Compose, GitHub Actions | Reproducible local environment + CI on push |

---

## Guardrails

- **Identity verification** is required before any tool call touches account-specific data, and persists only within a session.
- **No answers outside the approved policy documents** — the agent is instructed to say "I don't know" rather than fill gaps with its own assumptions.
- **Escalation rules** trigger on fraud-related language, large transaction amounts, and repeated failed identity verification, routing the conversation to a human instead of attempting to resolve it.

---

## Evaluation

A 25–30 question test set covers all four routing categories, each with an expected route, expected tool call (if any), and expected source document (if any). The scoring script reports per-category accuracy so the agent's behavior is backed by numbers, not impressions.

*(Results will be added here once the eval suite is run — e.g., "92% correct routing, 88% correct tool selection, 100% escalation recall on fraud-flagged test cases.")*

---

## Project status

- [ ] Policy documents + Postgres schema
- [ ] Qdrant RAG pipeline
- [ ] Mock bank API (FastAPI)
- [ ] LangGraph agent + routing logic
- [ ] Streamlit chat UI
- [ ] Eval harness
- [ ] Neo4j fraud-graph (stretch)
- [ ] CI/CD + Azure deployment

---

## Running it locally

```bash
git clone <repo-url>
cd banking-support-agent
docker-compose up -d
# instructions for seeding data, running the agent, and launching the UI
# will be added as each phase is completed
```

---

## Disclaimer

This is a portfolio/learning project. "Vedranta Bank," its policies, account data, and transactions are entirely fictional and generated for demonstration purposes. Nothing in this repository represents real financial advice, real banking data, or production-grade compliance guidance.