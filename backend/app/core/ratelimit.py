import time
from collections import defaultdict
from fastapi import HTTPException, status
from app.core.config import settings

class RateLimiter:
    def __init__(self, limit: int = 20, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        # user_id -> list of timestamps
        self.history = defaultdict(list)

    def check(self, user_id: str):
        now = time.time()
        cutoff = now - self.window_seconds
        # Prune old timestamps
        timestamps = [ts for ts in self.history[user_id] if ts > cutoff]
        
        if len(timestamps) >= self.limit:
            retry_after = int(self.window_seconds - (now - timestamps[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: maximum {self.limit} requests per minute. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(retry_after)}
            )
        
        timestamps.append(now)
        self.history[user_id] = timestamps

chat_rate_limiter = RateLimiter(limit=settings.RATE_LIMIT_PER_MINUTE, window_seconds=60)

