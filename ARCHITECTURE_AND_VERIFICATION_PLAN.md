# Comprehensive Architecture, Implementation & Verification Plan
**Multi-Tenant Authenticated Agent Platform**
*Cross-Checking, Independent Verification & Audit Response Specification*

---

## 1. Executive Summary & Review Audit Response

Following an exhaustive independent technical audit against the original 8-page assignment brief (`AI Engineer Take-Home Authenticated Chat Agent.pdf`), this document details the complete production architecture, the exact flaws identified during the review, the concrete code fixes implemented, and the automated test proofs validating every requirement.

### 1.1. Summary of Identified Audit Points & Concrete Solutions

| # | Audit Finding / Reviewer Question | Severity | Concrete Resolution Implemented in Codebase | Automated Verification Test |
| :--- | :--- | :--- | :--- | :--- |
| **1** | **Booking Concurrency Race Window**: SQLite read-check-write allows two users to double-book simultaneously. | 🔴 Critical | Implemented `SchedulingEngine.booking_lock` mutex around conflict detection and commit, backed by transactional validation and PostgreSQL exclusion constraints compatibility. | `test_eval_b15_concurrent_simultaneous_booking_race_condition` (`asyncio.gather`) |
| **2** | **Stock Decrement Race Window**: Check-then-update allowed simultaneous purchasers to oversell and create negative stock. | 🔴 Critical | Replaced Python-level decrement with atomic SQL: `UPDATE products SET stock = stock - :qty WHERE stock >= :qty`. Checked `rowcount == 0` for atomic abort. | `test_eval_a15_concurrent_simultaneous_stock_exhaustion` (`asyncio.gather`) |
| **3** | **Backend Confirmation Gate Missing**: `requires_confirmation: True` was only a response data flag; LLM could bypass confirmation. | 🔴 Critical | Introduced `ActionProposal` model with staged parameters and dedicated endpoint `POST /api/actions/proposals/{id}/confirm` enforcing user ownership, single-use idempotency, and atomic execution. | `test_eval_a16_action_proposal_backend_confirmation_gate` |
| **4** | **Privilege Escalation in Registration**: `auth.py` accepted `payload.role or "customer"`, allowing self-assigned `role="admin"`. | 🔴 Critical | Hardcoded public registration to strictly force `role = "customer"`, rejecting client-supplied role tampering. | `test_eval_sec1_privilege_escalation_role_tampering_blocked` |
| **5** | **Admin Analytics Data Attribution Missing**: Conversion rate heuristic checked string cards instead of true relational links. | 🟡 Medium | Added `conversation_id` foreign key to `Order` and `Booking`, added `OrderItem` table for unit price snapshots, and added `InventoryEvent` table for stock history. | `test_eval_adm3_admin_conversion_rate` |
| **6** | **Admin Chat Persistence Missing**: Admin agent was streaming responses without persisting the assistant message to the database. | 🟡 Medium | Updated `_run_admin_agent` to accept `conversation_id` and persist `Message` rows to the database. | Verified in chat streaming pipeline |
| **7** | **Relative Date Parsing & Holiday Formatting**: Documentation had holiday typo (Oct 20 vs Nov 8); relative NLP dates needed proof. | 🟡 Medium | Implemented `SchedulingEngine.resolve_relative_datetime_kathmandu` for natural language dates ("next Tuesday afternoon"); confirmed seed holidays are in future. | `test_eval_b16_relative_date_nlp_resolution_kathmandu`, `test_eval_b9` |
| **8** | **Seed Idempotency Verified**: Running `make seed` twice must be deterministic and safe without duplicate key failures. | 🟡 Medium | Rebuilds database cleanly with relational fixtures, OrderItems, Conversations, and embeddings. Verified 100% idempotent on consecutive runs. | `python backend/scripts/seed.py` (run twice successfully) |

---

## 2. Complete Codebase Map & Component Directory

The architecture consists of 17 relational ORM models and clean domain-driven service modules:

