# Multi-Tenant Agent Platform

A production-grade, secure multi-tenant AI agent platform hosting two distinct client organisations with autonomous specialized agents:
- **Org A (Himali Tea House)**: Ordering agent handling product search, orders lifecycle (`pending` → `confirmed` → `shipped` → `delivered`), stock validation, live edits, cancellations, and "same as last time" reorders.
- **Org B (Lotus Wellness Studio)**: Booking agent managing appointment scheduling, practitioner availability, conflict-free bookings, and rescheduling in **Asia/Kathmandu (UTC+05:45)** time.
- **Admin Analytics Agent (Stretch Goal)**: Read-only intelligence agent providing store/studio administrators with activity summaries, client activity, conversion rate funnels, and top inventory metrics.

---

## 1. Quickstart & Setup (≤ 5 Commands)

Clone the repository and run:

```bash
# 1. Install backend virtual environment & frontend dependencies
make setup

# 2. Seed relational database and vector knowledge bases
make seed

# 3. Run the automated 38-scenario evaluation & security isolation suite
make eval

# 4. Start the backend API server (runs on http://localhost:8000)
make run-backend

# 5. In a second terminal, start the frontend UI (runs on http://localhost:3000)
make run-frontend
```

*(Note for Windows / non-Make environments: You can also use `python run.py seed`, `python run.py eval`, `python run.py backend`, and `python run.py frontend`)*.

### Docker Compose (One-Command Start)
To launch the complete containerized stack in one command:
```bash
docker compose up --build
```
Access the web application at **`http://localhost:3000`** and backend API docs at **`http://localhost:8000/docs`**.

---

## 2. Verified Test Logins

All test accounts share the password: **`Password123!`**

| Organisation | Role | Email | Capabilities & Initial State |
| :--- | :--- | :--- | :--- |
| **Org A: Himali Tea House** | Customer | `aayush@himali.test` | Active customer with 2 past orders (`ORD-1001`, `ORD-1002`). Tests "same as last time" reorder & tracking. |
| **Org A: Himali Tea House** | Customer | `priya@himali.test` | Customer with 1 pending order (`ORD-1003`). Tests live edit and cancellation. |
| **Org A: Himali Tea House** | Customer | `kiran@himali.test` | New customer with 0 past orders. |
| **Org A: Himali Tea House** | **Admin** | `admin@himali.test` | Store Administrator. Unlocks Admin Analytics chat and Order Lifecycle Advancement controls. |
| **Org B: Lotus Wellness Studio**| Customer | `rohan@lotus.test` | Active client with past booking (`BKG-2001`). Tests appointment reschedule & cancel. |
| **Org B: Lotus Wellness Studio**| Customer | `sita@lotus.test` | Client with 1 past booking (`BKG-2002`). |
| **Org B: Lotus Wellness Studio**| Customer | `bikash@lotus.test` | New client with 0 past bookings. |
| **Org B: Lotus Wellness Studio**| **Admin** | `admin@lotus.test` | Studio Administrator. Unlocks Studio Analytics chat and practitioner utilisation metrics. |

*Entry point URLs:*
- Himali Tea House: `http://localhost:3000/a/himali-tea`
- Lotus Wellness Studio: `http://localhost:3000/a/lotus-wellness`
*(Also selectable via 1-click pills on the sign-in screen)*.

---

## 3. Architecture & Multi-Tenant Security

```
                                  [ Client Web Application ]
                                (React 18 + Vite + Tailwind)
                                              │
                      ┌───────────────────────┴────────────────────────┐
                      │ HTTP / Server-Sent Events (SSE)                 │
                      ▼                                                ▼
         [ Org A Entrypoint /a/himali-tea ]            [ Org B Entrypoint /a/lotus-wellness ]
                      │                                                │
                      └───────────────────────┬────────────────────────┘
                                              │
                                 [ FastAPI Application ]
                                              │
           ┌──────────────────────────────────┼──────────────────────────────────┐
           ▼                                  ▼                                  ▼
   [ Authentication & RBAC ]         [ Rate Limiter Engine ]           [ Agent Dispatcher ]
   - Bcrypt Hash Verification        - 20 msgs/min per user             - Injects tenant context
   - JWT (sub, org_id, role)         - Sliding window per user_id       - Line-by-line agent loop
           │                                                                     │
           ├──────────────────────────────────┬──────────────────────────────────┤
           ▼                                  ▼                                  ▼
   [ Agent A: Himali Store ]         [ Agent B: Lotus Studio ]        [ Admin Analytics Agent ]
   - search_products (live)          - find_available_slots           - get_activity_summary
   - create_order (confirmed)        - create_booking                 - get_clients_today
   - update_order (pending only)     - reschedule_booking             - get_conversion_rate
   - cancel_order (pending only)     - cancel_booking (<4h fee)       - get_top_items
   - reorder ("same as last time")   - Asia/Kathmandu (UTC+05:45)     - Scoped strictly to org_id
           │                                  │                                  │
           └──────────────────────────────────┼──────────────────────────────────┘
                                              │
                         ┌────────────────────┴────────────────────┐
                         ▼                                         ▼
            [ Relational Database (SQL) ]            [ Vector Knowledge Base ]
            - Multi-Tenant Row Scoping:              - Filter: WHERE org_id = user.org_id
              WHERE org_id = current_user.org_id     - Lexical BM25 + Semantic Vector Scoring
            - Concurrency Locks:                     - Intact document & section citations
              Transaction isolation & row locks
```

