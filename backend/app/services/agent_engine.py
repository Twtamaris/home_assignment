"""Chat entry point. The keyword router is gone; AgentLoop calls the configured LLM."""
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Conversation, User
from app.services.agent_loop import AgentLoop


class AgentEngine:
    @classmethod
    async def run_agent_turn(
        cls,
        db: AsyncSession,
        user: User,
        conversation: Conversation,
        user_message: str,
    ) -> AsyncGenerator[str, None]:
        async for event in AgentLoop.run_turn(db, user, conversation, user_message):
            yield event