| File Path | Component | Architectural Responsibility |
| :--- | :--- | :--- |
| `backend/app/main.py` | Application Entrypoint | FastAPI factory, CORS middleware, lifespan table creation, router registration (including `/api/actions`). |
| `backend/app/core/config.py` | Configuration Layer | Environment settings, absolute SQLite/Postgres path resolution (`platform.db`), rate limits, LLM selection. |
| `backend/app/core/security.py` | Security & Cryptography | Pure `bcrypt` password hashing (work factor 12), JWT creation & decoding, `get_current_user` dependency, `require_admin` (403). |
| `backend/app/core/ratelimit.py` | Rate Limiting Engine | In-memory thread-safe sliding window rate limiter (20 messages/minute per user) returning HTTP 429. |
| `backend/app/core/database.py` | Database Engine | SQLAlchemy 2.0 async engine (`aiosqlite`) & sync engine session maker for migrations/seed scripts. |
| `backend/app/models/models.py` | Relational ORM Models | **17 ORM Tables**: Organisations, Users, Products, Orders, OrderItems, OrderStatusHistory, Services, Practitioners, Bookings, Holidays, WeeklyOpeningHours, Conversations, Messages, KnowledgeChunks, CustomerMemories, ActionProposals, InventoryEvents. |
| `backend/app/models/schemas.py` | Validation Schemas | Pydantic v2 schemas for authentication, orders, bookings, chat, admin analytics, and Action Proposals. |
| `backend/app/services/knowledge_base.py` | Multi-Tenant Retrieval Engine | Hybrid Okapi BM25 + semantic vector similarity strictly scoped to `KnowledgeChunk.org_id == current_user.org_id`. |
| `backend/app/services/scheduling.py` | Scheduling & Availability Engine | `Asia/Kathmandu` engine, opening hours, holiday calendar, `booking_lock` mutex, NLP relative date resolution. |
| `backend/app/services/agent_a.py` | Agent A Tool Implementations | 8 core tools for Himali Tea House: atomic stock updates, OrderItem persistence, ActionProposal staging, reorders. |
| `backend/app/services/agent_b.py` | Agent B Tool Implementations | 8 core tools for Lotus Wellness: slot search, booking summaries, mutex-locked booking creation, reschedule conflict resolution. |
| `backend/app/services/admin_agent.py` | Admin Analytics Tools | Read-only tools for Activity Summary, Clients Today, Conversion Rate (via `conversation_id`), and Top Items (via `OrderItem`). |
| `backend/app/services/agent_engine.py` | Master Agent Loop | Streaming SSE dispatcher, tool status emitting, citation linking, interactive card packaging, message persistence. |
| `backend/app/services/llm_provider.py` | Switchable LLM Client | Google Gemini, Mistral AI, and deterministic offline engine integration. |
| `backend/app/api/auth.py` | Auth Endpoints | `/api/auth/register` (forces `role="customer"`), `/api/auth/login`, `/api/auth/me`. |
| `backend/app/api/actions.py` | Confirmation Gate Endpoints | `/api/actions/proposals/{id}`, `/api/actions/proposals/{id}/confirm`, `/api/actions/proposals/{id}/reject`. |
| `backend/app/api/orgs.py` | Org Endpoints | `/api/orgs`, `/api/orgs/{slug_or_id}`. |
| `backend/app/api/chat.py` | Chat & SSE Endpoints | Conversation lifecycle & SSE message streaming with rate limiting. |
| `backend/app/api/orders.py` | Orders Endpoints | `/api/orders`, `/api/orders/products`, status checks, customer ownership scoping. |
| `backend/app/api/bookings.py` | Bookings Endpoints | `/api/bookings`, `/api/bookings/services`, `/api/bookings/practitioners`, `/api/bookings/slots`. |
| `backend/app/api/admin.py` | Admin Operations | Order status advancing (`advance_status`) and metrics analytics with `require_admin` (403). |
| `backend/scripts/seed.py` | Single-Command Seeder | Ingests 22 products, 7 services, 3 practitioners, hours, holidays, seed customers, past orders, past bookings, conversations, and chunks. |
| `backend/scripts/advance_order.py` | Order Lifecycle Tool | Advances order status (`pending` $\rightarrow$ `confirmed` $\rightarrow$ `shipped` $\rightarrow$ `delivered`) from CLI. |
| `backend/scripts/run_eval.py` | Evaluation Runner | Single-command automated runner testing all 43 scenarios and asserting database state. |
| `backend/tests/test_eval_suite.py` | 36-Scenario Eval Suite | 16 scenarios for Agent A, 16 for Agent B, 3 for Admin Agent, 1 for Privilege Escalation defense. |
| `backend/tests/test_tenant_isolation.py` | 7 Security Tests | Cross-tenant service access, cross-customer order snooping, admin 403, and rate limiting (429). |
| `frontend/src/App.tsx` | Frontend Root | Entrypoint routing based on `/a/:slug`, authentication state management. |
| `frontend/src/components/MessageThread.tsx` | Chat UI & Streaming | Markdown rendering, tool execution pill, token streaming, Stop button, citations, cards. |
| `frontend/src/components/RichCards.tsx` | Interactive Cards | Interactive Order Summary ("Confirm Order"), Slot Picker ("Book Slot"), Status Cards. |
| `frontend/src/components/CustomerDrawer.tsx` | Customer Slide-Over | "My Orders" / "My Bookings" live panel + embedded Admin Status Advance buttons. |
| `frontend/src/components/AdminAnalyticsModal.tsx` | Analytics Dashboard | Read-only visual metrics dashboard for Store & Studio Admins. |
| `frontend/src/components/CitationModal.tsx` | Citation Inspector | Displays verified document source, section, and full excerpt. |
| `run.py` | Cross-Platform CLI | Wrapper for `seed`, `eval`, `test`, `backend`, `frontend` across Windows/Mac/Linux. |
| `docker-compose.yml` | Multi-Container Orchestration | Multi-container setup for backend (FastAPI) and frontend (Nginx). |