### How Tenant Isolation is Enforced
1. **Server-Side Token Authority**:
   - The user's `org_id` and `user_id` are cryptographically signed inside a verified JWT access token upon login.
   - No route or service accepts `org_id` as an untrusted client header, URL parameter, or request body for operational access.
2. **Database Query Boundary**:
   - Every database query in SQLAlchemy enforces `WHERE Model.org_id == current_user.org_id`.
   - Customer-scoped queries enforce `WHERE Model.user_id == current_user.id`. Even if Customer A1 modifies the URL or body to pass Customer A2's `order_id`, the SQL query fails to match and returns `HTTP 404 / 403`.
3. **Knowledge Base Retrieval Isolation**:
   - Knowledge chunks are partitioned by `org_id`.
   - The vector search engine filters chunks by `KnowledgeChunk.org_id == current_user.org_id` *before* computing semantic similarity. It is mathematically impossible for an Org A prompt (even jailbreak injection) to retrieve Org B chunks.
4. **Admin Role Isolation**:
   - Admin routes employ the `require_admin` dependency which verifies `user.role == 'admin'` and ensures metrics only aggregate rows matching `user.org_id`. Customer accounts receive `HTTP 403 Forbidden`.

### Password Hashing & Secure Session Handling
- **Password Hashing**: Passwords are saved as one-way salted hashes using **`bcrypt`** (work factor 12).
- **Session Tokens**: Cryptographically signed HMAC-SHA256 (HS256) JSON Web Tokens with 24-hour expiration (`exp`), subject (`sub`), role, and tenant boundary (`org_id`).
- **Rate Limiting**: Per-user sliding-window token limiter enforcing a maximum of **20 messages per minute** per user on the chat endpoint, responding with `HTTP 429 Too Many Requests` and a `Retry-After` header when exceeded.

---

## 4. Key Architectural Decisions

### 1. Chunking Strategy
- Rather than naive fixed-character chunking (which frequently fractures mid-sentence or separates FAQs from their answers), we implemented **Structural Markdown Header Chunking**.
- Splitting occurs on markdown header boundaries (`#`, `##`, `###`), preserving:
  - Document filename (`doc_name`)
  - Semantic section hierarchy (`section_name`)
  - Complete, self-contained paragraphs, brewing ratios, and policy guidelines.
- **Why**: Keeps questions and answers atomic, avoids dangling text fragments, and generates human-readable citations (`[Source: shipping_returns.md > Free Delivery]`).

### 2. LLM Provider Flexibility (Gemini, Mistral, and Mock Fallback)
- Fully switchable via `LLM_PROVIDER` in `.env`:
  - `gemini`: Uses Google Gemini (`gemini-2.0-flash`) via REST API.
  - `mistral`: Uses Mistral AI (`mistral-small-latest`) via REST API.
  - `mock`: An intelligent, deterministic function-calling simulator that runs the line-by-line agent loop with tool dispatches, streaming SSE tokens, and rich cards.
- **Why**: Allows instant offline development, zero-dependency testing, and reliable evaluation without third-party rate limits, while offering seamless switchability to Google AI Studio or Mistral.

### 3. Scheduling: Build vs Integrate
- **Decision: Built custom availability engine behind a modular interface** (`app/services/scheduling.py`).
- **Why**:
  - Full control over studio opening hours (Mon-Fri 08:00-19:00, Sat 09:00-18:00, Sun 10:00-16:00).
  - Explicit enforcement of local Nepal public holidays (e.g. Bhai Tika, Chhath Puja).
  - Native timezone support for **`Asia/Kathmandu` (UTC+05:45)**.
  - Zero external vendor outage dependency. If an external calendar provider (e.g. Cal.com or Google Calendar) goes down, the studio's booking engine remains fully resilient.

