# Multi-Tenant Agent Platform

## 1. Project Overview
The Multi-Tenant Agent Platform is a production-grade, shared-infrastructure AI application hosting two distinct business organisations with autonomous, specialized assistants: **Himali Tea House** (Org A: a single-origin orthodox Himalayan tea e-commerce store with an ordering specialist agent managing live product discovery, atomic inventory checks, interactive order proposals, and lifecycle edits/cancellations) and **Lotus Wellness Studio** (Org B: a holistic therapy clinic with an appointment booking agent handling practitioner calendars, timezone-aware scheduling in **Asia/Kathmandu UTC+05:45**, holiday closures, and conflict-free rescheduling). Both organisations share common core infrastructure—including a FastAPI asynchronous backend, React 18 frontend with Server-Sent Events (SSE) streaming, SQLAlchemy ORM, and an isolated Admin Analytics Agent—while enforcing strict cryptographic, relational, and vector data isolation across all tenant boundaries.

---

## 2. Setup in 5 Commands

### Docker Setup (One-Click Stack)
```bash
# 1. Environment configuration
cp .env.example .env

# 2. Build and launch containerized backend and frontend
docker compose up -d --build

# 3. Seed database with initial products, services, opening hours, and knowledge bases
docker compose exec backend python scripts/seed.py

# 4. Run the automated 43-scenario evaluation and security isolation suite
docker compose exec backend python scripts/run_eval.py

# 5. Access the Web Application
# Open http://localhost:3000 in your browser (API documentation available at http://localhost:8000/docs)
```

### Local Development Setup (Make / Native Python)
```bash
# 1. Setup virtual environment and frontend dependencies
make setup

# 2. Rebuild database, populate seed catalogs, and index knowledge bases
make seed

# 3. Run evaluation suite and verify all business rules (43 scenarios)
make eval

# 4. Start backend API server (runs on http://localhost:8000)
make run-backend

# 5. In a second terminal, start frontend development server (runs on http://localhost:3000)
make run-frontend
```
*(Windows users without `make` can use `python run.py seed`, `python run.py eval`, `python run.py backend`, and `python run.py frontend`)*.

---

## 3. Test Logins

All seeded test accounts share the password: **`Password123!`**

| Organisation | Role | Name | Email Address | Password | Capabilities & Test Scope |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Org A: Himali Tea House** | Customer | Aayush Sharma | `aayush@himali.test` | `Password123!` | Active customer with 2 past orders (`ORD-1001`, `ORD-1002`). Tests "same as last time" reorder, order tracking, and pending cancellations. |
| **Org A: Himali Tea House** | Customer | Priya Adhikari | `priya@himali.test` | `Password123!` | Customer with 1 pending order (`ORD-1003`). Tests live shipping address modifications and cancellation policies. |
| **Org A: Himali Tea House** | Customer | Kiran Thapa | `kiran@himali.test` | `Password123!` | New customer with 0 past orders. Tests fresh product discovery and initial order placement. |
| **Org A: Himali Tea House** | **Admin** | Himali Admin | `admin@himali.test` | `Password123!` | Store Administrator. Unlocks Admin Analytics chat, AOV / gross revenue metrics, and order status advancement. |
| **Org B: Lotus Wellness Studio** | Customer | Sita Gurung | `sita@lotus.test` | `Password123!` | Active client with 1 past booking (`BKG-2002`). Tests slot booking, relative date resolution, and conflict-free rescheduling. |
| **Org B: Lotus Wellness Studio** | Customer | Rohan Shrestha | `rohan@lotus.test` | `Password123!` | Client with past booking (`BKG-2001`). Tests cancellation fee calculation (<4-hour notice). |
| **Org B: Lotus Wellness Studio** | Customer | Bikash Pandey | `bikash@lotus.test` | `Password123!` | New client with 0 past bookings. Tests service catalog inquiries and initial appointment booking. |
| **Org B: Lotus Wellness Studio** | **Admin** | Lotus Admin | `admin@lotus.test` | `Password123!` | Studio Administrator. Unlocks Studio Analytics chat, practitioner utilisation rates, and appointment cancellation ratios. |

*Direct Workspace URLs & 1-Click Buttons:*
- Himali Tea House: `http://localhost:3000/a/himali-tea`
- Lotus Wellness Studio: `http://localhost:3000/a/lotus-wellness`
- *Note:* The sign-in screen features **1-Click Verified Test Login** buttons for instant one-click authentication as Aayush, Sita, or either administrator.

