from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import create_engine, event, text
from app.core.config import settings

_sqlite = "sqlite" in settings.DATABASE_URL
_connect_args = {"check_same_thread": False, "timeout": settings.SQLITE_BUSY_TIMEOUT_MS / 1000} if _sqlite else {}

# Async Engine for FastAPI
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# Sync Engine for Seeding and offline CLI scripts
sync_engine = create_engine(
    settings.SYNC_DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False, "timeout": settings.SQLITE_BUSY_TIMEOUT_MS / 1000} if "sqlite" in settings.SYNC_DATABASE_URL else {},
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()


def _sqlite_on_connect(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute(f"PRAGMA busy_timeout = {int(settings.SQLITE_BUSY_TIMEOUT_MS)}")
    cursor.execute("PRAGMA journal_mode = WAL")
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.close()


def _sqlite_on_begin(connection):
    """Ask sqlite3 to open the driver's implicit transaction as BEGIN IMMEDIATE.

    SQLAlchemy's begin hook runs before the first statement. Setting the
    isolation level here makes that statement take the write lock, and
    session.commit() still commits the same transaction. The raw sqlite3
    connection is used because the async adapter's setter needs an event loop.
    """
    dbapi = connection.connection
    inner = getattr(dbapi, "_connection", None)
    sqlite_conn = getattr(inner, "_conn", None) if inner is not None else None
    target = sqlite_conn if sqlite_conn is not None else dbapi
    target.isolation_level = "IMMEDIATE"


if _sqlite:
    event.listen(async_engine.sync_engine, "connect", _sqlite_on_connect)
    event.listen(sync_engine, "connect", _sqlite_on_connect)
    event.listen(async_engine.sync_engine, "begin", _sqlite_on_begin)
    event.listen(sync_engine, "begin", _sqlite_on_begin)


def upgrade_sqlite_schema(sync_conn) -> None:
    """Idempotent upgrades for databases created before new columns existed."""
    rows = sync_conn.execute(text("PRAGMA table_info(organisations)")).fetchall()
    if not rows:
        return
    columns = {row[1] for row in rows}
    if "agent_kind" not in columns:
        sync_conn.execute(text(
            "ALTER TABLE organisations ADD COLUMN agent_kind VARCHAR(20) NOT NULL DEFAULT 'retail'"
        ))
    sync_conn.execute(text(
        "UPDATE organisations SET agent_kind = 'studio' WHERE slug = 'lotus-wellness'"
    ))


async def begin_immediate(session: AsyncSession) -> None:
    """
    Start a SQLite write transaction on this session's connection before any read
    that must stay valid through the following insert. Same connection is used for
    the check and the write. SQLITE_BUSY is left for the caller to turn into HTTP 409.
    """
    if not _sqlite:
        return
    # Touch the connection so the begin listener issues BEGIN IMMEDIATE before
    # the claim, the price check, and the write that follow on this session.
    await session.connection()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

