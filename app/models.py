"""Pydantic models for request/response validation"""
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator


class ProcessingStatus(str, Enum):
    """Enumeration of processing states"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class UploadResponse(BaseModel):
    """Response after successful file upload"""
    session_hash: str = Field(..., description="Unique session identifier")
    filename: str = Field(..., description="Original filename")
    file_size: int = Field(..., description="File size in bytes")
    total_pages: int = Field(..., description="Total number of pages in PDF")
    status_url: str = Field(..., description="URL to check processing status")
    results_url: str = Field(..., description="URL to retrieve results when ready")
    created_at: datetime = Field(..., description="Upload timestamp")
    
    class Config:
        json_schema_extra = {
            "example": {
                "session_hash": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "filename": "document.pdf",
                "file_size": 1048576,
                "total_pages": 10,
                "status_url": "/status/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "results_url": "/results/a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "created_at": "2024-01-15T10:30:00"
            }
        }


class SessionStatus(BaseModel):
    """Current processing status of a session"""
    session_hash: str = Field(..., description="Session identifier")
    status: ProcessingStatus = Field(..., description="Current processing status")
    progress: float = Field(0.0, ge=0.0, le=100.0, description="Processing progress percentage")
    current_page: Optional[int] = Field(None, description="Currently processing page number")
    total_pages: int = Field(..., description="Total number of pages")
    message: Optional[str] = Field(None, description="Status message or error details")
    started_at: datetime = Field(..., description="Processing start time")
    completed_at: Optional[datetime] = Field(None, description="Processing completion time")
    processing_time: Optional[float] = Field(None, description="Total processing time in seconds")
    
    @validator('progress')
    def round_progress(cls, v):
        """Round progress to 2 decimal places"""
        return round(v, 2)
    
    class Config:
        json_schema_extra = {
            "example": {
                "session_hash": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "status": "processing",
                "progress": 45.5,
                "current_page": 5,
                "total_pages": 10,
                "message": "Processing page 5 of 10",
                "started_at": "2024-01-15T10:30:00",
                "completed_at": None,
                "processing_time": None
            }
        }


class PageResult(BaseModel):
    """OCR result for a single page"""
    page_number: int = Field(..., description="Page number (1-indexed)")
    text: str = Field(..., description="Extracted text in Markdown format")
    confidence: Optional[float] = Field(None, description="OCR confidence score")
    image_url: str = Field(..., description="URL to access the page image")
    processing_time: float = Field(..., description="Page processing time in seconds")
    
    class Config:
        json_schema_extra = {
            "example": {
                "page_number": 1,
                "text": "# Title\n\nThis is the extracted text...",
                "confidence": 0.95,
                "image_url": "/images/a1b2c3d4-e5f6-7890-abcd-ef1234567890/1",
                "processing_time": 2.5
            }
        }


class OCRResult(BaseModel):
    """Complete OCR results for a document"""
    session_hash: str = Field(..., description="Session identifier")
    filename: str = Field(..., description="Original filename")
    total_pages: int = Field(..., description="Total number of pages")
    pages: List[PageResult] = Field(..., description="Results for each page")
    combined_markdown_url: str = Field(..., description="URL to download combined Markdown")
    download_url: str = Field(..., description="URL to download all results as ZIP")
    metadata: Dict[str, Any] = Field(..., description="Additional metadata")
    processing_time: float = Field(..., description="Total processing time in seconds")
    created_at: datetime = Field(..., description="Result creation timestamp")
    
    class Config:
        json_schema_extra = {
            "example": {
                "session_hash": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                "filename": "document.pdf",
                "total_pages": 2,
                "pages": [
                    {
                        "page_number": 1,
                        "text": "# Page 1 Content",
                        "confidence": 0.95,
                        "image_url": "/images/session123/1",
                        "processing_time": 2.5
                    }
                ],
                "combined_markdown_url": "/results/session123/combined.md",
                "download_url": "/download/session123",
                "metadata": {
                    "model": "nanonets/Nanonets-OCR-s",
                    "device": "cuda",
                    "gpu_name": "NVIDIA T4"
                },
                "processing_time": 15.3,
                "created_at": "2024-01-15T10:30:45"
            }
        }


class ErrorResponse(BaseModel):
    """Standard error response"""
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Additional error details")
    session_hash: Optional[str] = Field(None, description="Session hash if applicable")
    
    class Config:
        json_schema_extra = {
            "example": {
                "error": "FileNotFoundError",
                "message": "Session not found",
                "detail": "No session found with hash: abc123",
                "session_hash": "abc123"
            }
        }


class HealthResponse(BaseModel):
    """Health check response"""
    status: str = Field(..., description="Service status")
    version: str = Field(..., description="Service version")
    gpu_available: bool = Field(..., description="GPU availability")
    gpu_name: Optional[str] = Field(None, description="GPU device name")
    model_loaded: bool = Field(..., description="Model loading status")
    storage_available: bool = Field(..., description="Storage availability")
    active_sessions: int = Field(..., description="Number of active sessions")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "healthy",
                "version": "1.0.0",
                "gpu_available": True,
                "gpu_name": "NVIDIA T4",
                "model_loaded": True,
                "storage_available": True,
                "active_sessions": 3
            }
        }