---

## 4. Architecture & Tenant Isolation

```
                                  [ Client Web Application ]
                                (React 18 + Vite + Tailwind CSS)
                                               │
                       ┌───────────────────────┴────────────────────────┐
                       │ HTTP / Server-Sent Events (SSE) Streaming       │
                       ▼                                                ▼
          [ Org A Entrypoint: /a/himali-tea ]          [ Org B Entrypoint: /a/lotus-wellness ]
                       │                                                │
                       └───────────────────────┬────────────────────────┘
                                               │
                                  [ FastAPI Application Layer ]
                                               │
            ┌──────────────────────────────────┼──────────────────────────────────┐
            ▼                                  ▼                                  ▼
    [ Authentication & RBAC ]         [ Rate Limiter Engine ]           [ Agent Dispatcher ]
    - Bcrypt Password Verification    - 20 requests/min per user        - Line-by-line agent execution
    - JWT (sub, org_id, role)         - Sliding window limiter          - Streaming SSE token emitter
            │                                                                     │
            ├──────────────────────────────────┬──────────────────────────────────┤
            ▼                                  ▼                                  ▼
    [ Agent A: Himali Ordering ]      [ Agent B: Lotus Booking ]       [ Admin Analytics Agent ]
    - Live product search             - Availability in UTC+05:45       - Read-only operational metrics
    - Pre-order confirmation card     - Practitioner double-book mutex  - Time-windowed conversion funnels
    - Atomic inventory decrement      - Holiday & hours validation      - Practitioner utilisation
    - Lifecycle edits / cancels       - Conflict refusal + 3 alts       - Strictly scoped to user.org_id
            │                                  │                                  │
            └──────────────────────────────────┼──────────────────────────────────┘
                                               │
                          ┌────────────────────┴────────────────────┐
                          ▼                                         ▼
             [ Relational Database (SQL) ]            [ Vector Knowledge Base ]
             - Multi-tenant row scoping:              - Filter: WHERE org_id = user.org_id
               WHERE org_id = user.org_id             - Lexical BM25 + Dense Semantic Embeddings
             - Concurrency Mutex & Atomic SQL:        - Exact document & section citation chips
               UPDATE stock WHERE stock >= qty        - Modal verified excerpt viewers
```

