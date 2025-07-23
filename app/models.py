"""
Pydantic models for Gnosis OCR-S API responses
"""
from typing import Optional, Dict, Any
from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    gpu_available: bool
    gpu_name: Optional[str] = None
    model_loaded: bool
    storage_available: bool
    active_sessions: int
    cache_info: Dict[str, Any]


class ErrorResponse(BaseModel):
    """Error response"""
    error: str
    message: str
    detail: Optional[str] = None
