"""Test environment. Runs before any test module imports the app.

Every run gets its own throw-away SQLite file and Chroma folder, seeded from the seed files, with the
mock model and BM25 retrieval. Nothing here reads .env, calls a model API, or touches the dev database.
"""
import atexit
import datetime
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

_workdir = Path(tempfile.mkdtemp(prefix="agent_platform_tests_"))
atexit.register(shutil.rmtree, _workdir, ignore_errors=True)

os.environ.update({
    "DATABASE_URL": f"sqlite+aiosqlite:///{(_workdir / 'eval.db').as_posix()}",
    "SYNC_DATABASE_URL": f"sqlite:///{(_workdir / 'eval.db').as_posix()}",
    "CHROMA_PATH": str(_workdir / "chroma"),
    "LLM_PROVIDER": "mock",
    "EMBEDDING_PROVIDER": "bm25",
    "GEMINI_API_KEY": "",
    "MISTRAL_API_KEY": "",
    "SECRET_KEY": os.environ.get("TEST_SECRET_KEY", "test-only-secret-key-not-used-anywhere-else"),
    "BCRYPT_ROUNDS": "4",
    "MOCK_TOKEN_DELAY_MS": "0",
})


def _reseed() -> None:
    result = subprocess.run(
        [sys.executable, str(BACKEND_DIR / "scripts" / "seed.py")],
        env=os.environ, capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        raise RuntimeError(f"Seeding the test database failed:\n{result.stdout}\n{result.stderr}")


_reseed()

import pytest  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _seed_per_module():
    """Every test file starts from the seed data, so no file depends on what another one did."""
    if not getattr(_seed_per_module, "seeded", False):
        _seed_per_module.seeded = True  # the import-time seed above covers the first module
    else:
        _reseed()
    yield


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """The limiters are process-wide. Reset them so one test cannot starve the next."""
    from app.api.auth import auth_rate_limiter
    from app.core.ratelimit import chat_rate_limiter

    chat_rate_limiter.history.clear()
    auth_rate_limiter.history.clear()
    yield


class _DayAllocator:
    """Hands out distinct, open, non-holiday studio days so tests never collide on a slot."""

    def __init__(self, start_offset: int = 3):
        self._next = start_offset

    async def next_open_day(self) -> datetime.date:
        from sqlalchemy import select
        from app.core.database import AsyncSessionLocal
        from app.models.models import Holiday
        from app.services.scheduling import SchedulingEngine

        from app.models.models import Booking

        async with AsyncSessionLocal() as session:
            closed = {h.holiday_date for h in (await session.execute(select(Holiday))).scalars().all()}
            busy = {
                b.start_time.date().isoformat()
                for b in (await session.execute(select(Booking).where(Booking.status.in_(["confirmed", "rescheduled"])))).scalars().all()
            }
        while True:
            day = (SchedulingEngine.now_kathmandu() + datetime.timedelta(days=self._next)).date()
            self._next += 1
            if day.isoformat() not in closed and day.isoformat() not in busy:
                return day


_days = _DayAllocator()


@pytest.fixture
def open_day():
    """Async factory: `await open_day()` returns a fresh, bookable studio date."""
    return _days.next_open_day
