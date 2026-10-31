# Project Guide

A reference for how this project is put together and what every part does. The [README](../README.md) gives the overview and quick start; this guide explains each component in detail, so you can run, change, or extend the project without reading all the code first.

> JBank is a fictional bank. All customers, accounts, transactions, and policies in this repository are synthetic.

**Contents**
1. [Status](#1-status)
2. [How the pieces fit together](#2-how-the-pieces-fit-together)
3. [Repository layout](#3-repository-layout)
4. [Infrastructure (Docker Compose)](#4-infrastructure-docker-compose)
5. [Relational data (PostgreSQL)](#5-relational-data-postgresql)
6. [Knowledge base (policy documents)](#6-knowledge-base-policy-documents)
7. [RAG pipeline](#7-rag-pipeline)
8. [Configuration reference](#8-configuration-reference)
9. [Common tasks](#9-common-tasks)
10. [Troubleshooting](#10-troubleshooting)
11. [Planned components](#11-planned-components)

---

## 1. Status

| Component | State |
|---|---|
| Docker stack (Postgres, Qdrant, Ollama) | Built |
| Synthetic data (schema + seed script) | Built |
| Policy documents with metadata | Built |
| RAG pipeline (chunk, embed, store, retrieve) | Built |
| Mock bank API (FastAPI) | Planned |
| Agent (LangGraph) and chat UI (Streamlit) | Planned |
| Evaluation harness | Planned |
| Jurisdiction-aware, role-based retrieval across countries | Planned (stretch); the metadata and filters it needs already exist |
| Neo4j fraud graph | Planned (stretch) |

Everything in sections 2 to 10 describes what exists today. Section 11 describes what is not built yet.

---

## 2. How the pieces fit together

```
                       ┌──────────────────────────────────────────┐
                       │              Docker Compose              │
                       │                                          │
 data/policy_docs/*.md │   ┌──────────┐   ┌──────────┐            │
        │              │   │  Ollama  │   │  Qdrant  │  vector DB │
        ▼              │   │ (models) │   │ (vectors)│            │
  agent/rag/ingest ────┼──►│ embeds   │──►│ stores   │            │
                       │   └──────────┘   └────▲─────┘            │
 question + role       │                       │ filtered search  │
        │              │                       │                  │
        ▼              │                       │                  │
  agent/rag/retriever ─┼───────────────────────┘                  │
                       │                                          │
 data/seed/seed.py ────┼──►  ┌────────────┐                       │
                       │     │ PostgreSQL │  customers, accounts, │
                       │     │            │  cards, transactions  │
                       │     └────────────┘                       │
                       └──────────────────────────────────────────┘
```

There are two separate sources of information, and keeping them separate is deliberate:

- **Knowledge base (Qdrant):** unstructured policy text that anyone may need to quote ("What is the wire transfer fee?"). Found by *meaning*, through semantic search.
- **Account data (PostgreSQL):** structured facts about one specific customer ("What is my balance?"). Found by *exact lookup*, through the API that will be built on top of it.

The future agent chooses between these (and escalation to a human) for each message.

---

## 3. Repository layout

```
.
├── docker-compose.yml        Defines all containers, ports, and volumes
├── requirements.txt          Python dependencies (pinned)
├── .env.example              Documented configuration values (copy to .env)
├── .gitignore                Keeps secrets, caches, and generated exports out of git
├── README.md                 Overview and quick start
├── agent/
│   └── rag/                  The retrieval pipeline (section 7)
│       ├── config.py         Settings and defaults
│       ├── embeddings.py     Text -> vectors via Ollama
│       ├── store.py          Shared Qdrant client
│       ├── chunker.py        Markdown docs -> chunks with metadata
│       ├── ingest.py         Chunk, embed, and load into Qdrant
│       ├── retriever.py      Filtered semantic search
│       └── test_retrieval.py Manual retrieval quality check
├── data/
│   ├── policy_docs/          The knowledge base (section 6)
│   └── seed/
│       ├── schema.sql        Table definitions (section 5)
│       └── seed.py           Generates synthetic customers and transactions
├── docs/                     Documentation (this guide)
├── api/  eval/  ui/          Reserved for planned components
```

---

## 4. Infrastructure (Docker Compose)

`docker compose up -d` starts everything. Containers are named `banking_*`.

| Service | Image | Host port | Purpose |
|---|---|---|---|
| `postgres` | `postgres:16` | **5433** | Relational data (customers, accounts, cards, transactions) |
| `qdrant` | `qdrant/qdrant:latest` | 6333 (REST + dashboard), 6334 (gRPC) | Vector database for the policy documents |
| `ollama` | `ollama/ollama:latest` | **11435** | Runs the language models locally: `nomic-embed-text` for embeddings, `mistral` for chat |
| `ollama-init` | `curlimages/curl:latest` | none | One-shot helper: waits until Ollama is healthy, pulls both models, then exits |

**Why ports 5433 and 11435?** Inside Docker the services use their standard ports (5432 and 11434). On your machine, those standard ports may already be taken by a native PostgreSQL or Ollama installation, so the containers are published on 5433 and 11435 to avoid the clash.

**Storage.** Data lives in named Docker volumes, so it survives restarts: `postgres_data`, `qdrant_data`, and `ollama_data` (Docker prefixes them with the project folder name, e.g. `bankingsupportagent_postgres_data`). The `ollama_data` volume holds the models (about 4.7 GB), which is why `docker compose down -v` should be avoided: `-v` deletes all volumes, including the models.

**Startup order.** `ollama-init` only starts once Ollama's healthcheck passes. The first run takes several minutes while the models download; later runs are near-instant.

**Auto-created tables.** `data/seed/schema.sql` is mounted into Postgres's init folder, so a fresh clone gets its tables automatically the first time the database volume is created. An existing volume does not re-run it (see section 9 to apply it by hand).

**Commented-out placeholders.** `docker-compose.yml` contains disabled blocks for Neo4j, the API, and the UI, to be enabled as those components are built.

---

## 5. Relational data (PostgreSQL)

Defined in `data/seed/schema.sql`. Running that file **drops and recreates** all four tables, so it doubles as a reset.

### Tables

**`customers`**: one row per person.

| Column | Notes |
|---|---|
| `customer_id` | Primary key |
| `first_name`, `last_name`, `email` (unique), `phone` | Synthetic contact details |
| `country` | `US`, `MX`, or `ES`. The customer's jurisdiction; will decide which policy documents may be used for them |
| `date_of_birth`, `last4_ssn` | Synthetic values used only to simulate identity verification |
| `created_at` | Timestamp |

**`accounts`**: a customer has one or two.

| Column | Notes |
|---|---|
| `account_id`, `customer_id` | Primary key; foreign key to `customers` |
| `account_type` | `essential_checking`, `premier_checking`, `standard_savings`, `high_yield_savings` |
| `account_number` | Synthetic, unique |
| `balance_cents` | Balance in **cents** (integer), which avoids floating-point rounding errors |
| `currency` | `USD`, `MXN`, or `EUR`, following the customer's country |
| `status` | `active`, `frozen`, `closed` |
| `opened_at` | Timestamp |

**`cards`**: one debit card per account.

| Column | Notes |
|---|---|
| `card_id`, `account_id` | Primary key; foreign key to `accounts` |
| `card_last4` | Only the last four digits are ever stored |
| `card_type` | `debit` or `credit` |
| `status` | `active`, `frozen`, `replaced`, `expired` |
| `issued_at`, `expires_at` | Dates |

**`transactions`**: account history.

| Column | Notes |
|---|---|
| `transaction_id`, `account_id` | Primary key; foreign key to `accounts` |
| `amount_cents` | **Negative = money out** (purchase, withdrawal), **positive = money in** (deposit) |
| `merchant_name`, `category`, `description` | `category` is one of: groceries, dining, transfer, atm_withdrawal, deposit, subscription, utilities, online_shopping |
| `status` | `pending`, `posted`, `disputed`, `reversed` |
| `occurred_at` | Timestamp |

All tables use `ON DELETE CASCADE` from their parent, so deleting a customer removes their accounts, cards, and transactions. Indexes exist on the foreign keys and on `transactions.occurred_at`.

### The seed script (`data/seed/seed.py`)

Fills the tables with fake data using Faker:

- **30 customers**, spread across countries (about 60% US, 20% MX, 20% ES). Names and phone prefixes match the country (`+1`, `+52`, `+34`).
- **1 to 2 accounts per customer**, in the country's currency, with random balances between 5.00 and 25,000.00.
- **One debit card per account.**
- **15 transactions per account**, spread over the previous 90 days.
- **Reproducible:** the random generators use fixed seeds, so every run produces the same customers, accounts, and amounts. Dates (birth dates, card expiry, transaction timestamps) are relative to the day you run it.
- **One transaction:** if anything fails, everything rolls back and nothing is half-written.
- **Not idempotent:** running it twice adds a second set of customers. To reset, run `schema.sql` first (section 9).

Known simplification: balances are random and are not computed from the transaction history, so the two will not reconcile.

---

## 6. Knowledge base (policy documents)

Six markdown files in `data/policy_docs/`. They are the text the retrieval pipeline searches.

| File | Covers |
|---|---|
| `account_types_and_fees.md` | Account types, monthly fees, common fees, waivers |
| `overdraft_policy.md` | What an overdraft is, protection options, fees, grace period |
| `dispute_chargeback_process.md` | When and how to dispute a charge, timelines, outcomes, what automation may do |
| `card_replacement_policy.md` | Reasons for replacement, freeze rules, costs and timelines |
| `fraud_policy.md` | What counts as fraud, response protocol, mandatory escalation triggers |
| `interest_rate_faq.md` | Savings, checking, and CD rates; early-withdrawal penalties |

Several documents end with a section on what the automated system may and may not do. These are intentional: they put escalation and verification rules into retrievable text, so an answer can cite the rule it is following.

### Document format

Every document starts with a **front matter block** (YAML between `---` lines), followed by normal markdown:

```markdown
---
title: Fraud Policy
country: US
doc_type: customer_facing
allowed_roles: [support_agent, executive, compliance_officer]
effective_date: 2026-01-01
version: "1.0"
---

# Fraud Policy

## First section
...
```

| Field | Meaning |
|---|---|
| `title` | Human-readable name; included in every chunk and shown as the citation |
| `country` | Jurisdiction the document applies to (`US`, `MX`, `ES`). Used as a search filter |
| `doc_type` | Kind of document. Today only `customer_facing`; internal-only documents are planned |
| `allowed_roles` | Which staff roles may retrieve this document. Used as a search filter |
| `effective_date`, `version` | When the content took effect and which revision it is; returned with every result so answers can be traced |

**Rules for adding or editing a document:**
- All six fields are required. Ingestion stops with a clear error naming the file and the missing fields.
- Content is split at `## ` headings, so give each topic its own `##` section. Text before the first `##` (the title and disclaimer) is not indexed.
- Keep each section self-contained, since it is retrieved on its own.
- After any change, re-run ingestion (section 9).

---

## 7. RAG pipeline

RAG (retrieval-augmented generation) means the agent looks up approved text before answering, instead of answering from the model's memory. This pipeline is the "look up" half. It lives in `agent/rag/`.

### Data flow

```
Ingest (offline)                                  Retrieve (per question)
────────────────                                  ───────────────────────
policy_docs/*.md                                  question + role (+ country)
   │ chunker.py                                      │ embeddings.py
   ▼                                                 ▼
chunks + metadata                                 question vector
   │ embeddings.py                                   │ retriever.py
   ▼                                                 ▼
vectors                                           Qdrant search with filters
   │ ingest.py                                       │
   ▼                                                 ▼
Qdrant collection "policy_docs"                   ranked chunks with scores and sources
```

### Modules

| File | What it does |
|---|---|
| `config.py` | Reads settings (service addresses, model name, collection name) from environment variables, with defaults for running on the host. See section 8 |
| `embeddings.py` | Converts text to vectors with Ollama. Adds the prefixes `nomic-embed-text` expects: `search_document: ` for chunks and `search_query: ` for questions. Other models can be added with their own prefixes |
| `store.py` | Creates one shared Qdrant client |
| `chunker.py` | Reads each document, validates and strips the front matter, splits at `## ` headings, and builds one chunk per section |
| `ingest.py` | Runs chunker, then embeddings, then loads Qdrant |
| `retriever.py` | `retrieve()`: the search function the agent will call |
| `test_retrieval.py` | Manual check of retrieval quality and filter behaviour (section 9) |

### Chunks

One chunk is one `##` section. Its text is prefixed with the document title and section header (for example, `Fraud Policy - Immediate Response Protocol`), so it still makes sense when shown on its own. Each chunk is stored in Qdrant with this payload:

| Field | Meaning |
|---|---|
| `text` | The chunk text (what is embedded and shown) |
| `doc_id`, `source_file` | Which document it came from (file name without extension; path relative to `data/policy_docs/`) |
| `title`, `section`, `chunk_index` | Document title, section header, and position in the document |
| `country`, `doc_type`, `allowed_roles`, `effective_date`, `version` | Copied from the front matter |

Chunk IDs are generated from the file path and section header, so the same section always gets the same ID.

### Ingestion (`python -m agent.rag.ingest`)

1. Chunks every `.md` file under `data/policy_docs/` (including subfolders).
2. Embeds all chunks with `nomic-embed-text` (768 dimensions, cosine similarity).
3. **Deletes and recreates** the Qdrant collection `policy_docs`, so it always matches the files on disk. There are no stale chunks if a section is renamed or removed, and it is safe to run repeatedly.
4. Creates search indexes on `country`, `doc_type`, and `allowed_roles`.
5. Prints the number of chunks per document.

The vector size is read from the model, not hardcoded, so switching embedding models only requires re-running ingestion.

### Retrieval (`retrieve()` in `retriever.py`)

```python
from agent.rag.retriever import retrieve

results = retrieve(
    "What is the fee for an international wire transfer?",
    role="support_agent",     # required
    country="US",             # optional
    top_k=4,                  # optional, default 4
    score_threshold=None,     # optional minimum similarity
)
```

| Parameter | Meaning |
|---|---|
| `query` | The question, in natural language |
| `role` | **Required.** Only chunks whose `allowed_roles` include this role are searched. There is deliberately no way to search without saying who is asking |
| `country` | Optional. If given, only chunks for that jurisdiction are searched |
| `top_k` | How many chunks to return |
| `score_threshold` | Optional. Drops matches below this similarity (cosine, roughly 0 to 1) |

**Returns** a list ordered best-first. Each item has: `score`, `text`, `doc_id`, `source_file`, `title`, `section`, `country`, `doc_type`, `version`, `effective_date`.

**Filtering happens inside the search query**, not afterwards. Chunks the caller may not see are never ranked or returned, so they cannot leak into an answer.

**An empty list means nothing matched** (wrong role, a country with no documents, or everything below the threshold). Callers must treat this as "not found" and say so, not fall back to another country's documents or to the model's own knowledge.

### Measured retrieval quality

From `test_retrieval.py` on the current six documents (12 answerable and 5 unanswerable questions):

| Measure | Result |
|---|---|
| Right document ranked first (hit@1) | 11 of 12 |
| Right document in the top 3 (hit@3) | 12 of 12 |
| Top score on answerable questions | 0.693 or higher |
| Top score on unanswerable questions | 0.613 or lower |
| Provisional "not found" threshold | about 0.65, to be validated with harder questions in the evaluation phase |

The one question not ranked first was "Someone used my card without my permission": the lost/stolen card section (0.693) edged out the fraud policy (0.670). Fraud and unauthorized-use language will therefore be handled as an explicit escalation signal in the agent, not left to retrieval ranking.

---

## 8. Configuration reference

Python code reads **environment variables** and falls back to the defaults below, which are correct for running scripts on your own machine against the Docker containers. Nothing loads the `.env` file automatically yet; it documents the values that containers will use once the API and UI are added.

| Variable | Default | Used by |
|---|---|---|
| `POSTGRES_HOST` | `127.0.0.1` | `seed.py` |
| `POSTGRES_PORT` | `5433` | `seed.py` |
| `POSTGRES_DB` | `banking_db` | `seed.py` |
| `POSTGRES_USER` | `banking_user` | `seed.py` |
| `POSTGRES_PASSWORD` | `banking_pass` | `seed.py` |
| `QDRANT_HOST` | `127.0.0.1` | `agent/rag` |
| `QDRANT_PORT` | `6333` | `agent/rag` |
| `QDRANT_COLLECTION` | `policy_docs` | `agent/rag` |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11435` | `agent/rag` |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | `agent/rag` |

The Postgres credentials are local development defaults for synthetic data, not real secrets.

`OLLAMA_BASE_URL` is named that way on purpose: the native Ollama tools read `OLLAMA_HOST`, and sharing that name would cause conflicts.

### Which address to use

| Where your code runs | Postgres | Qdrant | Ollama |
|---|---|---|---|
| On your machine (scripts, notebooks) | `127.0.0.1:5433` | `127.0.0.1:6333` | `http://127.0.0.1:11435` |
| Inside a Docker container (later) | `postgres:5432` | `qdrant:6333` | `http://ollama:11434` |

---

## 9. Common tasks

Run commands from the project root, with your Python environment active.

**Start and stop**
```bash
docker compose up -d        # start everything
docker compose stop         # stop, keeping all data
docker compose ps           # see what is running
```
Avoid `docker compose down -v`: it deletes the volumes, including the downloaded models.

**First-time setup**
```bash
docker compose up -d
pip install -r requirements.txt
python data/seed/seed.py               # load synthetic customers and transactions
python -m agent.rag.ingest             # index the policy documents
python -m agent.rag.test_retrieval     # check retrieval
```

**Reset the database to a clean state** (replaces all customers, accounts, cards, and transactions):
```bash
docker compose exec -T postgres psql -U banking_user -d banking_db < data/seed/schema.sql
python data/seed/seed.py
```
On Windows `cmd`, use backslashes in the path: `data\seed\schema.sql`.

**Look at the data**
```bash
docker exec banking_postgres psql -U banking_user -d banking_db -c "SELECT country, COUNT(*) FROM customers GROUP BY country;"
```
The Qdrant dashboard at `http://localhost:6333/dashboard` lets you browse the stored chunks and their metadata.

**Add or change a policy document**
1. Create or edit the `.md` file in `data/policy_docs/` with a complete front matter block (section 6).
2. Run `python -m agent.rag.ingest`.
3. Run `python -m agent.rag.test_retrieval` and confirm the existing questions still pass. Add a question for the new content to `ANSWERABLE` in that file.

**Read the retrieval test output** (`python -m agent.rag.test_retrieval`)
- *Part 1:* each answerable question with its top three matches. `OK` means the right document ranked first, `top3` means it appeared lower, `MISS` means it did not appear.
- *Part 2:* the top score for questions the documents cannot answer. These should be clearly lower than the Part 1 scores.
- *Part 3:* filter checks. Every line should say `PASS`.

---

## 10. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `failed to connect to the docker API ... daemon` | Docker Desktop is not running. Start it and retry |
| `password authentication failed for user "banking_user"` when running a script | The script reached a native PostgreSQL on port 5432 instead of the container. Use port **5433** (the default in `seed.py`) |
| Ingestion fails with `front matter is missing [...]` | A policy document lacks required metadata. Add the listed fields (section 6) |
| Ingestion or retrieval cannot reach Ollama | Check `docker compose ps` shows `banking_ollama` as healthy and that you are using port **11435**, not 11434 |
| `retrieve()` returns an empty list | Expected if the role is not in the document's `allowed_roles`, no document exists for that country, or all matches fall below `score_threshold`. Treat as "not found" |
| `ValueError: role is required` | `retrieve()` must always be told who is asking |
| Seed script fails with `value too long for type character varying` | A generated value exceeds its column width. Check the column sizes in `schema.sql` |
| The first `docker compose up` seems stuck | The models are downloading (about 4.7 GB). Check progress with `docker compose logs ollama-init` |
| Windows console shows garbled characters | Run `chcp 65001` first. The test script already forces UTF-8 output |

---

## 11. Planned components

Not built yet. Listed so the intended shape is clear.

- **Mock bank API (FastAPI):** endpoints for balance, transactions, card freeze, dispute status, and identity verification, served from the PostgreSQL data, with API-key authentication, rate limiting, and an audit log of who asked for what.
- **Agent (LangGraph + local Mistral):** routes each message to one of four paths (answer from documents, fetch account data, escalate to a human, or decline as out of scope), requires identity verification before any account data is shown, and says "not found" when retrieval returns nothing.
- **Chat UI (Streamlit).**
- **Evaluation harness:** a test set scoring routing, tool selection, retrieval, and escalation, including harder negative questions to validate the "not found" threshold.
- **Jurisdiction-aware, role-based retrieval (stretch):** fictional Spain and Mexico documents with different rules, internal-only documents restricted by role, a multilingual embedding model, and side-by-side answers when a question spans countries. The metadata fields and retrieval filters it needs are already in place.
- **Neo4j fraud graph (stretch).**
