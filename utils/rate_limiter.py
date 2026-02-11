import time
import asyncio
from typing import Optional

class TokenBucketRateLimiter:
    def __init__(self, rate_limit_per_minute: int):
        self.rate_limit = rate_limit_per_minute
        self.tokens = rate_limit_per_minute
        self.last_refill = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1):
        """
        Acquires `tokens` from the bucket. Blocks until tokens are available.
        """
        if self.rate_limit <= 0:
            return  # No limit

        while True:
            async with self.lock:
                now = time.monotonic()
                # Refill logic
                time_passed = now - self.last_refill
                if time_passed > 60: # Reset every minute
                     self.tokens = self.rate_limit
                     self.last_refill = now
                
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return
                
                # Calculate wait time
                wait_time = 60 - time_passed
            
            # Wait outside lock
            if wait_time > 0:
                await asyncio.sleep(wait_time)