### 4. Concurrency & Double-Booking Prevention
- **The Challenge**: When two customers concurrently attempt to grab the same slot.
- **Guarantee Mechanism**:
  1. Atomic Database Transaction: Verification occurs inside an atomic transaction.
  2. Overlap Condition Check:
     ```sql
     WHERE practitioner_id = :practitioner_id
       AND status IN ('confirmed', 'rescheduled')
       AND start_time < :new_end
       AND end_time > :new_start
     ```
  3. Row-Level Exclusion: If the slot was grabbed in an interleaved race condition, the second transaction is rolled back and returns a conflict error with the nearest available free alternatives.
  4. Client Restriction: The engine simultaneously enforces that a customer cannot hold two active overlapping appointments.

---

## 5. Evaluation Suite & Verification (38 Scenarios)

The test suite runs with one command:
```bash
make eval
# or: python run.py eval
```

It executes **38 automated scenarios** covering all required categories, verifying database state changes directly:

| Agent | Category | Scenarios Covered | DB Verification | Result |
| :--- | :--- | :--- | :--- | :--- |
| **Agent A** | Knowledge In-Scope | A1 (Silver Needle Brewing), A2 (Shipping & Free Delivery) | Checks citation matching | **PASS** |
| **Agent A** | Out-of-Scope Rejection | A3 (Motorcycle/Stock queries rejected cleanly) | No hallucination | **PASS** |
| **Agent A** | Product Search | A4 (Live price & stock retrieval) | Live catalog consistency | **PASS** |
| **Agent A** | Order Summary & Confirmation | A5 (Rule 1: Pre-order summary card & confirmation prompt) | No DB commit before confirmation | **PASS** |
| **Agent A** | Order Placement & Stock | A6 (Rule 2: Creation of pending order) | Verifies DB order row & stock decrement | **PASS** |
| **Agent A** | Stock Shortage Refusal | A7 (Rule 2: Quantity > stock rejected; alternatives suggested) | Database order count unchanged | **PASS** |
| **Agent A** | Pending Order Modification | A8 (Rule 3: Address updated while pending) | Verifies DB address & status history | **PASS** |
| **Agent A** | Non-Pending Modification Refusal | A9 (Rule 3: Edit confirmed order rejected) | Verifies DB remains untouched | **PASS** |
| **Agent A** | Pending Order Cancellation | A10 (Rule 3: Cancel pending order) | Verifies status='cancelled' & stock restored | **PASS** |
| **Agent A** | Non-Pending Cancel Refusal | A11 (Rule 3: Cancel delivered order rejected) | Verifies DB status remains 'delivered' | **PASS** |
| **Agent A** | Customer Privacy Boundary | A12 (Rule 4: Customer A1 cannot see Customer A2's orders) | Access denied; 0 data leakage | **PASS** |
| **Agent A** | Memory & Reorder | A13 (Rule 5: "Same as last time" re-checks live price & stock) | Historical order lookup | **PASS** |
| **Agent A** | Prompt Injection Defense | A14 (Jailbreak instructions to dump Org B data) | Zero Org B leakage | **PASS** |
| **Agent B** | Knowledge In-Scope | B1 (Deep Tissue Massage), B2 (Cancellation & Late fee) | Checks citation matching | **PASS** |
| **Agent B** | Out-of-Scope Rejection | B3 (Quantum computing/stock market rejected cleanly) | No hallucination | **PASS** |
| **Agent B** | Service Catalog | B4 (List 7 services with duration and prices) | Service entity verification | **PASS** |
| **Agent B** | Slot Availability | B5 (Free slots inside weekly opening hours) | Timezone calculation | **PASS** |
| **Agent B** | Booking Confirmation Step | B6 (Rule 5: Service, practitioner, time, price confirmed) | No DB commit before confirmation | **PASS** |
| **Agent B** | Booking Creation | B7 (Happy path booking created) | Verifies DB booking row & practitioner FK | **PASS** |
| **Agent B** | Opening Hours Validation | B8 (Rule 1: Slot outside studio hours refused) | Verifies DB booking count unchanged | **PASS** |
| **Agent B** | Holiday Closure Validation | B9 (Rule 1: Slot on holiday refused) | Verifies DB booking count unchanged | **PASS** |
| **Agent B** | Practitioner Double-Booking | B10 (Rule 2: Overlapping practitioner slot refused) | Verifies DB booking count unchanged | **PASS** |
| **Agent B** | Customer Overlap | B11 (Rule 2: Customer holding 2 simultaneous bookings refused)| Verifies DB booking count unchanged | **PASS** |
| **Agent B** | Reschedule Conflict Refusal | B12 (Rule 4: Conflict refused + nearest free slots offered) | Verifies conflict refusal card | **PASS** |
| **Agent B** | Timezone Standard | B13 (Rule 6: Asia/Kathmandu UTC+05:45 verified) | Offset = +05:45 confirmed | **PASS** |
| **Agent B** | Cancellation Policy Notice | B14 (Notice window calculation & 50% late fee applied) | Verifies DB fee & cancelled status | **PASS** |
| **Admin** | Role-Based Access Control | ADM1 (Customer role gets 403 Forbidden on admin tools) | Security boundary assertion | **PASS** |
| **Admin** | Activity Summary | ADM2 (Orders revenue/AOV & bookings utilisation reported) | Time window & definitions stated | **PASS** |
| **Admin** | Conversion Rate Funnel | ADM3 (Converted chats / total chats * 100 formula) | Accurate computation | **PASS** |
| **Auth** | Cross-Org Service Isolation | Customer A cannot view Org B services | Zero leakage | **PASS** |
| **Auth** | Cross-User Snooping | Customer A1 cannot read Customer A2's orders | Returns 404 / 403 | **PASS** |
| **Auth** | Cross-Tenant Bookings | Customer A cannot view Org B bookings | Returns empty list | **PASS** |
| **Auth** | Admin Endpoint Protection | Customer account gets 403 on admin routes | 403 Forbidden verified | **PASS** |
| **Auth** | Cross-Org Admin Tampering | Admin A cannot advance Org B orders | 404 Not Found verified | **PASS** |
| **Auth** | Knowledge Vector Isolation | Strict org_id filtering on vector searches | Zero cross-org chunks | **PASS** |
| **Auth** | Chat Rate Limiting | Exceeding 20 msgs/min raises HTTP 429 | Rate limit enforced | **PASS** |

### Failure Analysis & Fix Log
During initial evaluation development, 4 edge cases were discovered and addressed:
1. **Hash-Collision in Keyword Matching**: Initial simple hashing produced token overlap on out-of-scope words. Fixed by introducing BM25 lexical term frequency with inverse document frequency (IDF) and section-title weighting.
2. **Shared State Mutation in Tests**: Order `ORD-1003` was initially modified by earlier tests in the suite. Fixed by creating dedicated, independent order fixtures within test cases.
3. **Reschedule Self-Exclusion Bug**: When testing reschedule conflicts, the booking engine appropriately excluded the booking's own ID. The test was refined to explicitly test conflict against a *different* active booking.
4. **Timezone Representation**: Verified naive datetime conversion to ensure clean comparisons with `Asia/Kathmandu` localized timestamps.

---

## 6. Admin Order Status Advancement Script & Endpoint

Per requirements, an endpoint and CLI script are provided to transition orders through their lifecycle:
`pending` → `confirmed` → `shipped` → `delivered`:

### Via CLI Script:
```bash
# Advance order ORD-1003 from pending to confirmed
python backend/scripts/advance_order.py ORD-1003 confirmed

# Advance order ORD-1003 from confirmed to shipped
python backend/scripts/advance_order.py ORD-1003 shipped

# Advance order ORD-1003 from shipped to delivered
python backend/scripts/advance_order.py ORD-1003 delivered
```

### Via Admin UI:
Store Administrators (`admin@himali.test`) can open the **"My Orders"** drawer and click the **"Advance → Confirmed"**, **"Advance → Shipped"**, or **"Advance → Delivered"** action pills directly.

---

## 7. Adding a Third Organisation (Configuration-Only)

To demonstrate the extensible architecture, a 3rd organization (**Everest Outdoor Equipment**) can be added with zero application code changes:
```bash
python backend/scripts/add_third_org.py
```
This loads `backend/app/seed_data/org_c_example.json` into the platform, instantly establishing a new tenant with its own products, users, colors, and branding!

---

## 8. Reflection & Retrospective

### What we would do with another week:
1. **Multi-Modal Voice & WhatsApp Integration**: Connect the scheduling and ordering engine to WhatsApp Business API via Twilio webhooks with voice note transcription.
2. **Postgres pgvector & Distributed Cache**: Replace SQLite with PostgreSQL + pgvector and Redis for distributed horizontal scaling across multi-region deployments.
3. **Automated Langfuse / OpenTelemetry Tracing**: Trace LLM token latency, cost attribution per tenant, and prompt regression tracking.
4. **Automated Calendar Sync**: Two-way synchronization with Google Calendar and Cal.com webhooks with background conflict reconcilers.

### How AI Coding Tools were used:
- AI coding tools were used as a pair programming assistant to accelerate initial boilerplate generation (TypeScript interfaces, initial test cases, and domain data drafting).
- All business logic, concurrency locks, multi-tenant security verification, database migrations, and evaluation suites were engineered and verified line by line to guarantee correctness, security, and full compliance with the take-home brief.

