# Multi-Tenant Agent Platform

One chat platform that hosts an AI agent for two client organisations. A customer of one organisation can never reach the other organisation's agent or data.

| | Org A: Himali Tea House | Org B: Lotus Wellness Studio |
| --- | --- | --- |
| Agent | **Ordering agent**: product questions, takes, edits, tracks and repeats orders | **Booking agent**: service questions, books, reschedules and cancels appointments without conflicts |
| Entry point | `/a/himali-tea` | `/a/lotus-wellness` |
| Stretch | Admin analytics agent (both orgs), a third organisation added by configuration alone (`/a/everest-gear`), long-term customer memory | |

Stack: FastAPI, SQLAlchemy (SQLite), Chroma + Gemini Embedding 2 for retrieval (BM25 fallback), Gemini / Mistral / Groq / Ollama / mock chat models behind one switch, React + Vite + Tailwind, Server-Sent Events for streaming.

Contents: [Setup](#1-setup-in-five-commands) · [Test logins](#2-test-logins) · [Architecture and tenant isolation](#3-architecture-and-tenant-isolation) · [Auth and sessions](#4-authentication-and-sessions) · [Key decisions](#5-key-decisions) · [Requirements checklist](#6-requirements-checklist) · [Eval results and failure analysis](#7-eval-results-and-failure-analysis) · [Another week](#8-what-i-would-do-with-another-week) · [AI tools](#9-how-i-used-ai-coding-tools) · [Demo script](#10-demo-script-58-minutes)

---

## 1. Setup in five commands

Needs Python 3.11+ and Node 20+. No API key is needed to run everything (the `mock` model and BM25 retrieval work offline).

```bash
make setup           # venv, backend + frontend dependencies, creates .env from .env.example
make seed            # rebuilds the database AND both knowledge bases from the seed files
make eval            # 112 scenarios, pass/fail per scenario, checks database state
make run-backend     # API on http://localhost:8000 (docs at /docs)
make run-frontend    # app on http://localhost:3000   (second terminal)
```

Open <http://localhost:3000/a/himali-tea> or <http://localhost:3000/a/lotus-wellness>.

Without `make` (for example plain Windows): `python -m venv backend/.venv`, `backend\.venv\Scripts\pip install -r backend/requirements.txt`, `cd frontend && npm install`, copy `.env.example` to `.env`, then use `python run.py seed`, `python run.py eval`, `python run.py backend` and `python run.py frontend`, which are the same commands.

**Docker** (one command): `cp .env.example .env && docker compose up --build`, then open <http://localhost:3000>. The container seeds an empty volume once (`seed.py --if-missing`) and keeps data across restarts. Run `docker compose exec backend python scripts/seed.py` to rebuild from the seed files.

**Using the real model.** Edit `.env`: `LLM_PROVIDER=gemini`, `GEMINI_API_KEY=...`, and for vector retrieval `EMBEDDING_PROVIDER=gemini`, then `make seed` again so the vectors are built. `LLM_PROVIDER` also accepts `mistral` (`MISTRAL_API_KEY`), `groq` (`GROQ_API_KEY`, free key from console.groq.com) and `ollama` (a local model, no key and no quota: install Ollama and run `ollama pull llama3.1:8b`). Mistral, Groq and Ollama share one OpenAI-compatible client, tested against a fake HTTP server in `tests/test_providers.py` (request shape, streamed tool calls, error messages). **Only Gemini has been run live end to end**; the other three are backups for when a free tier runs out and have not been verified against the real services. Gemini has its own adapter. A key alone never changes the provider. If one free tier runs out, switch the variable and restart: the agent, tools and tests do not change. The provider is one environment variable. Every variable is listed in [.env.example](.env.example).

Other commands: `make live-eval` (same checks against the real model), `make add-org` (adds the third organisation from `backend/app/seed_data/org_c_*`), `make advance-order ID=ORD-1003 STATUS=confirmed` (admin script that moves an order along, so tracking and the edit rules can be demonstrated).

## 2. Test logins

Password for every seeded account: `Password123!`. The sign-in page has one-click buttons for a customer and the admin of the organisation you are on.

| Organisation | Role | Email | What it is good for |
| --- | --- | --- | --- |
| Himali Tea House | customer | `aayush@himali.test` | Two past orders (`ORD-1001` confirmed, `ORD-1002` delivered): "same as last time", tracking, refused edits |
| Himali Tea House | customer | `priya@himali.test` | One **pending** order `ORD-1003`: edit address, cancel |
| Himali Tea House | customer | `kiran@himali.test` | No orders: first order, stock refusal |
| Himali Tea House | **admin** | `admin@himali.test` | Orders panel (advance status), analytics, admin chat |
| Lotus Wellness Studio | customer | `rohan@lotus.test` | Past booking `BKG-2001` and an **upcoming** `BKG-2003` with Master Tenzing: other customers cannot book or move into that slot |
| Lotus Wellness Studio | customer | `sita@lotus.test` | Past booking `BKG-2002`: book, reschedule into Rohan's slot (refused), cancel |
| Lotus Wellness Studio | customer | `bikash@lotus.test` | No bookings |
| Lotus Wellness Studio | **admin** | `admin@lotus.test` | Practitioner utilisation, cancellations |
| Everest Outdoor (after `make add-org`) | customer / admin | `climber@everest.test` / `admin@everest.test` | Third organisation |

Seed dates are relative to the day you run `make seed` (past bookings are always in the past, `BKG-2003` is always 2 to 4 days ahead), so the data never goes stale.

## 3. Architecture and tenant isolation

```
 Browser (React)  ──  /a/<org-slug> entry point, SSE stream ───────────────┐
                                                                            ▼
 FastAPI ── auth (bcrypt + signed token, revocable) ── rate limit (per user) ──► routes
     │
     ├─ chat route ──► AgentLoop (one tool-calling loop for retail, studio and admin)
     │                    │  tools come from a per-kind allowlist; org_id and user_id are injected by the SERVER
     │                    ├─ read tools ──► live SQL, knowledge search
     │                    └─ write tools ──► only STAGE an ActionProposal (summary card). Nothing is written.
     │
     └─ POST /api/actions/proposals/{id}/confirm ──► ActionService (the only writer)
              claim proposal once ► re-check price, stock, slot ► write, inside one BEGIN IMMEDIATE transaction

 SQLite (org_id on every row)         Chroma (org_id metadata, filtered in every query)
```

**How isolation is enforced.** Each layer is independent, so a mistake in one does not open the door:

1. **The organisation is fixed at the entry point.** Sign-up and login are bound to the organisation of the page (`/a/<slug>`); a user belongs to exactly one organisation. Logging in at the wrong entry point fails with the same message as a wrong password.
2. **The server never trusts the client for tenancy.** Headers, query strings and request bodies are ignored for `org_id`/`user_id`. The token carries them, and `get_current_user` re-reads the user from the database and requires that the token's `org_id` matches the row. The **role is read from the database**, not from the token.
3. **Every query is scoped** by `org_id`, and customer queries by `user_id` too. Someone else's order, booking, conversation or proposal is a **404, indistinguishable from a missing one** (no existence oracle).
4. **The model cannot choose the tenant.** Tool schemas contain no `org_id`/`user_id`; the dispatcher injects them from the session and strips them if a model supplies them. A tool outside the caller's allowlist is refused (customers cannot call admin tools, admins have no write tools at all).
5. **Knowledge search is scoped twice:** a `where={"org_id": ...}` filter in the vector query, then a per-hit check on the returned metadata. Retrieved text and customer memory are passed to the model as *untrusted data*.
6. **The frontend** shows a "Cross-Tenant Access Blocked" screen if a signed-in user opens another organisation's address. That is a convenience; the server does not rely on it.
7. **Admin is read-only and scoped.** `/api/admin/*` requires the admin role (customers get **403**), every query filters on the admin's own `org_id`, and the admin chat's tool list contains no write tool. A customer cannot open or use an admin conversation.

These are exercised by `tests/test_tenant_isolation.py` (15 tests that try to break isolation by URL, header, body, forged token, `alg: none`, role tampering, the vector path and the rate limit) plus the cross-user and cross-org scenarios inside each agent's suite.

### The agent loop, step by step ([agent_loop.py](backend/app/services/agent_loop.py))

I did not use an agent framework; the loop is one function, `AgentLoop.run_turn`, of about 150 lines:

1. Load the organisation and its `agent_kind` (`retail`, `studio` or admin). A customer asking for an admin chat gets nothing.
2. Save the user's message and, for a fresh chat, derive its title from it.
3. Build the model input: the system prompt (rules, and for the studio the current Kathmandu time), the customer's long-term memory as an *untrusted data* message, and the last 12 messages with a compact record of what earlier tools returned, so ids such as `srv_1` or an order id survive across turns.
4. Up to 5 rounds: stream the model. Text tokens go straight to the browser as SSE `token` events. Tool calls are checked against the allowlist and required arguments, emitted as `tool_start` ("Checking live products and stock..."), run with server-side `org_id`/`user_id`, and their results (trimmed, never dropped, if large) go back to the model. Citations and the card are captured from the results.
5. If a write tool staged a proposal, tools are switched off and the model writes the final sentence only. One confirmation card per message.
6. Save the agent message (text, tool activity, citations, card) and send `done`.

The provider layer ([llm_provider.py](backend/app/services/llm_provider.py)) hides Gemini, Mistral and the mock behind one stream interface. For Gemini it replays the SDK's original model `Content` (thought signatures included), retries across a fallback model list on 429/503/504, and streams the final answer.

## 4. Authentication and sessions

- **Passwords:** `bcrypt`, work factor 12, salted, never returned by any endpoint. Sign-up validates the email and a minimum length of 8, and always creates a `customer` (a `role` in the body is ignored).
- **Session:** a signed HS256 token (24 h) sent as `Authorization: Bearer`. **Why not a managed provider:** two fixed organisations and a take-home scope; a self-contained token keeps the project runnable with no external account. **Why not cookies:** the API is called from a single-page app and from `curl`; a Bearer header removes CSRF as a concern and keeps CORS strict (only the configured origins, no credentials).
- **Logout is real.** Each token has a `jti`. `POST /api/auth/logout` stores it in a revocation table, so that token stops working immediately everywhere, while the user's other sessions continue. Expired revocation rows are cleaned up on logout. The UI calls it, and returns to the entry point (with a notice) if a call ever comes back 401.
- **Brute force:** login and sign-up are throttled to 10 attempts a minute per client address and email (HTTP 429). The chat endpoint is limited to **20 messages a minute per user** (`RATE_LIMIT_PER_MINUTE`).
- **Trade-off I accept:** the token lives in `localStorage`, so an XSS bug would expose it. The mitigations are server-side revocation, a short life, and no raw HTML rendering (markdown is rendered by `react-markdown`). A production version would move it to an `HttpOnly` `SameSite` cookie with a CSRF token.
- **Secrets:** none in the repo. `.env` is git-ignored (verified: it was never committed), `SECRET_KEY` is required and cannot be blank, and `.env.example` lists every variable.

## 5. Key decisions

### Retrieval: chunking and embeddings
- **Chunking:** split on markdown headings (`#`, `##`, `###`). Each chunk is one self-contained unit: a single FAQ question with its answer, one policy, one brewing guide, one product, one practitioner bio. Fixed-size windows cut an answer from its question and a policy from its exceptions; heading chunks cannot. Every chunk keeps `doc_name` and `section_name`, which become the citation chip `faq.md › Q15: ...`. Org A: 56 chunks over 5 documents (about, shipping and returns, FAQ with 16 Q&As, brewing guides, product descriptions); Org B: 39 chunks over 5 documents (about, services, practitioner bios, cancellation and late policy, FAQ with 16 Q&As).
- **Model:** `gemini-embedding-2` (free tier, 3072 dimensions), stored in a persistent Chroma collection with **cosine** distance. Documents are embedded as `title: <section> | text: <chunk>` and queries as `task: search result | query: ...`, which is the format this model expects. One practical finding: this model merges a *list of strings into one vector*; each chunk must be sent as its own `Content` (a bug I hit and fixed, see section 7).
- **One retrieval path, not a fused hybrid.** Vector search when embeddings are on, **BM25** over the same chunks otherwise (and as a fallback if the embedding call fails). The result says which one answered.
- **"I don't know" is a retrieval property.** Both paths return nothing below a relevance floor. For vectors I **measured** it on 25 real questions (15 answerable, 10 not): answerable ones scored **0.69 to 0.82** cosine similarity (the right document came back every time), unanswerable ones **0.49 to 0.63**, so the floor is **0.66**. For BM25 a passage must contain at least half of the question's meaningful words (stopwords removed) and at least two when the question has two or more. Without this, "Who won the football world cup?" returned a caffeine FAQ with a citation.
- **Live data never comes from the knowledge base.** Prices, stock, order status, hours and availability are always read from SQL (the product descriptions document deliberately contains no prices). The tool result tells the model so.
- **Rebuild:** `make seed` drops the relational tables, resets the Chroma collection (no stale vectors survive), and re-ingests every `seed_data/<org_id>_knowledge/` folder.

### Scheduling: built, not integrated
I wrote the slot engine ([scheduling.py](backend/app/services/scheduling.py)) rather than wrap Cal.com or Google Calendar: the rules in the brief (opening hours, holidays, full-duration fit, practitioner and customer overlap, nearest alternatives) are domain logic I wanted under test, and it removes a network dependency from the booking path. Slots are generated on a 30-minute grid from the day's hours, with one query for the day's bookings instead of one per slot. A practitioner is only offered, and only bookable, for services on their specialty list. Slots in the past are never offered. Times are stored as studio wall-clock time and always shown in **Asia/Kathmandu (UTC+05:45)**; the UI formats with an explicit `timeZone`, so a visitor's browser zone cannot shift them. Relative phrases ("next Tuesday afternoon", "day after tomorrow at 3pm", "in 3 days") resolve against the Kathmandu clock, and the model is told the current studio time. If I integrated an external calendar I would keep it behind this same engine interface, treat its free/busy answer as advisory, re-check against my own table inside the write transaction, and on an outage refuse new bookings with a clear message while still serving reads from the last known state.

### Concurrency: how double bookings and overselling are prevented
- **Writes only happen in `ActionService.confirm`, inside one SQLite `BEGIN IMMEDIATE` transaction** (set on every transaction by an engine hook), so writers are serialised by the database itself and a waiting writer retries up to `SQLITE_BUSY_TIMEOUT_MS`, then gets HTTP 409.
- **The proposal is claimed with a single atomic `UPDATE ... WHERE status = 'pending' AND not expired`.** A double-click, a retry or a second tab confirms once; the others get "already confirmed".
- **Inside the same transaction** price, stock or the slot are re-checked. Stock uses `UPDATE products SET stock = stock - :qty WHERE stock >= :qty` and checks `rowcount`, so stock cannot go negative even without the lock. Bookings re-run the overlap check on the same connection that inserts.
- **If something changed after the card was shown:** a price change commits a *replacement* proposal (never charges the old total); a taken slot or sold-out item is a **409 Conflict**, writes nothing, and the explanation (with alternatives) is saved into the chat.
- **Proven by test:** two customers confirming the same slot at the same time through the API get exactly one `200` and one `409`; two sessions taking the last unit get exactly one order and stock `0`.
- **Limit:** this relies on SQLite's single-writer model on one host. On Postgres I would use `SELECT ... FOR UPDATE` and a `btree_gist` exclusion constraint on `(practitioner_id, tsrange(start, end))`, which moves the guarantee into the schema.

### Confirmation is a server-side gate, not a model behaviour
The brief says the agent shows a summary and waits for the customer. A prompt can be argued out of that, so the write tools **only stage** an `ActionProposal` (a stored, expiring, single-use, per-user record) and return a card. The model physically cannot place, change or cancel anything; only the Confirm button (`POST /api/actions/proposals/{id}/confirm`) writes. The `/api/orders` and `/api/bookings` write routes refuse direct calls. If a customer types "yes" in chat, the agent tells them to press Confirm.

## 6. Requirements checklist

| Requirement from the brief | Where it lives | Proven by |
| --- | --- | --- |
| Exactly one org per user, role `customer` or `admin` | `User.org_id`, `User.role`; sign-up fixes both | `test_signing_up_on_an_entry_point_fixes_the_organisation...` |
| Sign-up on the org's own entry point fixes `org_id` | `/a/<slug>` + bound sign-up form | same, and UI check "sign-up on the Lotus entry point creates an org_b customer" |
| Hashed passwords, login, logout, secure sessions | `security.py`, `auth.py`; section 4 | `test_auth.py` |
| Cannot reach the other org by URL, header or body | section 3 | `test_tenant_isolation.py` |
| KB search never returns another org's content | org filter plus per-hit check | `test_knowledge_search_never_returns...`, `test_vector_search_filters_by_org...` |
| Chat rate limit, no secrets in the repo, `.env.example` | `ratelimit.py`, `.gitignore` | `test_chat_endpoint_is_rate_limited_per_user` |
| Automated tests for cross-org and cross-user access | `backend/tests` | `make eval` |
| 2 seeded orgs, at least 20 products / 6 services, 3 practitioners, hours, holidays, 3 customers each | `seed_data/initial_records.json` | 22 products, 7 services, 3 practitioners, 4 holidays, 16 FAQs per org |
| KB documents incl. product descriptions, brewing guides, bios, FAQ of at least 15 Q&As | `seed_data/*_knowledge/` | 56 + 39 chunks |
| Citations with document and section | `citations` on every knowledge answer | `a01`, `a02`, `b01`, `b02` |
| One command to rebuild both knowledge bases | `make seed` | |
| **Agent A tools** `search_knowledge`, `search_products`, `create_order`, `update_order`, `cancel_order`, `get_order_status`, `list_my_orders`, `reorder` | [tool_registry.py](backend/app/services/tool_registry.py) | |
| A1 summary and confirm before placing or changing | proposal gate | `a05`, `a09`, `a12` |
| A2 quantity cannot exceed stock; offer an alternative | same-category alternatives | `a07`, `a08`, `a22` |
| A3 edit or cancel only while `pending`, with reason and status | `update_order`, `cancel_order` | `a11`, `a13`, `a18` |
| A4 a customer sees and acts on only their own orders | scoped queries, "not found" | `a14`, `a24` |
| A5 "same as last time" notes price and stock changes | `reorder` | `a16`, `a17` |
| A6 admin endpoint or script advancing status | `POST /api/admin/orders/{id}/advance_status`, `make advance-order` | `a18` |
| **Agent B tools** `search_knowledge`, `list_services`, `get_opening_hours`, `find_available_slots`, `create_booking`, `reschedule_booking`, `cancel_booking`, `list_my_bookings` | [tool_registry.py](backend/app/services/tool_registry.py) | |
| B1 inside hours, avoid holidays, fit the full duration | `validate_slot` | `b09`, `b10` |
| B2 no practitioner double booking, no customer overlap | `validate_slot`, serialised writes | `b11`, `b12` |
| B3 safe when two customers grab the same slot; explain how | section 5 | `b13` (real concurrent confirms) |
| B4 conflicting reschedule refused with nearest alternatives | `find_nearest_alternatives` | `b14` |
| B5 confirm service, practitioner, date, time and price | booking card | `b08` |
| B6 relative dates in studio time | `resolve_relative_datetime_kathmandu` | `b06`, `b07` |
| Cancellation policy applied | free at 4 hours or more, 50% below | `b16`, `b17` |
| Chat: org branding and agent greeting, lands in the chat after login | `LoginPage`, `ChatPage` | UI checks |
| Chat: sidebar with new, rename, delete | `Sidebar` (delete asks twice) | UI checks |
| Chat: markdown and code blocks, token-by-token streaming with **Stop** | `MessageThread`, SSE | UI checks "markdown renders", "Stop button ends one early" |
| Chat: visible tool activity and clickable citation chips | `tool_start` events, citation modal | UI check "citation chips open the source excerpt" |
| Chat: rich cards (order summary with Confirm, slot list, status cards) | `RichCards.tsx` | UI checks |
| Chat: "My orders" / "My bookings" panel matches the agent | `CustomerDrawer` | UI check "My Bookings panel matches" |
| Chat: Enter sends, Shift+Enter newline, empty / loading / error states, 375 px | `MessageThread` | UI checks at 375 px (no horizontal scroll) |
| Stretch: admin analytics with the four metrics, read-only, 403, scoping, windows and definitions | `admin_agent.py` | `adm01` to `adm14`, section 7 |
| Stretch: third organisation by configuration | `make add-org` | `test_the_third_organisation_works_end_to_end...` |
| Stretch: long-term memory | `CustomerMemory` | `a19`, `a20`, `b21` |
| Eval of 12+ scenarios per agent that checks the database | `make eval` | section 7 |

**Admin metrics and their definitions** (also shown in the admin UI and returned with every number):

| Metric | Retail | Studio |
| --- | --- | --- |
| Activity summary | Orders by current status; gross revenue and average order value over confirmed, shipped and delivered orders (pending and cancelled excluded) | Bookings by status, cancellations and cancellation rate, practitioner utilisation (non-cancelled sessions, booked hours, share) |
| Clients today | Customers who sent a chat message today, and accounts created today. "Today" is the **Asia/Kathmandu** day | same |
| Conversion rate | customer conversations started in the window that produced at least one **confirmed** order / all customer conversations started in the window. A staged but unconfirmed card does not count | same, with bookings |
| Top items | Top 5 products by units on non-cancelled orders; products with 5 or fewer units, ranked by past stock-outs | Most-booked services; busiest start hours (non-cancelled) |

Windows are rolling and printed with their start and end in studio time (`days` is limited to 1 to 365). Read-only is enforced by construction (the admin tool list has no write tool, tested by a model that tries `cancel_order`) and the admin API has no write route except the status advance the brief asks for.

## 7. Eval results and failure analysis

### How to run
`make eval` (or `python backend/scripts/run_eval.py`). It builds a **temporary database and vector folder from the seed files**, uses the deterministic `mock` model and BM25 retrieval (no network, no key, your development data is untouched), runs every scenario through the real stack (login, chat endpoint, tool loop, confirmation card, confirm endpoint), and asserts on **database state** afterwards. Every file starts from the seed again, and all dates are relative to today, so the suite does not depend on the day it runs or on the order of the files. Output is pass/fail per scenario grouped by agent; the counts below are what that command prints.

### Result of the final run: 112 of 112 scenarios passed

| Suite | Scenarios | Result |
| --- | ---: | --- |
| Agent A, Himali ordering | 26 | all passed |
| Agent B, Lotus booking | 27 | all passed |
| Admin analytics agent | 14 | all passed |
| Tenant isolation and access control | 15 | all passed |
| Auth, sessions, throttling, conversations | 10 | all passed |
| Confirmation gate and concurrency | 13 | all passed |
| Third organisation by configuration | 1 | passed |
| Chat provider adapters (Mistral, Groq, Ollama) | 6 | all passed |

Coverage required by the brief: knowledge answers with citations (`a01`, `a02`, `b01`, `b02`); questions the knowledge base cannot answer (`a03`, `b03`); the happy path (`a05`, `b08`); every business rule (table in section 6); **memory** (`a19`, `a20`, `b21`); edge cases (negative, zero and oversized quantities, unknown SKU, repeated SKUs, past times, closed hours, holidays, a practitioner who does not offer the service, expired and stale proposals); **cross-organisation access** (`a14`, `a24`, `b19`, `adm12`, plus the isolation file); **prompt injection** (`a23`, `b20`, `adm10`, `adm11`, and a *misbehaving model* that asks for forbidden tools in `a24b`, which proves the server holds the line even when the model does not).

### Live model results
The offline suite proves the server-side rules, but its model is a keyword stub, **not evidence that Gemini picks the right tool**. `make live-eval` runs a scenario set against the real model on a copy of your data. In this review I ran a deliberately small subset because the free tier allows only about **20 requests a day per model** (and returned timeouts under load):

| Check against real `gemini-3.8-flash` | Result |
| --- | --- |
| Return policy question: tool `search_knowledge`, correct documents and sections cited | passed |
| "How much is the Silver Needle and is it in stock?": tool `search_products`, answer shows the live price | passed |
| **A4** order: summary card first (total 1,900), nothing written, order and stock change only after Confirm | passed |
| **B3** "next Tuesday afternoon" resolves to Tuesday-afternoon slots in Kathmandu time | passed |
| **B4** booking: card with service, practitioner, 3:00 PM and price; booking row only after Confirm | passed |

The other 11 live scenarios (including injection against the real model) exist but were not run here; run them with `make live-eval` when your quota allows (`--only A8,B5` to choose).

### What went wrong and how it was fixed
The first full run of the existing suite was **1 failed, 52 passed**, while the old README claimed "53 passed". The failure was a date-fragile test (it booked a seeded holiday); the product was right and the test was wrong. A line-by-line cross-check against the brief then found real defects. Each was fixed and has a regression test:

| # | Found | Impact | Fix |
| --- | --- | --- | --- |
| 1 | `make seed` / `make eval` used Windows `cmd` syntax | Fails on macOS and Linux, where reviewers run it | Cross-platform Makefile |
| 2 | Org A knowledge base had no product descriptions | Brief lists them explicitly | Generated from the catalogue, without prices |
| 3 | Sign-up page used a default org, not the entry point | Signing up on Lotus could create a Himali account | Organisation comes from the URL |
| 4 | No server-side logout | Brief lists "log out" | Token revocation |
| 5 | Order quantity 0 or negative accepted | A negative quantity *added* stock | Whole numbers from 1, duplicate SKUs merged |
| 6 | `update_order` committed mid-transaction, left stray proposals, ignored its own reserved stock, and a stale price produced a *create* proposal | Address-only edit failed when the order held the last units; a stale edit could place a duplicate order | One code path, reservation-aware, stale edits re-stage an edit |
| 7 | No "slot in the past" rule; a closed day fell back to default hours; "nearest" alternatives were the earliest of the day; a practitioner could be booked for a service they do not offer; past bookings could be moved | Business rules 1 and 4 | All enforced and tested |
| 8 | Chroma citations had no document name; no relevance floor; BM25 counted stopwords | "Can't answer" questions got a citation | Metadata, calibrated floors, coverage rule |
| 9 | Embedding batches returned one vector for many chunks (found only by running against real Gemini) | Silent mis-indexing, then BM25 fallback | One `Content` per chunk, count check, seed reports what actually happened |
| 10 | `make seed` did not clear Chroma and crashed if the embedding API errored | "Rebuild" left stale vectors | Reset, graceful fallback |
| 11 | Expired proposals could still be confirmed; a failed confirm returned HTTP 200 | Stale cards worked; a refused double booking looked like success | Expiry in the claim; 409 Conflict |
| 12 | The tool result shrinker dropped lists | The model was told "no slots" while the card showed slots | Lists are trimmed, never dropped |
| 13 | Conversion rate counted staged proposals; admin metrics hardcoded `org_a`; "today" was UTC | Wrong numbers; a third org got studio metrics | Counted from confirmed rows; chosen by `agent_kind`; Kathmandu day |
| 14 | Confirm button came back after a reload; outcome only lived in the browser; slot times used the browser's time zone | Re-confirming an old card errored; wrong times for visitors elsewhere | State fetched per card, outcome saved in the thread, explicit `Asia/Kathmandu` |
| 15 | Admins could only list their *own* orders (none) | No way to demonstrate status changes in the UI | Org-scoped admin orders and bookings lists |
| 16 | Signing out after signing up showed the sign-up form | Confusing | Resets on sign-in or sign-out |
| 17 | Another customer's order id returned "Access denied" | Confirms it exists | "Not found", identical to a missing id |
| 18 | CORS `*` with credentials; no password rule; no login throttle | Hardening | Configured origins, min length, throttle |
| 19 | Docker would copy `.venv` into the image, wipe data on every restart, and keep the database outside the volume | Slow builds, lost data | `.dockerignore`, `--if-missing`, data on the volume |
| 20 | Org taglines had been overwritten with greetings | Greeting shown twice on the entry page | Real taglines |
| 21 | Found by manual testing with the real model: it passed a practitioner *name* where an id was expected, and the tool answered "0 slots" instead of an error (no tool listed practitioner ids either) | The agent told a customer Master Tenzing had no free Tuesday slots when he had 10 | Names resolve to ids, unknown ids return an error listing valid ones, `list_services` now lists practitioners and who offers what; covered by `b26` and live scenario `B7` |

### Open limitations (what is not solved, and the fix)
- **Retrieval margin is narrow.** The similarity floor (0.66) sits between 0.63 and 0.69 from 25 probe questions. A borderline question could land on either side. Fix: a larger labelled set, a re-ranker or a second signal (lexical coverage) combined with the vector score.
- **The offline model is not an LLM.** Real tool choice is only covered by `make live-eval`, which is quota-limited on the free tier. Fix: a paid or local model in CI, and LLM-as-judge scoring of the reply text.
- **SQLite and in-process rate limiting** mean one host and one process. Fix: Postgres with exclusion constraints and Redis for limits and token revocation.
- **Session token in `localStorage`** (see section 4). Fix: `HttpOnly` cookie plus CSRF token.
- **Docker images were not built in the review environment** (the Docker daemon was not running). I validated `docker compose config` and the start-up logic (`seed.py --if-missing` keeps data across restarts, a plain re-seed rebuilds), but a first `docker compose up --build` is yours to confirm.
- **Not built:** email reminders and shipped notifications, per-run tracing with per-org token cost, LLM-as-judge scoring.
- **Gemini free tier:** about 20 requests a day per model and occasional 504s. The provider falls back across models and tells the user plainly; a demo should use a fresh quota.

## 8. What I would do with another week

1. Run the live eval in CI on a paid key and add an LLM-as-judge pass over replies (tone, grounding, refusal quality), tracked per commit.
2. Per-run tracing (OpenTelemetry spans per tool call) and per-organisation token cost, using the usage the providers already return.
3. Postgres + pgvector (one datastore for rows and vectors), exclusion constraint for bookings, Redis for rate limits and revocation, `HttpOnly` cookie sessions.
4. Reminders and notifications: an outbox table written in the confirm transaction, drained by a worker (email 2 hours before a booking, "order shipped" when status advances).
5. A re-ranker and a labelled retrieval set for the knowledge bases, so the relevance floor is measured rather than estimated; per-chunk freshness tracking when a policy document changes.
6. Browser tests in CI (the `frontend/e2e/ui_check.py` checks, headless).

## 9. How I used AI coding tools

AI coding assistants wrote and reviewed a large share of this code, and the same tools were used for the line-by-line cross-check of the brief described in section 7 (Claude Code ran the test suites, drove the app in a real browser at 375 px and 1280 px, and probed the live Gemini API to calibrate retrieval and find the embedding batching bug). The runtime model is Gemini. I treated every generated change as a hypothesis: the offline suite, the live checks and the browser script are what I rely on, not the assistant's description of its own work, and several of the defects in section 7 were found precisely because a test or a live call contradicted a confident explanation.

## 10. Demo script (5 to 8 minutes)

Run `make seed`, set `LLM_PROVIDER=gemini` in `.env`, start both servers, and use a fresh quota (see the free-tier note in section 7). With the default `mock` model the app still demonstrates every flow, and `MOCK_TOKEN_DELAY_MS` makes its streaming and the Stop button visible. Suggested order, matching the brief:

1. **Org A order, edit, track, reorder** (`/a/himali-tea`, Kiran): "What green teas do you have?" (live price and stock) -> "Order 2 of the Golden Tippy black tea, deliver to Lazimpat" -> point at the **summary card and that nothing is saved**, press **Confirm Order** -> "Change the address of that order to Sanepa" -> Confirm Changes. In another window sign in as the admin: **Orders** panel -> advance it to confirmed. Back as Kiran: "Where is my order?" (status card with timeline) and try to edit again: **refused with the reason and current status**. Sign in as Aayush: "Same as last time".
2. **Org B booking and a refused conflict** (`/a/lotus-wellness`, Sita): "Free slots for a deep tissue massage next Tuesday afternoon" (slot picker, Kathmandu time) -> pick one, confirm. Then "Move it to <Rohan's BKG-2003 time>" -> **refused, with the nearest free alternatives**. (Rohan's time is in the My Bookings panel of `rohan@lotus.test`.)
3. **Cross-org failure:** signed in as Aayush, open `/a/lotus-wellness` -> **Cross-Tenant Access Blocked**. Then show the API refusing it: `curl -H "Authorization: Bearer <Aayush token>" localhost:8000/api/bookings` returns `[]`, a Lotus conversation id returns 404.
4. **Admin agent:** as `admin@himali.test` (staff land in **Admin Chat**; the other tab, "Customer view", is the normal customer agent and has no analytics): "How did we do over the last 30 days?" (window and definition stated), the **Analytics** panel (figures tagged with their window, bars for rankings, full definitions under "How these numbers are calculated"), and "Cancel all orders" (refused: read-only). A customer calling `/api/admin/activity_summary` gets **403**.
5. **Close with `make eval`** and the per-scenario table.

## Repository layout

```
backend/app/api/          routes: auth, orgs, chat (SSE), orders, bookings, actions (confirm gate), admin
backend/app/core/         config, database (SQLite pragmas, BEGIN IMMEDIATE), security, rate limiter
backend/app/models/       SQLAlchemy models, Pydantic schemas
backend/app/services/     agent_loop, tool_registry, llm_provider, agent_a / agent_b (tools), actions_service,
                          scheduling, knowledge_base, admin_agent, order_lifecycle, seeding
backend/app/seed_data/    initial_records.json, <org_id>_knowledge/*.md, org_c_example.json
backend/scripts/          seed.py, run_eval.py, live_eval.py, add_third_org.py, advance_order.py
backend/tests/            the eval scenarios (pytest), conftest builds a throw-away database
frontend/src/             App, auth context, chat page, cards, panels;  frontend/e2e/ui_check.py
Makefile, run.py          commands (run.py is the same list for machines without make)
docker-compose.yml, Dockerfile.backend, Dockerfile.frontend, .dockerignore, .env.example
```