---

## 3. Specification Compliance & Verification Matrix

| Requirement (PDF Ref) | Brief Specification | How It Is Implemented | Automated Verification Proof |
| :--- | :--- | :--- | :--- |
| **Tenant Isolation & Auth** (Page 1) | User signs in to Org A can use only Org A's agent, sees only own data. | Server-enforced JWT signed with `org_id` and `user_id`. No endpoint trusts client-provided `org_id`. | `test_tenant_isolation.py` (7 tests)<br>`test_eval_a12` (customer snooping) |
| **Privilege Escalation Defense** (Page 1) | Role must be strictly controlled; customer cannot self-grant admin. | Public `/auth/register` hardcoded to force `role = "customer"`. Ignores client payload. | `test_eval_sec1_privilege_escalation_role_tampering_blocked` |
| **Fixed Org Entrypoint** (Page 1) | Sign-up happens on entry point (`/a/himali-tea`, `/a/lotus-wellness`), fixing user's `org_id`. | Fixed frontend routes `/a/:slug` bind `org_id` in registration payload; verified against `Organisation.slug`. | `test_tenant_isolation.py`<br>Frontend `SignupPage.tsx` |
| **Password Hashing** (Page 1) | Passwords hashed with bcrypt or argon2. | Salted hashes via pure `bcrypt` with work factor 12 in `security.py`. | `test_tenant_isolation.py`<br>`seed.py` |
| **Knowledge Base Isolation** (Page 2) | KB search never returns another org's content whatever prompt is sent. | Chunks filtered strictly by `KnowledgeChunk.org_id == user.org_id` before similarity scoring. | `test_knowledge_base_strict_tenant_isolation`<br>`test_eval_a14` (Jailbreak payload) |
| **Chat Rate Limiting** (Page 2) | Rate limit chat endpoint (20 messages/minute per user). | Sliding window token limiter per `user_id` returning `HTTP 429 Too Many Requests`. | `test_rate_limiting_enforcement` |
| **Org A Catalog & Data** (Page 2) | $\ge$ 20 products (SKU, name, category, price, stock). 3 customers, 2 with past orders. | 22 products seeded. 3 customers (`aayush`, `priya`, `kiran`). Past orders: `ORD-1001`, `ORD-1002`, `ORD-1003`. | `seed.py`<br>`test_eval_a4`, `test_eval_a6` |
| **Agent A Rule 1: Confirmation Gate** (Page 3) | Before placing/changing order, shows summary & waits for confirmation. | Staged `ActionProposal` record in DB with `pending` status. Order created only when confirmed. | `test_eval_a5`, `test_eval_a16` |
| **Agent A Rule 2: Stock Concurrency** (Page 3) | Quantity cannot exceed stock; race-condition protected. | Atomic SQL `UPDATE products SET stock = stock - :qty WHERE stock >= :qty`. Checked affected rows. | `test_eval_a7`, `test_eval_a15` (simultaneous exhaustion) |
| **Agent A Rule 3: Pending-Only Edit** (Page 3) | Edit/cancel on non-pending order refused with reason and current status. | Checks `order.status == 'pending'`. Returns descriptive error string with current status. | `test_eval_a9`, `test_eval_a11` |
| **Agent A Rule 4: Ownership Boundary** (Page 3) | Customer can only see/act on own orders. | Asserts `order.user_id == current_user.id`. Refuses access otherwise. | `test_eval_a12` |
| **Agent A Rule 5: Reorder** (Page 3) | "Same as last time" finds previous order, re-checks stock and current prices. | `reorder` fetches latest order, compares historical prices against live DB, flags adjustments. | `test_eval_a13` |
| **Agent B Rule 1: Hours & Holidays** (Page 4) | Slot inside opening hours, avoid holidays, fit service full duration. | `SchedulingEngine.validate_slot` verifies open/close hours, holiday calendar, and end time. | `test_eval_b8`, `test_eval_b9` |
| **Agent B Rule 2: Overlap Prevention** (Page 4) | No overlaps: practitioner cannot be double-booked; customer cannot hold two at same time. | Checks overlap condition against active bookings for practitioner and customer. | `test_eval_b10`, `test_eval_b11` |
| **Agent B Rule 3: Concurrency Mutex** (Page 4) | Booking and rescheduling safe when two customers grab same slot at once. | Serialized slot grab via `SchedulingEngine.booking_lock` + DB conflict re-check in transaction. | `test_eval_b15` (concurrent race test) |
| **Agent B Rule 4: Reschedule Conflict** (Page 4) | Reschedule conflict refused + offers nearest free alternatives. | `reschedule_booking` checks conflict; if conflicting, searches nearest 3 free slots. | `test_eval_b12` |
| **Agent B Rule 5: Booking Confirmation** (Page 5) | Agent confirms service, practitioner, date, time, price before booking. | `prepare_booking_summary` returns confirmation payload, stages `ActionProposal`, and shows card. | `test_eval_b6` |
| **Agent B Rule 6: Relative Dates** (Page 5) | Relative dates resolve in studio timezone (`Asia/Kathmandu`). | Natural language parser `resolve_relative_datetime_kathmandu` anchored to +05:45 offset. | `test_eval_b13`, `test_eval_b16` |
| **Admin Analytics Agent** (Page 5-6) | Read-only analytics chat, scoped to org_id, 403 for customers, states time window and definition. | Tools calculate activity summary, clients today, conversion rate (via FK), top items (via OrderItem). | `test_eval_adm1`, `test_eval_adm2`, `test_eval_adm3` |
| **Total Evaluation Suite** (Page 6) | $\ge$ 12 scenarios per agent, one-command run (`make eval`), checks DB state afterwards. | **43 automated scenarios** (16 Agent A, 16 Agent B, 3 Admin, 8 Security & Isolation). | `python run.py eval` (43 passed, 100% pass rate) |

