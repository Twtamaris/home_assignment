"""One-command eval: runs every scenario and reports pass/fail per scenario, grouped by agent.

    python scripts/run_eval.py              all scenarios, offline (mock model, BM25, throw-away database)
    python scripts/run_eval.py -k a05       forward any pytest selection

Every scenario drives the real stack (login, chat endpoint, tool loop, confirmation card, confirm endpoint)
and then asserts on database state, not only on reply text. The tests build their own temporary database
from the seed files and never read .env, call a model API, or touch the development database.
The numbers printed here are counted from the results of this run.
"""
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import OrderedDict
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

MIN_SCENARIOS_PER_AGENT = 12

GROUPS = OrderedDict([
    ("tests.test_eval_agent_a", ("Agent A  Himali Tea House (ordering)", True)),
    ("tests.test_eval_agent_b", ("Agent B  Lotus Wellness Studio (booking)", True)),
    ("tests.test_eval_admin", ("Admin analytics agent (stretch)", False)),
    ("tests.test_tenant_isolation", ("Tenant isolation and access control", False)),
    ("tests.test_auth", ("Auth, sessions, throttling", False)),
    ("tests.test_confirmation_gate", ("Confirmation gate and concurrency", False)),
    ("tests.test_third_org", ("Third organisation by configuration (stretch)", False)),
    ("tests.test_providers", ("Chat provider adapters (Mistral, Groq, Ollama)", False)),
])


def scenario_name(raw: str) -> str:
    """test_a05_order_waits_for_confirmation -> 'a05  order waits for confirmation'"""
    stem = re.sub(r"\[.*\]$", "", raw)
    stem = re.sub(r"^test_", "", stem)
    match = re.match(r"^([a-z]+\d+[a-z]?)_(.*)$", stem)
    code, rest = (match.group(1), match.group(2)) if match else ("", stem)
    return f"{code:<6}{rest.replace('_', ' ')}".rstrip()


def main() -> int:
    junit = Path(tempfile.mkdtemp(prefix="eval_report_")) / "results.xml"
    command = [
        sys.executable, "-m", "pytest", "tests", "-q", "--tb=short", "-W", "ignore", "-p", "no:cacheprovider",
        f"--junitxml={junit}", *sys.argv[1:],
    ]
    print("=" * 88)
    print("  EVAL SUITE  (offline: mock model, BM25 retrieval, temporary database built from the seed files)")
    print("=" * 88)
    proc = subprocess.run(command, cwd=str(backend_dir), env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    if not junit.exists():
        print("[!] pytest produced no report")
        return proc.returncode or 1

    scenarios = {key: OrderedDict() for key in GROUPS}
    for case in ET.parse(junit).getroot().iter("testcase"):
        module = case.get("classname", "")
        if module not in scenarios:
            continue
        name = scenario_name(case.get("name", ""))
        failed = case.find("failure") is not None or case.find("error") is not None
        skipped = case.find("skipped") is not None
        prior = scenarios[module].get(name, "PASS")
        scenarios[module][name] = "FAIL" if failed or prior == "FAIL" else ("SKIP" if skipped else "PASS")

    print("\n" + "=" * 88)
    print("  RESULTS PER SCENARIO")
    print("=" * 88)
    total = passed = 0
    shortfall = []
    for module, (title, per_agent) in GROUPS.items():
        results = scenarios[module]
        if not results:
            continue
        ok = sum(1 for status in results.values() if status == "PASS")
        total += len(results)
        passed += ok
        print(f"\n{title}: {ok}/{len(results)} passed")
        for name, status in results.items():
            print(f"  {'PASS' if status == 'PASS' else status}  {name}")
        if per_agent and len(results) < MIN_SCENARIOS_PER_AGENT:
            shortfall.append(title)

    print("\n" + "=" * 88)
    verdict = "ALL SCENARIOS PASSED" if proc.returncode == 0 and passed == total else "FAILURES PRESENT"
    print(f"  {verdict}: {passed}/{total} scenarios passed")
    if shortfall:
        print(f"  [!] fewer than {MIN_SCENARIOS_PER_AGENT} scenarios for: {', '.join(shortfall)}")
    print("  Offline run: LLM_PROVIDER=mock (a deterministic stand-in, not a language model), EMBEDDING_PROVIDER=bm25.")
    print("  Run `python scripts/live_eval.py` for the same checks against the real model.")
    print("=" * 88)
    return proc.returncode or (1 if shortfall else 0)


if __name__ == "__main__":
    sys.exit(main())