### Password Hashing & JWT Strategy
1. **Bcrypt Password Hashing**:
   - User passwords are never stored in plaintext. They are salted and hashed using one-way **`bcrypt`** (work factor 12) during registration and seed initialization ([`backend/app/core/security.py`](file:///c:/Users/baral/Desktop/home_assignment/backend/app/core/security.py#L22-L25)).
2. **Cryptographic JWT Tokens**:
   - Sessions are secured with HMAC-SHA256 (HS256) JSON Web Tokens. Claims include `sub` (authenticated user ID), `email`, `org_id` (the user's bound tenant), `role` (`customer` or `admin`), and expiration `exp` (24-hour lifetime).
3. **Privilege Escalation Protection**:
   - Public registration endpoints hardcode `role = "customer"`. Malicious payloads attempting to register with `role: "admin"` are strictly overridden.

### Server-Side `org_id` Extraction & SQL Row Scoping
- **Zero Trust on Client Tenant Claims**: The backend never accepts or trusts `org_id` from client headers, query parameters, or request bodies.
- **Server Extraction**: The `get_current_user` FastAPI dependency extracts and cryptographically verifies the token on every authenticated request.
- **Strict Query Enforcement**:
  - Every SQL query in SQLAlchemy includes a mandatory tenant boundary filter:
    ```python
    stmt = select(Order).where(Order.org_id == current_user.org_id)
    ```
  - Customer endpoints further scope by ownership:
    ```python
    stmt = select(Order).where(Order.org_id == current_user.org_id, Order.user_id == current_user.id)
    ```
  - Attempting to query or modify a record belonging to another user or another organisation produces an immediate `404 Not Found` or `403 Forbidden`.
- **Frontend Route Guard**:
  - [`frontend/src/App.tsx`](file:///c:/Users/baral/Desktop/home_assignment/frontend/src/App.tsx#L35-L62) inspects the URL path against the authenticated user's `currentOrg.slug`. An authenticated Himali user attempting to navigate to `/a/lotus-wellness/chat` is halted by a full-page **Cross-Tenant Access Blocked** security screen.

---

## 5. Key Decisions

### A. Retrieval: Structural Header Chunking & BM25 / Vector Hybrid
- **Structural Markdown Header Chunking**:
  - Instead of naive fixed-character chunking (which cuts sentences in half and separates FAQ questions from their answers), the knowledge base parser splits on markdown heading boundaries (`#`, `##`, `###`).
  - Each chunk preserves the document name (`doc_name`), section title (`section_name`), and complete self-contained semantic text (e.g. brewing temperatures, return rules, therapist bios).
- **BM25 + Semantic Vector Hybrid Ranking**:
  - Pure vector search often misses specific SKU strings or exact numerical policy thresholds; pure keyword search misses paraphrased intent.
  - The retrieval engine combines BM25 lexical term weighting (BM25 score) with dense semantic embeddings (cosine similarity) via Reciprocal Rank Fusion (RRF).
  - Strict tenant scoping (`WHERE chunk.org_id == user.org_id`) runs *before* similarity ranking, guaranteeing that Org A queries cannot retrieve Org B knowledge chunks under any circumstance.
  - Returns structured citations with clickable chips in the UI that open verified source modal viewers.

### B. Scheduling: Custom `SchedulingEngine` & Nepal Timezone Precision
- **Nepal Standard Time (`Asia/Kathmandu`, UTC+05:45)**:
  - Nepal is on a unique $+05:45$ timezone offset. All datetime operations, slot calculations, and opening hours boundaries are localized using `pytz.timezone("Asia/Kathmandu")`.
- **Relative Date NLP Resolution**:
  - The custom `resolve_relative_datetime_kathmandu` resolver calculates expressions like `"next Tuesday afternoon"` relative to the current wall-clock time in Kathmandu, anchoring afternoon appointments to 14:00 (2:00 PM) local time.
- **Holiday & Operating Hours Validation**:
  - Checks public holidays dynamically from the `holidays` database table (e.g., rejecting bookings on Bhai Tika or Dashain closures).
  - Enforces weekly operating hours (Mon–Fri 08:00–19:00, Sat 09:00–18:00, Sun 10:00–16:00) and duration fits (rejecting a 60-minute therapy booked at 18:30 on a weekday because it exceeds the 19:00 closing time).

### C. Concurrency: Atomic SQL Inventory & Async Mutex Booking Locks
- **Inventory Concurrency (Agent A)**:
  - To prevent stock from dropping below zero when multiple customers order simultaneously, inventory decrements use **atomic SQL conditional updates**:
    ```sql
    UPDATE products
    SET stock = stock - :qty
    WHERE org_id = :org_id AND sku = :sku AND stock >= :qty
    ```
  - If the database `rowcount == 0` (indicating another concurrent transaction took the remaining stock), the transaction immediately rolls back and returns an out-of-stock refusal with alternative tea suggestions.
- **Booking Mutex Lock (Agent B)**:
  - To prevent practitioner double-booking and simultaneous customer overlaps, `SchedulingEngine.booking_lock = asyncio.Lock()` wraps the slot validation and database commit steps in an atomic critical section.
  - Serialized execution inside `async with SchedulingEngine.booking_lock:` ensures that when two clients submit simultaneous booking requests for the exact same slot, the first succeeds and the second is safely rejected with proactive recommendations of the 3 nearest free alternatives.

---

## 6. Eval Results

The platform includes an automated evaluation suite that executes with a single command:
```bash
make eval
# or: python run.py eval
```

### 100% Pass Rate Across All 43 Automated Scenarios
The evaluation runner validates real business rules and verifies database state changes directly against the SQLite database:

| Component | Scenarios | Edge Cases & Key Assertions Tested | Result |
| :--- | :---: | :--- | :---: |
| **Agent A (Himali Tea House)** | 16 | • Atomic stock decrements and inventory event audit logging.<br>• Simultaneous stock exhaustion race condition (stock hits 0, never negative).<br>• Pre-order confirmation summary proposal requirement (Rule 1).<br>• Stock limit refusal and alternative suggestions (Rule 2).<br>• Pending order modification/cancellation vs. confirmed order refusal (Rule 3).<br>• Customer ownership boundary enforcement (Rule 4).<br>• "Same as last time" reorder with live stock and price re-checks (Rule 5).<br>• Prompt injection attacks attempting to dump schemas or cross-org data. | **PASS (16/16)** |
| **Agent B (Lotus Wellness Studio)** | 16 | • Concurrent simultaneous double-booking race condition prevented via mutex lock.<br>• Asia/Kathmandu timezone (+05:45) relative date NLP parsing ("next Tuesday afternoon").<br>• Pre-confirmation booking proposal card with service, practitioner, date, time, and fee (Rule 5).<br>• Studio holiday closure refusal (Bhai Tika / Dashain) (Rule 1).<br>• Opening hours boundary refusal (60-min massage at 18:30 exceeds 19:00 close) (Rule 1).<br>• Practitioner double-booking refusal (Rule 2).<br>• Customer simultaneous booking refusal (Rule 2).<br>• Reschedule conflict refusal with proactive suggestion of 3 nearest free alternatives (Rule 4).<br>• Cancellation notice policy calculation (<4-hour late cancellation fee) (Rule 3). | **PASS (16/16)** |
| **Admin Analytics Agent** | 3 | • Role-Based Access Control: Customer accounts strictly denied access (`HTTP 403 Forbidden`).<br>• Read-only enforcement: Modification and deletion commands rejected.<br>• Activity summaries, gross revenue, AOV, and practitioner utilisation reporting.<br>• Conversation-to-order conversion rate calculation with explicit mathematical formulas and time windows. | **PASS (3/3)** |
| **Tenant Isolation & Security** | 8 | • Cross-tenant service discovery blocked.<br>• Cross-customer order snooping rejected (`404 / 403`).<br>• Cross-tenant booking queries return empty sets.<br>• Admin endpoint protection against unprivileged customers.<br>• Cross-org admin status manipulation blocked.<br>• Strict knowledge base vector isolation (0 cross-org chunks retrieved).<br>• Rate limiting enforcement: Exceeding 20 msgs/min triggers `HTTP 429 Too Many Requests`.<br>• Privilege escalation role tampering overridden during registration. | **PASS (8/8)** |
| **Total** | **43** | **Comprehensive end-to-end coverage of all core and stretch requirements** | **100% PASS** |

---

## 7. Future Improvements (Another Week)

If given another week of development, we would prioritize the following production enhancements:
1. **Redis Multi-Instance Rate Limiting & Token Revocation**:
   - Migrate the in-memory sliding-window rate limiter to Redis (`token_bucket` / sliding log), enabling horizontal scalability across multiple load-balanced FastAPI instances and instant revocation of JWT tokens upon user logout.
2. **PostgreSQL Migration with Native Temporal Exclusion Constraints**:
   - Migrate from SQLite to PostgreSQL with the `btree_gist` extension, implementing native database-level exclusion constraints:
     ```sql
     ALTER TABLE bookings ADD CONSTRAINT no_overlapping_practitioner_slots
     EXCLUDE USING gist (practitioner_id WITH =, tsrange(start_time, end_time) WITH &&);
     ```
   - This provides sub-millisecond database engine-level concurrency protection across distributed database read/write replicas.
3. **Automated Asynchronous Notifications (Email & SMS/WhatsApp)**:
   - Integrate Celery / ARQ background task workers with SendGrid/AWS SES and Twilio to send automated booking confirmation emails, calendar invite attachments (`.ics`), SMS reminders 2 hours before appointments, and order dispatch tracking updates.
4. **Multi-Provider LLM Streaming Failover**:
   - Expand the line-by-line streaming loop to support dynamic runtime failover across Google Gemini, Anthropic Claude, and OpenAI with automated token cost and latency telemetry via OpenTelemetry / Langfuse.

---

## 8. AI Usage

AI coding assistants (Claude 3.5 Sonnet and Gemini 2.0) were utilized during the development of this project for:
- Accelerating domain-specific seed data generation (Himalayan tea cultivars, Ayurvedic therapy descriptions, practitioner bios, and public holiday schedules).
- Performing static code audits and designing comprehensive edge-case assertions for the 43-scenario evaluation suite.
- Assisting in the structured formatting and drafting of this technical documentation.

All core architectural decisions, database models, concurrency locks, multi-tenant security verifications, business logic rule enforcement, and test cases were verified and tested to guarantee 100% compliance with the assignment brief.