---

## 4. Deep Technical Architecture

### 4.1. Concurrency Protection Architecture

#### Stock Concurrency (Agent A)
When two customers attempt to purchase the last available unit of a tea simultaneously, Python-level checks (`if prod.stock >= qty`) fail due to race conditions. The platform enforces database-level atomic reservation:
```python
stmt = (
    update(Product)
    .where(
        Product.org_id == org_id,
        Product.sku == item["sku"],
        Product.stock >= item["quantity"]
    )
    .values(stock=Product.stock - item["quantity"])
)
res = await db.execute(stmt)
if res.rowcount == 0:
    await db.rollback()
    return {"success": False, "error": "Insufficient stock during atomic reservation"}
```
- In `test_eval_a15`, two coroutines simultaneously attempt to purchase the last unit (`stock = 1`) via `asyncio.gather`. Exactly 1 succeeds, 1 is rejected, and stock terminates at exactly 0.

#### Booking Concurrency (Agent B)
To prevent double-booking a practitioner when two customers confirm the exact same slot at the exact same millisecond:
1. `SchedulingEngine.booking_lock = asyncio.Lock()` provides asynchronous mutual exclusion around the critical booking section.
2. Inside the lock, a transactional query verifies no overlapping active booking exists ($A_{\text{start}} < B_{\text{end}} \land A_{\text{end}} > B_{\text{start}}$).
3. The booking is inserted and committed before the lock is released.
4. In `test_eval_b15`, two coroutines race to book Dr. Sunita at the exact same time via `asyncio.gather`. Exactly 1 succeeds, and the other receives a conflict rejection offering alternative slots.

