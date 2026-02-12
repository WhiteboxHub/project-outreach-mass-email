import asyncio
import logging
import random
from functools import wraps
from typing import Callable, Type, Tuple, Optional

logger = logging.getLogger("outreach_service")

class RetryManager:
    """
    Manages retry logic with exponential backoff and jitter.
    """
    
    @staticmethod
    def is_transient_error(exception: Exception) -> bool:
        """
        Determines if an error is transient and worth retrying.
        """
        # Add specific exception types here as we encounter them.
        # For now, we assume network-related errors or 5xx codes (if we had response objects) are transient.
        # We can refine this based on the specific libraries used (e.g., httpx.NetworkError).
        
        error_msg = str(exception).lower()
        transient_keywords = [
            "timeout", 
            "connection", 
            "rate limit", 
            "429", 
            "500", "502", "503", "504"
        ]
        
        return any(keyword in error_msg for keyword in transient_keywords)

    @staticmethod
    def with_retry(
        max_attempts: int = 3, 
        base_delay: float = 1.0, 
        max_delay: float = 10.0,
        retry_on: Tuple[Type[Exception], ...] = (Exception,)
    ):
        """
        Decorator to retry an async function upon failure.
        """
        def decorator(func: Callable):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                attempt = 0
                while True:
                    try:
                        return await func(*args, **kwargs)
                    except retry_on as e:
                        attempt += 1
                        if attempt >= max_attempts:
                            logger.warning(f"Max retry attempts ({max_attempts}) reached for {func.__name__}. Last error: {e}")
                            raise e
                        
                        if not RetryManager.is_transient_error(e):
                            logger.warning(f"Non-transient error encountered in {func.__name__}: {e}. Not retrying.")
                            raise e

                        # Calculate delay: base * 2^(attempt-1) + jitter
                        delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                        jitter = random.uniform(0, 0.1 * delay)
                        final_delay = delay + jitter
                        
                        logger.info(f"Transient error in {func.__name__}: {e}. Retrying execution in {final_delay:.2f}s (Attempt {attempt}/{max_attempts})")
                        await asyncio.sleep(final_delay)
            return wrapper
        return decorator
