import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import async_engine, Base
from app.api import auth, orgs, chat, orders, bookings, admin

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure tables are initialized on startup
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(
    title=settings.APP_NAME,
    description="Multi-Tenant Agent Platform hosting Himali Tea House and Lotus Wellness Studio",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "env": settings.APP_ENV,
        "llm_provider": settings.LLM_PROVIDER,
        "studio_timezone": settings.STUDIO_TIMEZONE
    }
