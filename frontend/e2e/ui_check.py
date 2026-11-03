"""Browser checks for the web app, driven with Playwright (Python).

Covers what the unit and API tests cannot: that the real UI works at 375px and 1280px. Entry points and branding,
sign-up bound to the entry point, markdown, slot picker in Kathmandu time, confirm cards and their persisted
state, the cross-tenant screen, session expiry, streaming with Stop, the admin panels.

    # terminal 1:  make seed && make run-backend      (LLM_PROVIDER=mock keeps it deterministic and free)
    # terminal 2:  make run-frontend
    pip install playwright            # uses an installed Edge or Chrome, no browser download
    python frontend/e2e/ui_check.py

Reseed first (`make seed`) for a repeatable run; the checks create a user and a few bookings and orders.
Screenshots are written to frontend/e2e/shots/.
Environment: BROWSER_CHANNEL (default msedge, or chrome), BASE_URL (default http://localhost:3000),
API_URL (default http://127.0.0.1:8000/api).
"""
import datetime
import json
import os
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("BASE_URL", "http://localhost:3000")
API = os.environ.get("API_URL", "http://127.0.0.1:8000/api")
SHOTS = Path(__file__).resolve().parent / "shots"
SHOTS.mkdir(exist_ok=True)
results = []


def call(method, path, token=None, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def api_login(email, org):
    return call("POST", "/auth/login", body={"email": email, "password": "Password123!", "org_id": org})[1]["access_token"]


def step(name):
    def deco(fn):
        def run(*a, **k):
            try:
                fn(*a, **k)
                results.append((name, "PASS", ""))
                print("PASS", name)
            except Exception as exc:  # noqa: BLE001
                try:  # a picture of the page at the moment of failure
                    globals()["page"].screenshot(path=str(SHOTS / ("FAIL_" + "".join(c if c.isalnum() else "_" for c in name)[:50] + ".png")))
                except Exception:  # noqa: BLE001
                    pass
                results.append((name, "FAIL", str(exc)[:300]))
                print("FAIL", name, "->", str(exc)[:300])
        return run
    return deco


def no_hscroll(page, label):
    width, inner = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    assert width <= inner + 1, f"{label}: horizontal scroll ({width} > {inner})"


def send(page, text):
    box = page.get_by_label("Message", exact=True)
    box.fill(text)
    box.press("Enter")


def wait_reply(page, count_before=None):
    """A reply is finished when the Stop button has come and gone and the saved thread has reloaded."""
    page.wait_for_timeout(150)
    stop = page.get_by_role("button", name="Stop")
    try:
        stop.wait_for(state="visible", timeout=1500)
    except Exception:  # noqa: BLE001 - a very fast reply may be over before the button shows
        pass
    stop.wait_for(state="hidden", timeout=40000)
    page.wait_for_timeout(800)


def bubbles(page):
    return page.locator("[role=log] > div .md-body").count()


def free_day(token, service, practitioner=None):
    for offset in range(3, 25):
        day = (datetime.date.today() + datetime.timedelta(days=offset)).isoformat()
        code, body = call("GET", f"/bookings/slots?service_id={service}&date={day}" + (f"&practitioner_id={practitioner}" if practitioner else ""), token)
        if code == 200 and len(body["slots"]) >= 4:
            return day, body["slots"]
    raise RuntimeError("no free day found")


with sync_playwright() as pw:
    browser = pw.chromium.launch(channel=os.environ.get("BROWSER_CHANNEL", "msedge"), headless=True)

    # ======================= PHONE (375 px) =======================
    ctx = browser.new_context(viewport={"width": 375, "height": 812}, device_scale_factor=2, is_mobile=True, has_touch=True)
    page = ctx.new_page()
    page.on("pageerror", lambda e: print("PAGEERROR", e))

    @step("entry point shows its own name, colours and the agent greeting (375px)")
    def entry():
        page.goto(f"{BASE}/a/lotus-wellness")
        expect(page.get_by_role("heading", name="Lotus Wellness Studio")).to_be_visible()
        expect(page.get_by_text("Maya", exact=False).first).to_be_visible()
        expect(page.get_by_text("Namaste! Welcome to Lotus Wellness Studio")).to_be_visible()
        assert "Lotus" in page.title()
        no_hscroll(page, "login")
        page.screenshot(path=str(SHOTS / "01_lotus_entry_375.png"), full_page=True)
    entry()

    @step("himali entry point has different branding")
    def entry_a():
        page.goto(f"{BASE}/a/himali-tea")
        expect(page.get_by_role("heading", name="Himali Tea House")).to_be_visible()
        expect(page.get_by_text("Tenzin", exact=False).first).to_be_visible()
        page.screenshot(path=str(SHOTS / "02_himali_entry_375.png"), full_page=True)
    entry_a()

    email = f"ui{datetime.datetime.now().strftime('%H%M%S')}@example.com"

    @step("sign-up on the Lotus entry point creates a Lotus (org_b) customer, not a Himali one")
    def signup():
        page.goto(f"{BASE}/a/lotus-wellness")
        page.get_by_role("button", name="Create an account at Lotus Wellness Studio").click()
        expect(page.get_by_text("Your account will belong to Lotus Wellness Studio")).to_be_visible()
        page.get_by_placeholder("Jane Doe").fill("UI Tester")
        page.get_by_placeholder("jane@example.com").fill(email)
        page.get_by_placeholder("Minimum 8 characters").fill("Password123!")
        page.get_by_role("button", name="Register Account").click()
        expect(page.get_by_role("heading", name="Lotus Wellness Studio")).to_be_visible(timeout=10000)
        token = page.evaluate("localStorage.getItem('auth_token')")
        code, me = call("GET", "/auth/me", token)
        assert me["org_id"] == "org_b" and me["role"] == "customer", me
        page.screenshot(path=str(SHOTS / "03_after_signup_chat_375.png"))
        no_hscroll(page, "chat after signup")
    signup()

    @step("markdown renders (lists, bold, code block) and Shift+Enter adds a line (375px)")
    def markdown():
        box = page.get_by_label("Message", exact=True)
        box.fill("first line")
        box.press("Shift+Enter")
        box.type("**bold** word")
        box.press("Shift+Enter")
        box.type("- item one")
        box.press("Shift+Enter")
        box.type("- item two")
        box.press("Shift+Enter")
        box.type("```")
        box.press("Shift+Enter")
        box.type("print('hi')")
        box.press("Shift+Enter")
        box.type("```")
        assert "\n" in box.input_value() and not page.locator("[role=log] .md-body").count()
        before = bubbles(page)
        box.press("Enter")
        wait_reply(page, before + 0)
        expect(page.locator(".md-body strong", has_text="bold")).to_be_visible()
        assert page.locator(".md-body ul li").count() == 2
        assert page.locator(".md-body pre code").count() == 1
        no_hscroll(page, "markdown thread")
        page.screenshot(path=str(SHOTS / "04_markdown_375.png"))
    markdown()

    @step("conversation title is set from the first message")
    def title():
        page.get_by_label("Toggle navigation").click()
        expect(page.get_by_text("first line", exact=False).first).to_be_visible()
        page.screenshot(path=str(SHOTS / "05_sidebar_375.png"))
        page.mouse.click(345, 400)  # the dimmed area beside the drawer closes it
        page.wait_for_timeout(400)
    title()

    @step("sign out revokes the token on the server and returns to the entry point")
    def signout():
        token = page.evaluate("localStorage.getItem('auth_token')")
        page.get_by_label("Sign out").click()
        expect(page.get_by_role("button", name="Sign in to Lotus Wellness Studio")).to_be_visible()  # sign-in form, not sign-up
        assert page.evaluate("localStorage.getItem('auth_token')") is None
        code, _ = call("GET", "/auth/me", token)
        assert code == 401, f"old token still works ({code})"
    signout()

    sita = api_login("sita@lotus.test", "org_b")
    day, slots = free_day(sita, "srv_5")
    rohan = api_login("rohan@lotus.test", "org_b")
    rohan_booking = next(b for b in call("GET", "/bookings", rohan)[1] if b["id"] == "BKG-2003")

    @step("quick login as Sita lands straight in the Lotus chat")
    def quick():
        page.get_by_role("button", name="Sita (customer)").click()
        expect(page.get_by_label("Message", exact=True)).to_be_visible(timeout=10000)
        expect(page.get_by_role("heading", name="Lotus Wellness Studio")).to_be_visible()
    quick()

    @step("slot picker shows times in Kathmandu time with a pick-a-slot button")
    def slots_card():
        before = bubbles(page)
        send(page, f"Show free slots for srv_5 on {day}")
        wait_reply(page, before + 0)
        card = page.get_by_role("group", name="Available time slots")
        expect(card).to_be_visible()
        expect(card.get_by_text("Asia/Kathmandu (UTC+05:45)")).to_be_visible()
        first = card.get_by_role("button").first
        shown = first.inner_text().split("\n")[0]
        # the first slot is the studio's opening time, in Kathmandu wall-clock time
        assert any(x in shown.lower() for x in ("am", "pm")), shown
        expected = slots[0]["start_time"]  # 2026-11-12T10:00:00+05:45
        hh = int(expected[11:13]) % 12 or 12
        assert shown.startswith(f"{hh}:"), f"{shown} vs {expected}"
        no_hscroll(page, "slot picker")
        page.screenshot(path=str(SHOTS / "06_slot_picker_375.png"))
        first.click()
    slots_card()

    @step("choosing a slot produces a booking summary with a Confirm button; nothing is saved yet")
    def summary():
        card = page.get_by_role("group", name="Appointment summary").last
        expect(card).to_be_visible(timeout=20000)
        expect(card.get_by_role("button", name="Confirm Booking")).to_be_visible()
        expect(card.get_by_role("button", name="Not now")).to_be_visible()
        expect(card.get_by_text("Private 1-on-1 Hatha & Vinyasa Yoga")).to_be_visible()
        no_hscroll(page, "booking summary")
        page.screenshot(path=str(SHOTS / "07_booking_summary_375.png"))
        mine = call("GET", "/bookings", sita)[1]
        assert not any(b["service_id"] == "srv_5" and b["start_time"].startswith(day) for b in mine), "saved before confirm"
    summary()

    @step("Confirm saves the booking, the card turns to Confirmed, and the outcome stays after a reload")
    def confirm():
        card = page.get_by_role("group", name="Appointment summary").last
        card.get_by_role("button", name="Confirm Booking").click()
        expect(card.get_by_text("Confirmed. This change has been saved.")).to_be_visible(timeout=10000)
        expect(page.get_by_role("group", name="Appointment confirmed")).to_be_visible(timeout=10000)
        mine = call("GET", "/bookings", sita)[1]
        assert any(b["service_id"] == "srv_5" and b["start_time"].startswith(day) and b["status"] == "confirmed" for b in mine)
        page.screenshot(path=str(SHOTS / "08_confirmed_375.png"))
        page.reload()
        expect(page.get_by_role("group", name="Appointment confirmed")).to_be_visible(timeout=10000)
        old = page.get_by_role("group", name="Appointment summary").last
        expect(old.get_by_text("Confirmed. This change has been saved.")).to_be_visible()
        assert old.get_by_role("button", name="Confirm Booking").count() == 0, "Confirm button came back after reload"
        page.screenshot(path=str(SHOTS / "09_after_reload_375.png"))
    confirm()

    @step("Shift+Enter lines stay on separate lines in the sent message")
    def newlines():
        box = page.get_by_label("Message", exact=True)
        box.fill("line one")
        box.press("Shift+Enter")
        box.type("line two")
        before = bubbles(page)
        box.press("Enter")
        wait_reply(page, before + 0)
        last_user = page.locator("[role=log] > div .md-body").filter(has_text="line one").last
        white_space = last_user.evaluate("e => getComputedStyle(e.querySelector('p')).whiteSpace")
        assert white_space == "pre-line", white_space  # a single newline is kept as a line break
    newlines()

    @step("My Bookings panel matches what the agent said, in studio time")
    def panel():
        page.get_by_label("My bookings").click()
        dlg = page.get_by_role("dialog")
        expect(dlg.get_by_text("Private 1-on-1 Hatha & Vinyasa Yoga").first).to_be_visible()
        expect(dlg.get_by_text("Asia/Kathmandu")).to_be_visible()
        expect(dlg.get_by_text("completed", exact=True)).to_be_visible()  # BKG-2002 is in the past
        no_hscroll(page, "bookings drawer")
        page.screenshot(path=str(SHOTS / "10_bookings_panel_375.png"))
        page.get_by_label("Close").click()
    panel()

    @step("conflicting reschedule shows the refusal card with nearest free alternatives")
    def conflict():
        # a second booking with Master Tenzing on a different day, then try to move it onto Rohan's slot
        other_day, _ = free_day(sita, "srv_1")
        before = bubbles(page)
        send(page, f"Book srv_1 with prac_2 at {other_day}T10:00:00+05:45")
        wait_reply(page, before + 0)
        card = page.get_by_role("group", name="Appointment summary").last
        card.get_by_role("button", name="Confirm Booking").click()
        expect(card.get_by_text("Confirmed. This change has been saved.")).to_be_visible(timeout=10000)
        mine = next(b for b in call("GET", "/bookings", sita)[1] if b["start_time"].startswith(other_day) and b["service_id"] == "srv_1")
        before = bubbles(page)
        send(page, f"Reschedule booking {mine['id']} to {rohan_booking['start_time']}")
        wait_reply(page, before + 1)
        conflict_card = page.get_by_role("group", name="Reschedule conflict").last
        expect(conflict_card).to_be_visible(timeout=10000)
        expect(conflict_card.get_by_text("Nearest free alternatives")).to_be_visible()
        assert conflict_card.get_by_role("button").count() == 3
        no_hscroll(page, "conflict")
        page.screenshot(path=str(SHOTS / "11_conflict_375.png"))
    conflict()

    @step("signed in to Lotus, opening /a/himali-tea shows the cross-tenant block (no Himali data)")
    def guard():
        page.goto(f"{BASE}/a/himali-tea")
        expect(page.get_by_role("heading", name="Cross-Tenant Access Blocked")).to_be_visible()
        assert page.get_by_text("Himali Tea House").count() == 0, "the other tenant's name must not be rendered"
        assert page.get_by_label("Message", exact=True).count() == 0
        page.screenshot(path=str(SHOTS / "12_tenant_guard_375.png"))
        page.get_by_role("button", name="Return to Lotus Wellness Studio").click()
        expect(page.get_by_label("Message", exact=True)).to_be_visible(timeout=10000)
    guard()

    @step("a session that ends in another tab returns the user to the entry point with a notice")
    def expiry():
        token = page.evaluate("localStorage.getItem('auth_token')")
        call("POST", "/auth/logout", token)  # signed out elsewhere
        try:  # the app may already have noticed (background refresh) before the message is typed
            page.get_by_label("Message", exact=True).fill("hello again friend", timeout=3000)
            page.get_by_label("Message", exact=True).press("Enter", timeout=3000)
        except Exception:  # noqa: BLE001
            pass
        expect(page.get_by_text("Your session has ended. Please sign in again.")).to_be_visible(timeout=10000)
        page.screenshot(path=str(SHOTS / "13_session_ended_375.png"))
    expiry()
    ctx.close()

    # ======================= DESKTOP (1280 px) =======================
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()

    @step("customer order flow on desktop: same-as-last-time card, confirm, status panel")
    def order_flow():
        page.goto(f"{BASE}/a/himali-tea")
        page.get_by_role("button", name="Aayush (customer)").click()
        expect(page.get_by_label("Message", exact=True)).to_be_visible(timeout=10000)
        before = bubbles(page)
        send(page, "Same as last time")
        wait_reply(page, before + 0)
        card = page.get_by_role("group", name="Order summary").last
        expect(card.get_by_role("button", name="Confirm Order")).to_be_visible()
        page.screenshot(path=str(SHOTS / "20_order_summary_1280.png"))
        card.get_by_role("button", name="Confirm Order").click()
        expect(card.get_by_text("Confirmed. This change has been saved.")).to_be_visible(timeout=10000)
        expect(page.get_by_role("group", name="Order placed").last).to_be_visible(timeout=10000)
        before = bubbles(page)
        send(page, "Show my orders")
        wait_reply(page, before + 0)
        expect(page.get_by_role("group", name="Your orders").last).to_be_visible()
        page.get_by_label("My orders").click()
        dlg = page.get_by_role("dialog")
        expect(dlg.get_by_text("#ORD-1001")).to_be_visible()
        page.screenshot(path=str(SHOTS / "21_orders_panel_1280.png"))
        page.get_by_label("Close").click()
    order_flow()

    @step("a knowledge answer has clickable citation chips that open the source excerpt")
    def citations():
        before = bubbles(page)
        send(page, "What is your return policy?")
        wait_reply(page, before + 0)
        chip = page.get_by_label("Sources").last.get_by_role("button").first
        expect(chip).to_be_visible()
        assert "›" in chip.inner_text() and ".md" in chip.inner_text()
        chip.click()
        expect(page.get_by_text("Knowledge Base Source")).to_be_visible()
        page.screenshot(path=str(SHOTS / "22_citation_1280.png"))
        page.get_by_role("button", name="Close Excerpt").click()
    citations()

    @step("responses stream and the Stop button ends one early")
    def stop_button():
        before = bubbles(page)
        box = page.get_by_label("Message", exact=True)
        box.fill("How should I brew the Himalayan Spring Silver Needle white tea?")
        box.press("Enter")
        stop = page.get_by_role("button", name="Stop")
        expect(stop).to_be_visible(timeout=5000)
        page.wait_for_timeout(500)  # some words have streamed
        partial = page.locator("[role=log] .animate-pulse").count()
        stop.click()
        expect(stop).to_have_count(0)
        expect(page.get_by_text("(stopped)")).to_be_visible(timeout=5000)
        page.screenshot(path=str(SHOTS / "24_stopped_1280.png"))
        # the box is usable again straight away
        expect(page.get_by_label("Message", exact=True)).to_be_enabled()
    stop_button()

    @step("cancel card is labelled for cancelling and Not now discards it")
    def cancel_discard():
        before = bubbles(page)
        send(page, "Cancel order ORD-1001")  # confirmed already: refused, no card
        wait_reply(page, before + 0)
        assert page.get_by_role("group", name="Order summary").filter(has_text="cancellation").count() == 0
        # a pending order of their own to cancel
        before = bubbles(page)
        send(page, "Order 1 x HT-IN-01")
        wait_reply(page, before + 0)
        card = page.get_by_role("group", name="Order summary").last
        card.get_by_role("button", name="Not now").click()
        expect(card.get_by_text("Discarded. Nothing was changed.")).to_be_visible(timeout=10000)
        page.screenshot(path=str(SHOTS / "23_discarded_1280.png"))
    cancel_discard()
    page.get_by_label("Sign out").click()

    @step("admin sees all orders, can advance a status, and opens analytics with definitions")
    def admin():
        page.get_by_role("button", name="Himali admin").click()
        expect(page.get_by_label("Message", exact=True)).to_be_visible(timeout=10000)
        expect(page.get_by_text("Admin analytics agent")).to_be_visible(timeout=10000)  # staff land in Admin Chat
        page.get_by_role("button", name="Orders").click()
        dlg = page.get_by_role("dialog")
        expect(dlg.get_by_text("#ORD-1003")).to_be_visible()
        expect(dlg.get_by_text("priya@himali.test").first).to_be_visible()
        row = dlg.locator(r"div.p-3\.5", has_text="#ORD-1003")
        assert row.count() == 1
        row.get_by_role("button", name="Confirm → confirmed").click()
        expect(dlg.locator(r"div.p-3\.5", has_text="#ORD-1003").get_by_text("confirmed", exact=True).first).to_be_visible(timeout=10000)
        page.screenshot(path=str(SHOTS / "30_admin_orders_1280.png"))
        page.get_by_label("Close").click()
        page.get_by_role("button", name="Analytics", exact=True).click()
        expect(page.get_by_text("How these numbers are calculated")).to_be_visible(timeout=10000)
        page.get_by_text("How these numbers are calculated").click()  # opens the definitions
        expect(page.get_by_text("Asia/Kathmandu").first).to_be_visible()
        page.screenshot(path=str(SHOTS / "31_admin_analytics_1280.png"), full_page=True)
        page.keyboard.press("Escape")
        page.locator("button:has(svg.lucide-x)").first.click()
    admin()

    @step("admin chat answers with window and definition and refuses writes")
    def admin_chat():
        page.get_by_role("button", name="Customer view").click()
        page.get_by_role("button", name="Admin Chat").click()
        expect(page.get_by_text("Admin analytics agent")).to_be_visible(timeout=10000)
        before = bubbles(page)
        send(page, "How did we do over the last 30 days?")
        wait_reply(page, before + 0)
        expect(page.get_by_text("Definition:", exact=False).last).to_be_visible()
        before = bubbles(page)
        send(page, "Delete all orders")
        wait_reply(page, before + 1)
        expect(page.get_by_text("read-only", exact=False).last).to_be_visible()
        page.screenshot(path=str(SHOTS / "32_admin_chat_1280.png"))
    admin_chat()
    ctx.close()
    browser.close()

fails = [r for r in results if r[1] == "FAIL"]
print(f"\n{len(results) - len(fails)}/{len(results)} UI checks passed")
sys.exit(1 if fails else 0)
