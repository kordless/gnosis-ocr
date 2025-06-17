"""Main FastAPI application for Gnosis OCR Service"""
import os
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import structlog

from app import __version__
from app.config import settings, validate_file_extension, format_file_size
from app.models import (
    UploadResponse, SessionStatus, OCRResult, ErrorResponse, 
    HealthResponse, ProcessingStatus, PageResult
)
from app.storage_service import storage_service
from app.ocr_service import ocr_service

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    # Startup
    logger.info("Starting Gnosis OCR Service", version=__version__)
    
    try:
        # Initialize services
        logger.info("Starting storage service...")
        await storage_service.start()
        logger.info("Storage service started")
        
        # Don't initialize OCR service during startup - do it lazily
        logger.info("OCR service will be initialized on first use")
        
        logger.info("Application startup complete")
    except Exception as e:
        logger.error("Failed to start services", error=str(e), exc_info=True)
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down Gnosis OCR Service")
    await storage_service.stop()
    await ocr_service.cleanup()


# Create FastAPI app
app = FastAPI(
    title="Gnosis OCR Service",
    description="GPU-accelerated OCR service using Nanonets-OCR-s model",
    version=__version__,
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def root():
    """Redirect to the web interface"""
    return FileResponse("static/index.html")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    gpu_info = ocr_service.get_gpu_info()
    
    return HealthResponse(
        status="healthy",
        version=__version__,
        gpu_available=gpu_info.get('available', False),
        gpu_name=gpu_info.get('device_name'),
        model_loaded=ocr_service.is_ready(),
        storage_available=os.path.exists(settings.storage_path),
        active_sessions=len(storage_service.get_active_sessions())
    )


@app.post("/upload", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    """Upload a PDF document for OCR processing"""
    # Validate file
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
        
    if not validate_file_extension(file.filename):
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file type. Allowed types: {settings.allowed_extensions}"
        )
        
    # Read file content
    content = await file.read()
    file_size = len(content)
    
    if file_size > settings.max_file_size:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size: {format_file_size(settings.max_file_size)}"
        )
        
    if file_size == 0:
        raise HTTPException(status_code=400, detail="Empty file")
        
    # Create session
    session_hash = storage_service.create_session()
    
    try:
        # Save uploaded file
        file_info = await storage_service.save_uploaded_file(
            session_hash, file.filename, content
        )
        
        # Start background processing
        background_tasks.add_task(
            process_document_task,
            session_hash,
            file_info['file_path']
        )
        
        # Return response
        return UploadResponse(
            session_hash=session_hash,
            filename=file.filename,
            file_size=file_size,
            total_pages=0,  # Will be updated during processing
            status_url=f"/status/{session_hash}",
            results_url=f"/results/{session_hash}",
            created_at=datetime.utcnow()
        )
        
    except Exception as e:
        logger.error("Upload failed", session_hash=session_hash, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def process_document_task(session_hash: str, file_path: str):
    """Background task for document processing"""
    try:
        await ocr_service.process_document(session_hash, file_path)
    except Exception as e:
        logger.error("Processing failed", session_hash=session_hash, error=str(e))


@app.get("/status/{session_hash}", response_model=SessionStatus)
async def get_status(session_hash: str):
    """Get processing status for a session"""
    status = storage_service.get_session_status(session_hash)
    
    if not status:
        raise HTTPException(status_code=404, detail="Session not found")
        
    return SessionStatus(
        session_hash=session_hash,
        status=ProcessingStatus(status.get('status', ProcessingStatus.PENDING.value)),
        progress=status.get('progress', 0.0),
        current_page=status.get('current_page'),
        total_pages=status.get('total_pages', 0),
        message=status.get('message'),
        started_at=datetime.fromisoformat(status.get('started_at', datetime.utcnow().isoformat())),
        completed_at=datetime.fromisoformat(status['completed_at']) if status.get('completed_at') else None,
        processing_time=status.get('processing_time')
    )


@app.get("/results/{session_hash}", response_model=OCRResult)
async def get_results(session_hash: str):
    """Get OCR results for a completed session"""
    # Check session status
    status = storage_service.get_session_status(session_hash)
    
    if not status:
        raise HTTPException(status_code=404, detail="Session not found")
        
    if status.get('status') != ProcessingStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400, 
            detail=f"Processing not completed. Current status: {status.get('status')}"
        )
        
    # Get results
    results = await storage_service.get_results(session_hash)
    
    # Build page results
    page_results = []
    for page_data in results['pages']:
        page_results.append(PageResult(
            page_number=page_data['page_number'],
            text=page_data['text'],
            image_url=f"/images/{session_hash}/{page_data['page_number']}",
            processing_time=0.0  # Not tracked per page currently
        ))
        
    return OCRResult(
        session_hash=session_hash,
        filename=status.get('filename', 'document.pdf'),
        total_pages=status.get('total_pages', 0),
        pages=page_results,
        combined_markdown_url=f"/results/{session_hash}/combined.md",
        download_url=f"/download/{session_hash}",
        metadata=results.get('metadata', {}),
        processing_time=status.get('processing_time', 0.0),
        created_at=datetime.fromisoformat(status.get('created_at', datetime.utcnow().isoformat()))
    )


@app.get("/images/{session_hash}/{page_number}")
async def get_page_image(session_hash: str, page_number: int):
    """Get extracted page image"""
    if not storage_service.validate_session(session_hash):
        raise HTTPException(status_code=404, detail="Session not found")
        
    image_data = await storage_service.get_page_image(session_hash, page_number)
    
    if not image_data:
        raise HTTPException(status_code=404, detail="Page image not found")
        
    return StreamingResponse(
        io.BytesIO(image_data),
        media_type="image/png",
        headers={
            "Content-Disposition": f"inline; filename=page_{page_number:03d}.png"
        }
    )


@app.get("/results/{session_hash}/combined.md")
async def get_combined_markdown(session_hash: str):
    """Get combined markdown output"""
    if not storage_service.validate_session(session_hash):
        raise HTTPException(status_code=404, detail="Session not found")
        
    file_path = storage_service.get_session_file_path(
        session_hash, 'combined_output.md', 'output'
    )
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Combined output not found")
        
    return FileResponse(
        file_path,
        media_type="text/markdown",
        headers={
            "Content-Disposition": f"inline; filename={session_hash}_combined.md"
        }
    )


@app.get("/download/{session_hash}")
async def download_results(session_hash: str):
    """Download all results as ZIP archive"""
    if not storage_service.validate_session(session_hash):
        raise HTTPException(status_code=404, detail="Session not found")
        
    # Check if processing is completed
    status = storage_service.get_session_status(session_hash)
    if status.get('status') != ProcessingStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail="Processing not completed"
        )
        
    # Create archive
    archive_path = storage_service.create_download_archive(session_hash)
    
    if not archive_path or not os.path.exists(archive_path):
        raise HTTPException(status_code=500, detail="Failed to create archive")
        
    return FileResponse(
        archive_path,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename={session_hash}_results.zip"
        }
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler"""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.__class__.__name__,
            message=exc.detail,
            detail=str(exc)
        ).dict()
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """General exception handler"""
    logger.error("Unhandled exception", error=str(exc), exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=exc.__class__.__name__,
            message="Internal server error",
            detail=str(exc)
        ).dict()
    )


# Import io for StreamingResponse
import io