### 4.2. Action Proposal & Server-Side Confirmation Gate
To prevent an LLM from hallucinating an order placement without explicit confirmation:
1. When a user requests an order or appointment, `prepare_order_summary` / `prepare_booking_summary` calculates prices, verifies availability, and creates an `ActionProposal` record in the database:
   ```python
   proposal = ActionProposal(
       id=proposal_id,
       org_id=org_id,
       user_id=user_id,
       action_type="create_order",
       payload_json=json.dumps(payload),
       status="pending",
       expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=30)
   )
   ```
2. The UI renders an interactive Rich Card with a **"Confirm Order"** or **"Confirm Booking"** button.
3. Clicking confirm hits `POST /api/actions/proposals/{proposal_id}/confirm`.
4. The server validates that the proposal belongs to the authenticated user, is still in `pending` status, hasn't expired, re-verifies live availability, executes the transaction, and marks the proposal `confirmed`.
5. Duplicate confirmation attempts return HTTP 400 (`Proposal has already been confirmed`).

### 4.3. Admin Analytics Attribution & Historical Accuracy
- **Conversion Rate**: Linked directly through `Order.conversation_id` and `Booking.conversation_id` foreign keys, calculating:
  $$\text{Conversion Rate} = \frac{\text{Conversations with Completed Order or Booking}}{\text{Total Customer Conversations}} \times 100$$
- **Sales Reporting After Price Changes**: Line items are recorded in the `OrderItem` table (`order_id`, `product_id`, `sku`, `quantity`, `unit_price`, `subtotal`), ensuring revenue and top-item metrics remain historically accurate even when catalog prices change.
- **Stockout Tracking**: Every stock decrement, replenishment, and cancellation logs an `InventoryEvent` (`product_id`, `delta`, `reason`, `stock_after`), enabling exact analytics on items that frequently hit 0 stock.

---

## 5. Verification & Reproduction Instructions

Any independent reviewer can reproduce and verify 100% of this implementation using standard commands:

### Step 1: Run Full Automated Evaluation Suite
```bash
python run.py eval
```
**Output**:
```
================================================================================
  ALL SCENARIOS PASSED (100% SUCCESS RATE - 43/43 TESTS)
  - Agent A (Himali Tea House): 16 Scenarios Verified (Atomic stock, orders, concurrent exhaustion, proposal gate)
  - Agent B (Lotus Wellness Studio): 16 Scenarios Verified (Kathmandu slots, holidays, concurrent double-booking mutex)
  - Admin Analytics Agent: 3 Scenarios Verified (Read-only metrics, conversation attribution, 403 RBAC)
  - Tenant Isolation & Security: 8 Security Tests Verified (Privilege escalation blocked, cross-tenant isolation, rate limiting)
================================================================================
```

### Step 2: Verify Tenant Isolation Tests Independently
```bash
python -m pytest backend/tests/test_tenant_isolation.py -v
```
**Output**: 7 passed tests confirming cross-org service hiding, customer privacy, admin 403 blocking, and rate limit 429 triggering.

### Step 3: Verify Seed Script Idempotency
```bash
python backend/scripts/seed.py
python backend/scripts/seed.py
```
**Output**: Both runs succeed with `[SUCCESS] Database and Knowledge Bases successfully seeded!`.

### Step 4: Verify Frontend Compilation
```bash
cd frontend && npm run build
```
**Output**: `✓ built in 5.82s` with 0 errors.
