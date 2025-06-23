"""Main FastAPI application for Gnosis OCR Service with new storage architecture"""
import os
import io
import asyncio
import base64
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, Dict, List
from pathlib import Path


from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
import structlog

from app import __version__
from app.config import settings, validate_file_extension, format_file_size
from app.models import (
    UploadResponse, SessionStatus, OCRResult, ErrorResponse, 
    HealthResponse, ProcessingStatus, PageResult
)
from app.storage_service_v2 import StorageService
from app.ocr_service_v2_fixed import OCRService, ocr_service

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

# FORCE LOG AT MODULE LEVEL
print("HARIN FORCE LOG: main_v2.py module loaded")
logger.error("HARIN FORCE LOG: structlog configured")

# Global storage for active WebSocket connections
active_websockets: Dict[str, WebSocket] = {}

# Global storage for chunked upload sessions
chunked_uploads: Dict[str, Dict] = {}


def get_user_email_from_request(request: Request, 
                               x_user_email: Optional[str] = Header(None)) -> Optional[str]:
    """Extract user email from request headers or auth context"""
    # Priority order:
    # 1. X-User-Email header
    # 2. Authorization token (if implemented)
    # 3. Default to None (anonymous)
    
    if x_user_email:
        logger.debug("User email from header", user_email=x_user_email)
        return x_user_email
    
    # TODO: Add JWT token parsing or other auth methods here
    # auth_header = request.headers.get("authorization")
    # if auth_header:
    #     token = auth_header.replace("Bearer ", "")
    #     user_info = decode_jwt(token)
    #     return user_info.get("email")
    
    # Log when using anonymous
    logger.debug("No user email found, using anonymous")
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    # Startup
    logger.info("Starting Gnosis OCR Service", version=__version__)
    
    try:
        # Don't initialize storage service globally - create per request
        logger.info("Storage service will be created per-request with user context")
        
        # Don't initialize OCR service during startup - do it lazily
        logger.info("OCR service will be initialized on first use")
        
        logger.info("Application startup complete")
    except Exception as e:
        logger.error("Failed to start services", error=str(e), exc_info=True)
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down Gnosis OCR Service")
    await ocr_service.cleanup()


