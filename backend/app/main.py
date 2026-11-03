import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import async_engine, Base, upgrade_sqlite_schema
from app.api import auth, orgs, chat, orders, bookings, admin, actions

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure tables are initialized on startup
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(upgrade_sqlite_schema)
    yield

app = FastAPI(
    title=settings.APP_NAME,
    description="Multi-Tenant Agent Platform hosting Himali Tea House and Lotus Wellness Studio",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Setup
# Bearer tokens travel in the Authorization header, so cookies (and credentialed CORS) are not needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Routers
app.include_router(auth.router, prefix="/api")
app.include_router(orgs.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(orders.router, prefix="/api")
app.include_router(bookings.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(actions.router, prefix="/api")

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "env": settings.APP_ENV,
        "llm_provider": settings.LLM_PROVIDER,
        "studio_timezone": "Asia/Kathmandu"
    }

