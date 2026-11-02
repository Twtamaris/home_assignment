import uuid
import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.ratelimit import chat_rate_limiter
from app.models.models import User, Conversation, Message
from app.models.schemas import (
    ConversationOut, ConversationCreate, ConversationUpdate, MessageOut, MessageSend
)
from app.services.agent_engine import AgentEngine

router = APIRouter(prefix="/chat", tags=["Chat"])

@router.get("/conversations", response_model=List[ConversationOut])
async def list_conversations(
    agent_type: str = "customer",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Lists conversations strictly scoped to the authenticated user and their organisation."""
    stmt = select(Conversation).where(
        Conversation.org_id == current_user.org_id,
        Conversation.user_id == current_user.id,
        Conversation.agent_type == agent_type
    ).order_by(desc(Conversation.updated_at))
    res = await db.execute(stmt)
    return [ConversationOut.from_orm(c) for c in res.scalars().all()]

@router.post("/conversations", response_model=ConversationOut)
async def create_conversation(
    payload: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if payload.agent_type == "admin" and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Only administrators can initiate admin analytics conversations."
        )

    conv_id = f"conv_{uuid.uuid4().hex[:10]}"
    conv = Conversation(
        id=conv_id,
        org_id=current_user.org_id,
        user_id=current_user.id,
        title=payload.title or "New Chat",
        agent_type=payload.agent_type or "customer"
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return ConversationOut.from_orm(conv)

@router.patch("/conversations/{conv_id}", response_model=ConversationOut)
async def rename_conversation(
    conv_id: str,
    payload: ConversationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Conversation).where(
        Conversation.id == conv_id,
        Conversation.org_id == current_user.org_id
    )
    res = await db.execute(stmt)
    conv = res.scalars().first()
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or access denied."
        )

    conv.title = payload.title
    conv.updated_at = datetime.datetime.utcnow()
    await db.commit()
    await db.refresh(conv)
    return ConversationOut.from_orm(conv)

@router.delete("/conversations/{conv_id}")
async def delete_conversation(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Conversation).where(
        Conversation.id == conv_id,
        Conversation.org_id == current_user.org_id
    )
    res = await db.execute(stmt)
    conv = res.scalars().first()
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or access denied."
        )

    await db.delete(conv)
    await db.commit()
    return {"success": True, "message": "Conversation deleted."}

@router.get("/conversations/{conv_id}/messages")
async def get_conversation_messages(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Conversation).where(
        Conversation.id == conv_id,
        Conversation.org_id == current_user.org_id
    )
    res = await db.execute(stmt)
    conv = res.scalars().first()
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or access denied."
        )

    m_stmt = select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
    m_res = await db.execute(m_stmt)
    messages = m_res.scalars().all()

    import json
    return [
        {
            "id": m.id,
            "conversation_id": m.conversation_id,
            "sender": m.sender,
            "content": m.content,
            "tool_calls": json.loads(m.tool_calls_json) if m.tool_calls_json else None,
            "citations": json.loads(m.citations_json) if m.citations_json else None,
            "card": json.loads(m.card_json) if m.card_json else None,
            "created_at": m.created_at.isoformat()
        }
        for m in messages
    ]

@router.post("/conversations/{conv_id}/messages")
async def send_chat_message(
    conv_id: str,
    payload: MessageSend,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Rate Limiting Check (20 requests/minute per user)
    chat_rate_limiter.check(current_user.id)

    # 2. Strict Tenant and Ownership Validation
    stmt = select(Conversation).where(
        Conversation.id == conv_id,
        Conversation.org_id == current_user.org_id
    )
    res = await db.execute(stmt)
    conv = res.scalars().first()
    if not conv or conv.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or cross-tenant access prohibited."
        )

    # If admin conversation, verify admin role
    if conv.agent_type == "admin" and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Admin analytics access restricted to administrators."
        )

    # 3. Stream agent execution loop via Server-Sent Events (SSE)
    async def event_generator():
        async for event in AgentEngine.run_agent_turn(db, current_user, conv, payload.content):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