# Create FastAPI app
app = FastAPI(
    title="Gnosis OCR Service",
    description="GPU-accelerated OCR service using Nanonets-OCR-s model with user partitioning",
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
    
    # Create anonymous storage service for health check
    storage = StorageService()
    cache_info = await storage.get_cache_info()
    
    return HealthResponse(
        status="healthy",
        version=__version__,
        gpu_available=gpu_info.get('available', False),
        gpu_name=gpu_info.get('device_name'),
        model_loaded=ocr_service.is_ready(),
        storage_available=True,  # Always true with new architecture
        active_sessions=0,  # Would need to implement session counting
        cache_info=cache_info
    )


@app.websocket("/ws/progress/{session_id}")
async def websocket_progress(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time upload progress updates"""
    await websocket.accept()
    active_websockets[session_id] = websocket
    
    logger.info("WebSocket connected", session_id=session_id)
    
    try:
        # Keep connection alive and listen for disconnect
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    except Exception as e:
        logger.error("WebSocket error", session_id=session_id, error=str(e))
    finally:
        # Clean up on disconnect
        if session_id in active_websockets:
            del active_websockets[session_id]
        logger.info("WebSocket disconnected", session_id=session_id)


async def send_progress_update(session_id: str, progress_data: Dict):
    """Send progress update to connected WebSocket client"""
    if session_id in active_websockets:
        try:
            await active_websockets[session_id].send_json(progress_data)
        except Exception as e:
            logger.error("Failed to send progress update", session_id=session_id, error=str(e))
            # Remove dead connection
            if session_id in active_websockets:
                del active_websockets[session_id]


@app.post("/upload/start")
async def start_chunked_upload(
    request: Request,
    x_user_email: Optional[str] = Header(None)
):
    """Start a new chunked upload session"""
    try:
        upload_info = await request.json()
        filename = upload_info.get('filename')
        total_size = upload_info.get('total_size')
        total_chunks = upload_info.get('total_chunks')
        
        if not filename or not total_size or not total_chunks:
            raise HTTPException(status_code=400, detail="Missing required fields: filename, total_size, total_chunks")
        
        # Validate file
        if not validate_file_extension(filename):
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid file type. Allowed types: {settings.allowed_extensions}"
            )
        
        if total_size > settings.max_file_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: {format_file_size(settings.max_file_size)}"
            )
        
        # Get user context
        user_email = get_user_email_from_request(request, x_user_email)
        
        # Create storage service
        storage_service = StorageService(user_email=user_email)
        if os.environ.get('RUNNING_IN_CLOUD') == 'true':
            storage_service.force_cloud_mode()
        
        # Create session
        session_hash = await storage_service.create_session({
            'filename': filename,
            'file_size': total_size,
            'created_at': datetime.utcnow().isoformat(),
            'chunked_upload': True,
            'total_chunks': total_chunks
        })
        
        # Store upload session
        chunked_uploads[session_hash] = {
            'filename': filename,
            'total_size': total_size,
            'total_chunks': total_chunks,
            'received_chunks': 0,
            'chunks_data': {},
            'user_email': user_email,
            'created_at': datetime.utcnow()
        }
        
        logger.info("Chunked upload started", 
                   session_hash=session_hash,
                   filename=filename,
                   total_size=total_size,
                   total_chunks=total_chunks)
        
        return {
            'session_hash': session_hash,
            'status': 'ready',
            'total_chunks': total_chunks
        }
        
    except Exception as e:
        logger.error("Failed to start chunked upload", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/upload/chunk/{session_hash}")
async def upload_chunk(
    session_hash: str,
    request: Request,
    x_user_email: Optional[str] = Header(None)
):
    """Upload a single chunk"""
    try:
        chunk_data = await request.json()
        chunk_number = chunk_data.get('chunk_number')
        chunk_content = chunk_data.get('content')  # base64 encoded
        
        if chunk_number is None or not chunk_content:
            raise HTTPException(status_code=400, detail="Missing chunk_number or content")
        
        if session_hash not in chunked_uploads:
            raise HTTPException(status_code=404, detail="Upload session not found")
        
        upload_session = chunked_uploads[session_hash]
        
        # Decode chunk content
        try:
            chunk_bytes = base64.b64decode(chunk_content)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid base64 content: {str(e)}")
        
        # Store chunk
        upload_session['chunks_data'][chunk_number] = chunk_bytes
        upload_session['received_chunks'] += 1
        
        # Calculate progress
        progress_percent = (upload_session['received_chunks'] / upload_session['total_chunks']) * 100
        
        # Send progress update via WebSocket
        await send_progress_update(session_hash, {
            'type': 'upload_progress',
            'chunk_number': chunk_number,
            'total_chunks': upload_session['total_chunks'],
            'received_chunks': upload_session['received_chunks'],
            'progress_percent': progress_percent,
            'message': f"Uploading chunk {chunk_number} of {upload_session['total_chunks']}"
        })
        
        logger.debug("Chunk received", 
                    session_hash=session_hash,
                    chunk_number=chunk_number,
                    chunk_size=len(chunk_bytes),
                    progress=progress_percent)
        
        # Check if all chunks received
        if upload_session['received_chunks'] >= upload_session['total_chunks']:
            # Assemble complete file
            await assemble_and_process_file(session_hash, upload_session)
        
        return {
            'status': 'received',
            'chunk_number': chunk_number,
            'received_chunks': upload_session['received_chunks'],
            'total_chunks': upload_session['total_chunks'],
            'progress_percent': progress_percent
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to upload chunk", session_hash=session_hash, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def assemble_and_process_file(session_hash: str, upload_session: Dict):
    """Assemble chunks into complete file and start processing"""
    try:
        logger.info("Assembling file", session_hash=session_hash)
        
        # Send progress update
        await send_progress_update(session_hash, {
            'type': 'upload_complete',
            'message': 'Upload complete, assembling file...'
        })
        
        # Assemble chunks in order
        complete_file = b''
        for chunk_num in sorted(upload_session['chunks_data'].keys()):
            complete_file += upload_session['chunks_data'][chunk_num]
        
        # Create storage service
        storage_service = StorageService(user_email=upload_session['user_email'])
        if os.environ.get('RUNNING_IN_CLOUD') == 'true':
            storage_service.force_cloud_mode()
        
        # Save assembled file
        await storage_service.save_file(
            complete_file, 
            'upload.pdf',
            session_hash
        )
        
        # Create initial status file
        initial_status = {
            'status': ProcessingStatus.PENDING.value,
            'progress': 0.0,
            'message': 'File uploaded, processing queued',
            'updated_at': datetime.utcnow().isoformat()
        }
        await storage_service.save_file(
            json.dumps(initial_status, indent=2),
            'status.json',
            session_hash
        )
        
        # Send processing start update
        await send_progress_update(session_hash, {
            'type': 'processing_started',
            'message': 'File assembled, starting OCR processing...'
        })
        
        # Start background processing
        asyncio.create_task(process_document_task(
            session_hash,
            complete_file,
            upload_session['user_email']
        ))
        
        # Clean up chunks from memory
        del chunked_uploads[session_hash]
        
        logger.info("File assembled and processing started", 
                   session_hash=session_hash,
                   file_size=len(complete_file))
        
    except Exception as e:
        logger.error("Failed to assemble file", session_hash=session_hash, error=str(e))
        await send_progress_update(session_hash, {
            'type': 'error',
            'message': f'Failed to assemble file: {str(e)}'
        })


@app.post("/upload", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    x_user_email: Optional[str] = Header(None)
):
    """Upload a PDF document for OCR processing"""
    # Get user context
    user_email = get_user_email_from_request(request, x_user_email)
    
    # Create storage service with detailed error handling
    try:
        storage_service = StorageService(user_email=user_email)
        logger.info("StorageService created", 
                   user_email=user_email,
                   user_hash=storage_service._user_hash,
                   is_cloud=storage_service._is_cloud)
        
        # Force GCS in cloud environment for session persistence
        if os.environ.get('RUNNING_IN_CLOUD') == 'true':
            logger.info("Forcing GCS mode for cloud environment")
            storage_service.force_cloud_mode()
            logger.info("GCS initialization completed")
            
    except Exception as e:
        logger.error("StorageService creation failed", 
                    error=str(e), 
                    error_type=type(e).__name__,
                    exc_info=True)
        raise HTTPException(status_code=500, detail=f"Storage initialization failed: {str(e)}")
    
    # Enhanced logging for debugging

    
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
        
    try:
        # Create session with metadata
        session_hash = await storage_service.create_session({
            'filename': file.filename,
            'file_size': file_size,
            'created_at': datetime.utcnow().isoformat()
        })
        
        # Save uploaded file
        await storage_service.save_file(
            content, 
            'upload.pdf',
            session_hash
        )
        
        # Create initial status file
        initial_status = {
            'status': ProcessingStatus.PENDING.value,
            'progress': 0.0,
            'message': 'Document uploaded, processing queued',
            'updated_at': datetime.utcnow().isoformat()
        }
        await storage_service.save_file(
            json.dumps(initial_status, indent=2),
            'status.json',
            session_hash
        )
        
        # Start background processing
        logger.error("UPLOAD ADDING BACKGROUND TASK", session_hash=session_hash, file_size=len(content))
        
        # Create task immediately with asyncio
        task = asyncio.create_task(process_document_task(session_hash, content, user_email))
        logger.error("UPLOAD TASK CREATED WITH ASYNCIO", session_hash=session_hash, task_id=id(task))
        
        # Also add to background_tasks for proper cleanup
        background_tasks.add_task(lambda: None)  # Dummy task to keep FastAPI happy
        
        logger.error("UPLOAD BACKGROUND TASK ADDED", session_hash=session_hash)

        
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
        logger.error("Upload failed", user_email=user_email, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def process_document_task(session_hash: str, file_content: bytes, user_email: Optional[str]):
    """Background task for document processing"""
    logger.error("PROCESSING TASK START", session_hash=session_hash, file_size=len(file_content))
    
    try:
        # Create storage service with user context
        storage_service = StorageService(user_email=user_email)
        logger.error("PROCESSING STORAGE CREATED", session_hash=session_hash)
        
        # Force GCS mode
        if os.environ.get('RUNNING_IN_CLOUD') == 'true':
            storage_service.force_cloud_mode()
            logger.error("PROCESSING GCS MODE FORCED", session_hash=session_hash)
        
        # Process document
        logger.error("PROCESSING DOCUMENT START", session_hash=session_hash)
        
        # Define progress callback
        async def progress_callback(current_page: int, total_pages: int):
            progress = (current_page / total_pages) * 100 if total_pages > 0 else 0
            status_update = {
                'status': ProcessingStatus.PROCESSING.value,
                'progress': progress,
                'current_page': current_page,
                'total_pages': total_pages,
                'message': f'Processing page {current_page} of {total_pages}',
                'updated_at': datetime.utcnow().isoformat()
            }
            await storage_service.save_file(
                json.dumps(status_update, indent=2),
                'status.json',
                session_hash
            )
            logger.info(f"Processing progress: page {current_page}/{total_pages}", 
                       session_hash=session_hash)
        
        # First extract images from PDF
        import pdf2image
        logger.info("Converting PDF to images for storage", session_hash=session_hash)
        try:
            images = pdf2image.convert_from_bytes(
                file_content,
                dpi=300,
                fmt='PNG',
                thread_count=4
            )
            logger.info(f"Extracted {len(images)} images from PDF", session_hash=session_hash)
            
            # Save images
            for i, image in enumerate(images):
                page_num = i + 1
                image_bytes = io.BytesIO()
                image.save(image_bytes, format='PNG')
                image_bytes.seek(0)
                
                await storage_service.save_page_image(
                    image_bytes.getvalue(),
                    page_num,
                    session_hash
                )
                logger.debug(f"Saved image for page {page_num}", session_hash=session_hash)
                
        except Exception as e:
            logger.error(f"Failed to extract/save images: {str(e)}", 
                        session_hash=session_hash, 
                        exc_info=True)
            # Continue even if image extraction fails
        
        # Call the actual OCR service method (synchronous)
        logger.info("Starting OCR processing", session_hash=session_hash)
        page_results = ocr_service.process_pdf(file_content, progress_callback=None)
        
        logger.info(f"OCR completed, got {len(page_results)} pages", session_hash=session_hash)
        
        # Save individual page results and images
        for i, page_result in enumerate(page_results):
            page_num = page_result.get('page_number', i + 1)
            
            # Save markdown result
            markdown_content = page_result.get('text', '')
            await storage_service.save_page_result(markdown_content, page_num, session_hash)
            
            # Update progress
            await progress_callback(page_num, len(page_results))
        
        # Create combined output
        combined_markdown = "\n\n---\n\n".join([
            f"# Page {r.get('page_number', i+1)}\n\n{r.get('text', '')}"
            for i, r in enumerate(page_results)
        ])
        
        await storage_service.save_file(
            combined_markdown.encode('utf-8'),
            'combined_output.md',
            session_hash
        )
        
        # Update final status
        final_status = {
            'status': ProcessingStatus.COMPLETED.value,
            'progress': 100.0,
            'total_pages': len(page_results),
            'message': 'Processing completed successfully',
            'updated_at': datetime.utcnow().isoformat()
        }
        await storage_service.save_file(
            json.dumps(final_status, indent=2),
            'status.json',
            session_hash
        )
        
        logger.error("PROCESSING DOCUMENT SUCCESS", session_hash=session_hash, pages=len(page_results))
        
    except Exception as e:
        logger.error("PROCESSING FAILED", session_hash=session_hash, error=str(e), error_type=type(e).__name__)
        import traceback
        logger.error("PROCESSING TRACEBACK", session_hash=session_hash, traceback=traceback.format_exc())
        
        # Update status with error
        try:
            error_status = {
                'status': ProcessingStatus.FAILED.value,
                'progress': 0.0,
                'message': f'Processing failed: {str(e)}',
                'error': str(e),
                'updated_at': datetime.utcnow().isoformat()
            }
            await storage_service.save_file(
                json.dumps(error_status, indent=2),
                'status.json',
                session_hash
            )
        except Exception as status_error:
            logger.error("Failed to update error status", error=str(status_error))


@app.get("/status/{session_hash}", response_model=SessionStatus)
async def get_status(
    session_hash: str,
    request: Request,
    x_user_email: Optional[str] = Header(None)
):
    """Get processing status for a session"""
    # Get user context
    user_email = get_user_email_from_request(request, x_user_email)
    
    # Create storage service with detailed error handling
    try:
        storage_service = StorageService(user_email=user_email)
        logger.info("StorageService created", 
                   user_email=user_email,
                   user_hash=storage_service._user_hash,
                   is_cloud=storage_service._is_cloud)
        
        # Force GCS in cloud environment for session persistence
        if os.environ.get('RUNNING_IN_CLOUD') == 'true':
            logger.info("Forcing GCS mode for cloud environment")
            storage_service.force_cloud_mode()
            logger.info("GCS initialization completed")
            
    except Exception as e:
        logger.error("StorageService creation failed", 
                    error=str(e), 
                    error_type=type(e).__name__,
                    exc_info=True)
        raise HTTPException(status_code=500, detail=f"Storage initialization failed: {str(e)}")
    
    # Enhanced logging for debugging

    
    # Enhanced logging for debugging
    logger.info("Status request", 
                session_hash=session_hash,
                user_email=user_email,
                user_hash=storage_service._user_hash,
                is_cloud=storage_service._is_cloud,
                remote_addr=request.client.host if request.client else 'unknown')
    
    # SKIP SESSION VALIDATION - NO AUTH VERSION
    logger.error("STATUS ENDPOINT - NO AUTH VERSION", session_hash=session_hash)
    
    # Override user hash to match the session
    # Just assume the session exists and try to read files directly
    
    try:
        # Get status file
        logger.debug("Attempting to get status file", session_hash=session_hash)
        status_content = await storage_service.get_file('status.json', session_hash)
        status = json.loads(status_content)
        logger.debug("Status file loaded", session_hash=session_hash, status=status)
        
        # Get metadata
        logger.debug("Attempting to get metadata file", session_hash=session_hash)
        metadata_content = await storage_service.get_file('metadata.json', session_hash)
        metadata = json.loads(metadata_content)
        logger.debug("Metadata file loaded", session_hash=session_hash, metadata=metadata)
        
        result = SessionStatus(
            session_hash=session_hash,
            status=ProcessingStatus(status.get('status', ProcessingStatus.PENDING.value)),
            progress=status.get('progress', 0.0),
            current_page=status.get('current_page'),
            total_pages=metadata.get('total_pages', 0),
            message=status.get('message'),
            started_at=datetime.fromisoformat(metadata.get('created_at', datetime.utcnow().isoformat())),
            completed_at=datetime.fromisoformat(status['updated_at']) if status.get('status') == 'completed' else None,
            processing_time=None  # Could calculate from timestamps
        )
        
        logger.info("Status response created", 
                   session_hash=session_hash,
                   status=result.status.value,
                   progress=result.progress)
        
        return result
        
    except FileNotFoundError as e:
        logger.error("Status file not found", 
                    session_hash=session_hash,
                    error=str(e),
                    user_hash=storage_service._user_hash,
                    session_path=str(storage_service.get_session_path(session_hash)))
        raise HTTPException(status_code=404, detail="Session not found")
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in status/metadata", 
                    session_hash=session_hash,
                    error=str(e))
        raise HTTPException(status_code=500, detail="Invalid session data")
    except Exception as e:
        logger.error("Error getting status", 
                    session_hash=session_hash, 
                    error=str(e),
                    error_type=type(e).__name__,
                    exc_info=True)
        raise HTTPException(status_code=500, detail="Error retrieving status")



@app.get("/results/{session_hash}", response_model=OCRResult)
async def get_results(
    session_hash: str,
    request: Request,
    x_user_email: Optional[str] = Header(None)
):
    """Get OCR results for a completed session"""
    # Get user context
    user_email = get_user_email_from_request(request, x_user_email)
    
    # Create storage service with detailed error handling
    try:
        storage_service = StorageService(user_email=user_email)
        logger.info("StorageService created", 
                   user_email=user_email,
                   user_hash=storage_service._user_hash,
                   is_cloud=storage_service._is_cloud)
        
        # Force GCS in cloud environment for session persistence
        if os.environ.get('RUNNING_IN_CLOUD') == 'true':
            logger.info("Forcing GCS mode for cloud environment")
            storage_service.force_cloud_mode()
            logger.info("GCS initialization completed")
            
    except Exception as e:
        logger.error("StorageService creation failed", 
                    error=str(e), 
                    error_type=type(e).__name__,
                    exc_info=True)
        raise HTTPException(status_code=500, detail=f"Storage initialization failed: {str(e)}")
    
    # Enhanced logging for debugging

    
    # SKIP SESSION VALIDATION - NO AUTH VERSION  
    logger.error("RESULTS ENDPOINT - NO AUTH VERSION", session_hash=session_hash)
    
    try:
        # Check session status
        status_content = await storage_service.get_file('status.json', session_hash)
        status = json.loads(status_content)
        
        if status.get('status') != ProcessingStatus.COMPLETED.value:
            raise HTTPException(
                status_code=400, 
                detail=f"Processing not completed. Current status: {status.get('status')}"
            )
        
        # Get metadata
        metadata_content = await storage_service.get_file('metadata.json', session_hash)
        metadata = json.loads(metadata_content)
        
        # Build page results
        page_results = []
        total_pages = metadata.get('total_pages', 0)
        
        for page_num in range(1, total_pages + 1):
            try:
                # Get page text
                page_text = await storage_service.get_file(
                    f'page_{page_num:03d}_result.txt',
                    session_hash
                )
                page_results.append(PageResult(
                    page_number=page_num,
                    text=page_text.decode('utf-8'),
                    image_url=storage_service.get_file_url(f'page_{page_num:03d}.png', session_hash),
                    processing_time=0.0  # Not tracked per page currently
                ))
            except FileNotFoundError:
                logger.warning("Page result not found", session_hash=session_hash, page=page_num)
        
        return OCRResult(
            session_hash=session_hash,
            filename=metadata.get('filename', 'document.pdf'),
            total_pages=total_pages,
            pages=page_results,
            combined_markdown_url=storage_service.get_file_url('combined_output.md', session_hash),
            download_url=f"/download/{session_hash}",
            metadata=metadata,
            processing_time=0.0,  # Could calculate from timestamps
            created_at=datetime.fromisoformat(metadata.get('created_at', datetime.utcnow().isoformat()))
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting results", session_hash=session_hash, error=str(e))
        raise HTTPException(status_code=500, detail="Error retrieving results")


@app.get("/storage/{user_hash}/{session_hash}/{filename:path}")
async def serve_user_file(
    user_hash: str,
    session_hash: str,
    filename: str,
    request: Request,
    x_user_email: Optional[str] = Header(None)
):
    """Serve files from user storage - NO AUTH"""
    logger.error("FILE SERVE - NO AUTH VERSION")
    
    # Create anonymous storage service
    storage_service = StorageService(user_email=None)
    
    # Force GCS in cloud environment
    if os.environ.get('RUNNING_IN_CLOUD') == 'true':
        storage_service.force_cloud_mode()
    
    # Override user hash to match URL
    storage_service._user_hash = user_hash
    logger.error("FILE SERVE USING URL HASH", user_hash=user_hash, session_hash=session_hash, filename=filename)
    
    try:
        # Get file content
        content = await storage_service.get_file(filename, session_hash)
        
        # Determine content type
        content_type = "application/octet-stream"
        if filename.endswith('.png'):
            content_type = "image/png"
        elif filename.endswith('.jpg') or filename.endswith('.jpeg'):
            content_type = "image/jpeg"
        elif filename.endswith('.txt'):
            content_type = "text/plain"
        elif filename.endswith('.md'):
            content_type = "text/markdown"
        elif filename.endswith('.json'):
            content_type = "application/json"
        elif filename.endswith('.pdf'):
            content_type = "application/pdf"
        
        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Content-Disposition": f"inline; filename={filename}"
            }
        )
        
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except Exception as e:
        logger.error("Error serving file", filename=filename, error=str(e))
        raise HTTPException(status_code=500, detail="Error retrieving file")


@app.get("/download/{session_hash}")
async def download_results(
    session_hash: str,
    request: Request,
    x_user_email: Optional[str] = Header(None)
):
    """Download all results as ZIP archive"""
    # Get user context
    user_email = get_user_email_from_request(request, x_user_email)
    
    # Create storage service with detailed error handling
    try:
        storage_service = StorageService(user_email=user_email)
        logger.info("StorageService created", 
                   user_email=user_email,
                   user_hash=storage_service._user_hash,
                   is_cloud=storage_service._is_cloud)
        
        # Force GCS in cloud environment for session persistence
        if os.environ.get('RUNNING_IN_CLOUD') == 'true':
            logger.info("Forcing GCS mode for cloud environment")
            storage_service.force_cloud_mode()
            logger.info("GCS initialization completed")
            
    except Exception as e:
        logger.error("StorageService creation failed", 
                    error=str(e), 
                    error_type=type(e).__name__,
                    exc_info=True)
        raise HTTPException(status_code=500, detail=f"Storage initialization failed: {str(e)}")
    
    # Enhanced logging for debugging

    
    # SKIP SESSION VALIDATION - NO AUTH VERSION
    logger.error("DOWNLOAD ENDPOINT - NO AUTH VERSION", session_hash=session_hash)
    
    # Check if processing is completed
    try:
        status_content = await storage_service.get_file('status.json', session_hash)
        status = json.loads(status_content)
        
        if status.get('status') != ProcessingStatus.COMPLETED.value:
            raise HTTPException(
                status_code=400,
                detail="Processing not completed"
            )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # TODO: Implement ZIP archive creation
    # For now, return not implemented
    raise HTTPException(status_code=501, detail="Archive download not yet implemented")


@app.get("/cache/info")
async def get_cache_info(
    x_user_email: Optional[str] = Header(None)
):
    """Get information about model cache (admin endpoint)"""
    # This could be restricted to admin users
    storage_service = StorageService(user_email=x_user_email)
    cache_info = await storage_service.get_cache_info()
    
    return {
        "cache_info": cache_info,
        "model_loaded": ocr_service.is_ready(),
        "gpu_info": ocr_service.get_gpu_info()
    }


@app.post("/api/log")
async def frontend_log(
    request: Request,
    x_user_email: Optional[str] = Header(None)
):
    """Frontend logging endpoint - receives logs from JavaScript"""
    try:
        log_data = await request.json()
        
        # Extract log details
        level = log_data.get('level', 'info').upper()
        message = log_data.get('message', '')
        context = log_data.get('context', {})
        timestamp = log_data.get('timestamp', datetime.utcnow().isoformat())
        session_id = log_data.get('session_id')
        user_agent = request.headers.get('user-agent', 'unknown')
        
        # Log with structured format
        log_entry = {
            'frontend_log': True,
            'level': level,
            'message': message,
            'context': context,
            'session_id': session_id,
            'user_email': x_user_email,
            'user_agent': user_agent,
            'timestamp': timestamp,
            'remote_addr': request.client.host if request.client else 'unknown'
        }
        
        # Route to appropriate log level
        if level == 'ERROR':
            logger.error("Frontend Error", **log_entry)
        elif level == 'WARN':
            logger.warning("Frontend Warning", **log_entry)
        elif level == 'DEBUG':
            logger.debug("Frontend Debug", **log_entry)
        else:
            logger.info("Frontend Info", **log_entry)
            
        return {"status": "logged", "timestamp": datetime.utcnow().isoformat()}
        
    except Exception as e:
        logger.error("Failed to process frontend log", error=str(e))
        return {"status": "error", "message": str(e)}


@app.get("/api/test/model-loading")
async def test_model_loading():
    """Test what happens when we try to load the model"""
    import os
    from transformers import AutoTokenizer, AutoProcessor
    
    result = {
        "env_vars": {
            "HF_HOME": os.environ.get("HF_HOME"),
            "TRANSFORMERS_CACHE": os.environ.get("TRANSFORMERS_CACHE"),
            "HF_DATASETS_OFFLINE": os.environ.get("HF_DATASETS_OFFLINE"),
            "TRANSFORMERS_OFFLINE": os.environ.get("TRANSFORMERS_OFFLINE"),
            "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE"),
        },
        "tests": {}
    }
    
    model_name = "nanonets/Nanonets-OCR-s"
    cache_dir = os.environ.get("HF_HOME", "/cache/huggingface")
    
    # Test 1: Check if the model directory exists
    model_dir = os.path.join(cache_dir, "hub", f"models--{model_name.replace('/', '--')}")
    result["tests"]["model_dir_exists"] = os.path.exists(model_dir)
    
    # Test 2: Check refs/main
    refs_main = os.path.join(model_dir, "refs", "main")
    if os.path.exists(refs_main):
        with open(refs_main) as f:
            commit_hash = f.read().strip()
            result["tests"]["refs_main_commit"] = commit_hash
            
            # Check if this snapshot exists
            snapshot_dir = os.path.join(model_dir, "snapshots", commit_hash)
            result["tests"]["snapshot_exists"] = os.path.exists(snapshot_dir)
            
            if os.path.exists(snapshot_dir):
                snapshot_files = os.listdir(snapshot_dir)
                result["tests"]["snapshot_files"] = snapshot_files[:20]  # First 20 files
    
    # Test 3: Try to load with different parameters
    test_configs = [
        {"local_files_only": True, "cache_dir": cache_dir},
        {"local_files_only": True, "cache_dir": cache_dir, "trust_remote_code": True},
        {"local_files_only": False, "cache_dir": cache_dir, "trust_remote_code": True},
    ]
    
    for i, config in enumerate(test_configs):
        try:
            # Force offline mode
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            
            tokenizer = AutoTokenizer.from_pretrained(model_name, **config)
            result["tests"][f"config_{i}"] = {"success": True, "config": config}
        except Exception as e:
            result["tests"][f"config_{i}"] = {
                "success": False, 
                "config": config,
                "error": str(e),
                "error_type": type(e).__name__
            }
    
    return result


@app.get("/api/test/processing")
async def test_processing():
    """Test the processing pipeline step by step"""
    results = {}
    
    # Test 1: Import pdf2image
    try:
        import pdf2image
        results["pdf2image"] = {"success": True, "version": getattr(pdf2image, "__version__", "unknown")}
    except Exception as e:
        results["pdf2image"] = {"success": False, "error": str(e)}
    
    # Test 2: Check poppler
    try:
        import subprocess
        result = subprocess.run(["pdftoppm", "-v"], capture_output=True, text=True)
        results["poppler"] = {
            "success": result.returncode == 0,
            "stdout": result.stdout[:200],
            "stderr": result.stderr[:200]
        }
    except Exception as e:
        results["poppler"] = {"success": False, "error": str(e)}
    
    # Test 3: Create test PDF
    try:
        from PIL import Image, ImageDraw
        import io
        
        # Create test image
        img = Image.new('RGB', (800, 600), color='white')
        draw = ImageDraw.Draw(img)
        draw.text((50, 50), "Test PDF Content", fill='black')
        
        # Convert to PDF
        pdf_buffer = io.BytesIO()
        img.save(pdf_buffer, format='PDF')
        pdf_bytes = pdf_buffer.getvalue()
        
        results["test_pdf"] = {
            "success": True,
            "size": len(pdf_bytes)
        }
        
        # Test 4: Convert PDF to images
        try:
            images = pdf2image.convert_from_bytes(
                pdf_bytes,
                dpi=150,
                fmt='PNG'
            )
            results["pdf_conversion"] = {
                "success": True,
                "num_images": len(images),
                "first_image_size": images[0].size if images else None
            }
        except Exception as e:
            results["pdf_conversion"] = {
                "success": False,
                "error": str(e),
                "type": type(e).__name__
            }
            
    except Exception as e:
        results["test_pdf"] = {"success": False, "error": str(e)}
    
    # Test 5: OCR service
    try:
        results["ocr_service"] = {
            "model_loaded": ocr_service._model_loaded,
            "device": str(ocr_service.device) if ocr_service.device else "not set"
        }
    except Exception as e:
        results["ocr_service"] = {"success": False, "error": str(e)}
    
    return results


@app.get("/api/test/simple-ocr")
async def test_simple_ocr():
    """Test OCR on a simple image"""
    try:
        from PIL import Image, ImageDraw
        import io
        
        # Create a simple test image
        img = Image.new('RGB', (800, 200), color='white')
        draw = ImageDraw.Draw(img)
        draw.text((50, 50), "Hello World! This is a test.", fill='black')
        
        # Convert to bytes
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        
        # Try OCR
        result = ocr_service.process_image(img)
        
        return {
            "success": True,
            "model_loaded": ocr_service._model_loaded,
            "text": result.get("text", ""),
            "image_size": img.size
        }
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "model_loaded": ocr_service._model_loaded
        }


@app.get("/api/test/cache-debug")
async def test_cache_debug():
    """Debug cache structure using OCR service debug method"""
    from app.ocr_service_v2_debug import OCRService
    
    ocr = OCRService()
    debug_info = ocr._debug_cache_structure()
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "debug_info": debug_info
    }


@app.get("/api/test/gcs-mount-diagnosis")
async def test_gcs_mount():
    """Diagnose GCS mount issues"""
    import subprocess
    import sys
    
    # Run the diagnostic script
    result = subprocess.run(
        [sys.executable, "/app/app/gcs_mount_fix.py"],
        capture_output=True,
        text=True
    )
    
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode
    }


@app.get("/api/test/model-load-debug")
async def test_model_load_debug():
    """Debug why model won't load"""
    import os
    from pathlib import Path
    
    result = {
        "env_vars": {
            "HF_HOME": os.environ.get("HF_HOME"),
            "TRANSFORMERS_CACHE": os.environ.get("TRANSFORMERS_CACHE"),
            "MODEL_CACHE_PATH": os.environ.get("MODEL_CACHE_PATH"),
            "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE"),
            "TRANSFORMERS_OFFLINE": os.environ.get("TRANSFORMERS_OFFLINE"),
        },
        "cache_locations": {},
        "model_search": {}
    }
    
    # First check what's at /cache root
    if os.path.exists("/cache"):
        cache_contents = os.listdir("/cache")
        result["cache_root"] = {
            "exists": True,
            "contents": cache_contents,
            "is_empty": len(cache_contents) == 0
        }
        
        # Check if huggingface is a file or directory
        hf_path = "/cache/huggingface"
        if "huggingface" in cache_contents:
            if os.path.isdir(hf_path):
                result["cache_root"]["huggingface_is_dir"] = True
                try:
                    hf_contents = os.listdir(hf_path)
                    result["cache_root"]["huggingface_contents"] = hf_contents[:10]
                except Exception as e:
                    result["cache_root"]["huggingface_error"] = str(e)
            elif os.path.isfile(hf_path):
                result["cache_root"]["huggingface_is_file"] = True
                result["cache_root"]["huggingface_size"] = os.path.getsize(hf_path)
            elif os.path.islink(hf_path):
                result["cache_root"]["huggingface_is_link"] = True
                result["cache_root"]["huggingface_target"] = os.readlink(hf_path)
        
        # Try to access it anyway
        try:
            import subprocess
            # Use ls -la to see what's really there
            ls_result = subprocess.run(["ls", "-la", "/cache"], capture_output=True, text=True)
            result["cache_root"]["ls_output"] = ls_result.stdout.split('\n')[:10]
        except Exception as e:
            result["cache_root"]["ls_error"] = str(e)
            
    else:
        result["cache_root"] = {"exists": False}
    
    # Check various possible cache locations
    locations = [
        "/cache",
        "/cache/huggingface",
        "/cache/huggingface/hub",
        os.environ.get("HF_HOME", ""),
        os.environ.get("TRANSFORMERS_CACHE", ""),
        os.path.expanduser("~/.cache/huggingface"),
    ]
    
    for loc in locations:
        if loc and os.path.exists(loc):
            result["cache_locations"][loc] = {
                "exists": True,
                "contents": os.listdir(loc)[:10] if os.path.isdir(loc) else "not a directory"
            }
        else:
            result["cache_locations"][loc] = {"exists": False}
    
    # Look for the specific model
    model_name = "nanonets--Nanonets-OCR-s"
    for base_path in ["/cache/huggingface", "/cache", os.environ.get("HF_HOME", "")]:
        if not base_path or not os.path.exists(base_path):
            continue
            
        # Try different paths where the model might be
        possible_paths = [
            f"{base_path}/hub/models--{model_name}",
            f"{base_path}/models--{model_name}",
            f"{base_path}/{model_name}",
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                result["model_search"][path] = {
                    "exists": True,
                    "contents": os.listdir(path)[:20] if os.path.isdir(path) else "not a directory"
                }
                
                # Check snapshots
                snapshots_path = os.path.join(path, "snapshots")
                if os.path.exists(snapshots_path):
                    result["model_search"][f"{path}/snapshots"] = os.listdir(snapshots_path)
    
    # Try to manually construct the path and check
    manual_path = "/cache/huggingface/hub/models--nanonets--Nanonets-OCR-s"
    if os.path.exists(manual_path):
        result["manual_path_check"] = {
            "path": manual_path,
            "exists": True,
            "contents": os.listdir(manual_path),
            "refs_main": None
        }
        
        refs_main = os.path.join(manual_path, "refs", "main")
        if os.path.exists(refs_main):
            with open(refs_main) as f:
                result["manual_path_check"]["refs_main"] = f.read().strip()
    else:
        result["manual_path_check"] = {"path": manual_path, "exists": False}
    
    return result


@app.get("/api/test/model-load-detailed")
async def test_model_load_detailed():
    """Detailed test of model loading process"""
    import subprocess
    import sys
    
    # Run the test script
    result = subprocess.run(
        [sys.executable, "/app/app/test_model_load.py"],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        import json
        return json.loads(result.stdout)
    else:
        return {
            "error": "Test script failed",
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }


@app.get("/api/test/cache")
async def test_cache_mount():
    """Test model cache mount and directory structure"""
    import os
    import glob
    
    result = {
        "env_vars": {
            "HF_HOME": os.environ.get("HF_HOME"),
            "TRANSFORMERS_CACHE": os.environ.get("TRANSFORMERS_CACHE"),
            "MODEL_CACHE_PATH": os.environ.get("MODEL_CACHE_PATH"),
            "HF_DATASETS_OFFLINE": os.environ.get("HF_DATASETS_OFFLINE"),
            "TRANSFORMERS_OFFLINE": os.environ.get("TRANSFORMERS_OFFLINE"),
        },
        "cache_paths": {},
        "model_search": {}
    }
    
    # Check various cache paths
    paths_to_check = [
        "/cache",
        "/cache/huggingface",
        "/cache/huggingface/hub",
        "/cache/huggingface/hub/models--nanonets--Nanonets-OCR-s",
        os.environ.get("HF_HOME", ""),
        os.environ.get("TRANSFORMERS_CACHE", ""),
        os.environ.get("MODEL_CACHE_PATH", ""),
    ]
    
    for path in paths_to_check:
        if path and os.path.exists(path):
            try:
                contents = os.listdir(path)[:10]  # First 10 items
                result["cache_paths"][path] = {
                    "exists": True,
                    "contents": contents,
                    "is_dir": os.path.isdir(path)
                }
            except Exception as e:
                result["cache_paths"][path] = {
                    "exists": True,
                    "error": str(e)
                }
        else:
            result["cache_paths"][path] = {"exists": False}
    
    # Search for model files
    search_patterns = [
        "/cache/**/config.json",
        "/cache/**/tokenizer*.json",
        "/cache/**/special_tokens_map.json",
        "/cache/**/preprocessor_config.json",
        "/cache/**/pytorch_model.bin",
        "/cache/**/model.safetensors",
        "/cache/**/nanonets*",
    ]
    
    for pattern in search_patterns:
        try:
            matches = glob.glob(pattern, recursive=True)[:10]  # First 10 matches
            result["model_search"][pattern] = matches
        except Exception as e:
            result["model_search"][pattern] = f"Error: {str(e)}"
    
    # Check specific model directory
    model_path = "/cache/huggingface/hub/models--nanonets--Nanonets-OCR-s/snapshots/3baad182cc87c65a1861f0c30357d3467e978172"
    if os.path.exists(model_path):
        result["nanonets_model_files"] = os.listdir(model_path)
    else:
        result["nanonets_model_files"] = "Model snapshot directory not found"
    
    return result


@app.get("/api/test/gcs")
async def test_gcs_connection():
    """Test GCS connectivity and basic operations"""
    try:
        from app.storage_service_v2 import HAS_GCS
        from google.cloud import storage as gcs
        
        result = {
            "has_gcs": HAS_GCS,
            "running_in_cloud": os.environ.get('RUNNING_IN_CLOUD'),
            "gcs_bucket": os.environ.get('GCS_BUCKET_NAME'),
            "test_results": {}
        }
        
        if HAS_GCS and os.environ.get('RUNNING_IN_CLOUD') == 'true':
            # Test GCS client creation
            try:
                client = gcs.Client()
                result["test_results"]["client_creation"] = "success"
            except Exception as e:
                result["test_results"]["client_creation"] = f"failed: {str(e)}"
                return result
            
            # Test bucket access
            bucket_name = os.environ.get('GCS_BUCKET_NAME', 'gnosis-ocr-storage')
            try:
                bucket = client.bucket(bucket_name)
                exists = bucket.exists()
                result["test_results"]["bucket_exists"] = exists
                result["test_results"]["bucket_name"] = bucket_name
            except Exception as e:
                result["test_results"]["bucket_access"] = f"failed: {str(e)}"
            
            # Test write/read
            try:
                test_blob = bucket.blob('test/gcs_test.txt')
                test_content = f"GCS test at {datetime.utcnow().isoformat()}"
                test_blob.upload_from_string(test_content)
                
                # Read back
                read_content = test_blob.download_as_text()
                result["test_results"]["write_read"] = "success" if read_content == test_content else "content mismatch"
                
                # Check exists
                result["test_results"]["blob_exists"] = test_blob.exists()
                
                # Clean up
                test_blob.delete()
            except Exception as e:
                result["test_results"]["write_read"] = f"failed: {str(e)}"
        
        return result
        
    except Exception as e:
        return {"error": str(e), "type": type(e).__name__}


@app.get("/api/debug/session/{session_hash}")
async def debug_session(
    session_hash: str,
    request: Request,
    x_user_email: Optional[str] = Header(None)
):
    """Debug endpoint to inspect session state"""
    try:
        user_email = get_user_email_from_request(request, x_user_email)
        storage_service = StorageService(user_email=user_email)
        
        debug_info = {
            'session_hash': session_hash,
            'user_email': user_email,
            'user_hash': storage_service._user_hash,
            'is_cloud': storage_service._is_cloud,
            'config': storage_service.config,
            'session_exists': await storage_service.validate_session(session_hash),
            'files': []
        }
        
        # Try to list session files
        try:
            session_path = storage_service.get_session_path(session_hash)
            debug_info['session_path'] = str(session_path)
            
            # Check for key files
            key_files = ['metadata.json', 'status.json', 'upload.pdf']
            for filename in key_files:
                try:
                    content = await storage_service.get_file(filename, session_hash)
                    file_info = {
                        'name': filename,
                        'exists': True,
                        'size': len(content),
                        'preview': content[:200].decode('utf-8', errors='ignore') if isinstance(content, bytes) else str(content)[:200]
                    }
                    debug_info['files'].append(file_info)
                except FileNotFoundError:
                    debug_info['files'].append({
                        'name': filename,
                        'exists': False,
                        'error': 'File not found'
                    })
                except Exception as e:
                    debug_info['files'].append({
                        'name': filename,
                        'exists': False,
                        'error': str(e)
                    })
                    
        except Exception as e:
            debug_info['session_path_error'] = str(e)
            
        logger.info("Debug session info", **debug_info)
        return debug_info
        
    except Exception as e:
        logger.error("Debug session failed", session_hash=session_hash, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))



@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler"""
    # Extract session_hash from URL if present
    session_hash = None
    if request.url.path:
        path_parts = request.url.path.strip('/').split('/')
        # Check common patterns: /status/{session_hash}, /results/{session_hash}, etc.
        if len(path_parts) >= 2 and path_parts[0] in ['status', 'results', 'images', 'download']:
            session_hash = path_parts[1]
        # Also check /api/debug/session/{session_hash}
        elif len(path_parts) >= 4 and path_parts[0] == 'api' and path_parts[1] == 'debug' and path_parts[2] == 'session':
            session_hash = path_parts[3]
    
    error_dict = ErrorResponse(
        error=exc.__class__.__name__,
        message=exc.detail,
        detail=str(exc)
    ).dict()
    
    # Add session_hash to error response if found
    if session_hash:
        error_dict['session_hash'] = session_hash
    
    return JSONResponse(
        status_code=exc.status_code,
        content=error_dict
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

