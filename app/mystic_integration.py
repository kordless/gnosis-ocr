"""
Mystic Integration for Gnosis OCR
This module provides decorators and utilities to integrate Mystic with the OCR service.
"""
import os
import time
import json
import functools
import logging
from typing import Any, Callable, Dict, Optional
import httpx
from datetime import datetime

logger = logging.getLogger(__name__)

# Mystic configuration from environment
MYSTIC_ENABLED = os.getenv("MYSTIC_ENABLED", "false").lower() == "true"
MYSTIC_HOST = os.getenv("MYSTIC_HOST", "mystic")
MYSTIC_PORT = int(os.getenv("MYSTIC_PORT", "8899"))
MYSTIC_URL = f"http://{MYSTIC_HOST}:{MYSTIC_PORT}"


class MysticClient:
    """Client for communicating with the Mystic sidecar."""
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=5.0)
        self.enabled = MYSTIC_ENABLED
        
    async def report_call(self, function_name: str, duration: float, error: Optional[Exception] = None):
        """Report a function call to Mystic."""
        if not self.enabled:
            return
            
        try:
            data = {
                "function": function_name,
                "duration": duration,
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(error) if error else None
            }
            
            await self.client.post(
                f"{MYSTIC_URL}/api/metrics/report",
                json=data
            )
        except Exception as e:
            logger.debug(f"Failed to report to Mystic: {e}")
    
    async def check_hijack(self, function_name: str) -> Optional[Dict[str, Any]]:
        """Check if a function is hijacked and get its configuration."""
        if not self.enabled:
            return None
            
        try:
            response = await self.client.get(
                f"{MYSTIC_URL}/api/hijacked/{function_name}"
            )
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.debug(f"Failed to check hijack status: {e}")
        
        return None
    
    async def get_cache(self, function_name: str, cache_key: str) -> Optional[Any]:
        """Get cached value from Mystic."""
        if not self.enabled:
            return None
            
        try:
            response = await self.client.get(
                f"{MYSTIC_URL}/api/cache/{function_name}/{cache_key}"
            )
            if response.status_code == 200:
                return response.json().get("value")
        except Exception as e:
            logger.debug(f"Failed to get cache: {e}")
        
        return None
    
    async def set_cache(self, function_name: str, cache_key: str, value: Any):
        """Set cached value in Mystic."""
        if not self.enabled:
            return
            
        try:
            await self.client.post(
                f"{MYSTIC_URL}/api/cache/{function_name}/{cache_key}",
                json={"value": value}
            )
        except Exception as e:
            logger.debug(f"Failed to set cache: {e}")


# Global Mystic client
mystic_client = MysticClient()


def mystic_aware(func: Callable) -> Callable:
    """
    Decorator that makes a function Mystic-aware.
    Handles caching, mocking, blocking, and performance tracking.
    """
    @functools.wraps(func)
    async def async_wrapper(*args, **kwargs):
        function_name = f"{func.__module__}.{func.__name__}"
        start_time = time.time()
        error = None
        
        try:
            # Check if function is hijacked
            hijack_info = await mystic_client.check_hijack(function_name)
            
            if hijack_info:
                strategy = hijack_info.get("strategy")
                
                if strategy == "block":
                    message = hijack_info.get("message", "Function blocked by Mystic")
                    raise RuntimeError(message)
                
                elif strategy == "mock":
                    mock_data = hijack_info.get("mock_data")
                    logger.info(f"Returning mock data for {function_name}")
                    return mock_data
                
                elif strategy == "cache":
                    # Generate cache key from args/kwargs
                    cache_key = f"{args}_{kwargs}"
                    cached_value = await mystic_client.get_cache(function_name, cache_key)
                    
                    if cached_value is not None:
                        logger.info(f"Cache hit for {function_name}")
                        return cached_value
                    
                    # Execute function and cache result
                    result = await func(*args, **kwargs)
                    await mystic_client.set_cache(function_name, cache_key, result)
                    return result
            
            # Normal execution
            return await func(*args, **kwargs)
            
        except Exception as e:
            error = e
            raise
            
        finally:
            duration = time.time() - start_time
            await mystic_client.report_call(function_name, duration, error)
    
    @functools.wraps(func)
    def sync_wrapper(*args, **kwargs):
        function_name = f"{func.__module__}.{func.__name__}"
        start_time = time.time()
        error = None
        
        try:
            # For sync functions, we can't easily check hijack status
            # In production, you'd implement a sync client or use threading
            return func(*args, **kwargs)
            
        except Exception as e:
            error = e
            raise
            
        finally:
            duration = time.time() - start_time
            # Log metrics locally since we can't easily report async
            logger.info(f"{function_name} took {duration:.3f}s")
    
    # Return appropriate wrapper based on function type
    import inspect
    if inspect.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper


# Export decorator for easy use
__all__ = ['mystic_aware', 'mystic_client']
