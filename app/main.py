"""Main FastAPI application for Gnosis OCR Service with new storage architecture"""
import os
import io
import asyncio
import base64
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, Dict, List
from pathlib import Path


from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import structlog

from app import __version__
from app.config import settings, validate_file_extension, format_file_size
from app.models import (
    SessionStatus, OCRResult, ErrorResponse, 
    HealthResponse, ProcessingStatus, PageResult
)
from app.storage_service import StorageService
from app.ocr_service import OCRService, ocr_service

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

# Global storage for active WebSocket connections
active_websockets: Dict[str, WebSocket] = {}

def format_job_result(result):
    """Format job result for display on job status page"""
    if isinstance(result, dict):
        # Single image result
        return result.get("text", "No text extracted")
    elif isinstance(result, list):
        # Multi-page PDF result
        if not result:
            return "No pages processed"
        
        # Combine all pages
        all_text = []
        for i, page_result in enumerate(result, 1):
            if isinstance(page_result, dict):
                page_text = page_result.get("text", "")
                if page_text.strip():
                    all_text.append(f"=== Page {i} ===\\n{page_text}")
        
        return "\\n\\n".join(all_text) if all_text else "No text extracted"
    else:
        # Fallback for other types
        return str(result)

# Session-based chunked uploads removed - using job-based chunked uploads only


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
        # Log startup environment for debugging (with error handling)
        try:
            logger.info("=== STARTUP ENVIRONMENT DEBUG ===")
            logger.info(f"DEVICE env var: {os.environ.get('DEVICE', 'not set')}")
            logger.info(f"MODEL_CACHE_PATH: {os.environ.get('MODEL_CACHE_PATH', 'not set')}")
            logger.info(f"HF_HOME: {os.environ.get('HF_HOME', 'not set')}")
            logger.info(f"TRANSFORMERS_CACHE: {os.environ.get('TRANSFORMERS_CACHE', 'not set')}")
            
            # Log mount points and cache directory
            cache_path = os.environ.get('MODEL_CACHE_PATH', '/app/cache')
            logger.info(f"Checking cache directory: {cache_path}")
            
            if os.path.exists(cache_path):
                logger.info(f"Cache directory exists: {cache_path}")
                try:
                    cache_contents = os.listdir(cache_path)
                    logger.info(f"Cache contents: {cache_contents}")
                    
                    # Check if it's empty or has HuggingFace structure
                    if not cache_contents:
                        logger.warning("Cache directory is EMPTY - model will need to download")
                    else:
                        logger.info("Cache directory has contents - checking structure...")
                        if 'hub' in cache_contents:
                            hub_path = os.path.join(cache_path, 'hub')
                            if os.path.exists(hub_path):
                                hub_contents = os.listdir(hub_path)
                                logger.info(f"Hub directory contents: {hub_contents}")
                            else:
                                logger.warning("Hub directory path exists in listing but not accessible")
                        else:
                            logger.warning("No 'hub' directory found in cache")
                except Exception as e:
                    logger.warning(f"Error reading cache directory: {e}")
            else:
                logger.warning(f"Cache directory does NOT exist: {cache_path}")
            
            # Log disk space for download capability
            import shutil
            try:
                total, used, free = shutil.disk_usage(cache_path if os.path.exists(cache_path) else '/')
                free_gb = free / (1024**3)
                logger.info(f"Available disk space: {free_gb:.1f} GB")
                if free_gb < 5:
                    logger.warning("Low disk space - model download may fail")
            except Exception as e:
                logger.warning(f"Could not check disk space: {e}")
        except Exception as startup_debug_error:
            logger.error(f"Error in startup debug logging: {startup_debug_error}")

        
        # Don't initialize storage service globally - create per request
        logger.info("Storage service will be created per-request with user context")
        
        # Don't initialize OCR service during startup - do it lazily
        logger.info("OCR service will be initialized on first use")
        logger.info("Model will download on first startup if cache is empty")
        
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

# Initialize Jinja2 templates
templates = Jinja2Templates(directory="app/templates")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/", include_in_schema=False)
async def root(request: Request):
    """Serve the web interface"""
    return templates.TemplateResponse("index.html", {"request": request})



@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint (docext pattern)"""
    gpu_info = ocr_service.get_gpu_info()
    model_health = ocr_service.health_check()
    
    # Simple cache info without requiring storage service
    cache_info = {
        "message": "Cache handled by container - model cache at /app/cache",
        "cache_path": "/app/cache",
        "available": True
    }
    
    # Use docext-style status
    overall_status = "healthy" if model_health["status"] == "ready" else "starting"
    
    return HealthResponse(
        status=overall_status,
        version=__version__,
        gpu_available=gpu_info.get('cuda_available', False),
        gpu_name=gpu_info.get('device_name'),
        model_loaded=model_health["model_loaded"],
        storage_available=True,  # Always true with new architecture
        active_sessions=0,  # Would need to implement session counting
        cache_info=cache_info
    )



@app.get("/api/v1/model/status")
async def get_model_status():
    """Get the current model loading status"""
    return ocr_service.get_model_status()


@app.get("/api/v1/model/check-cache")
async def check_model_cache():
    """Check if model files exist in cache"""
    cache_dir = os.environ.get('MODEL_CACHE_PATH', '/cache/huggingface')
    model_name = settings.model_name
    model_cache_path = os.path.join(cache_dir, 'hub', f'models--{model_name.replace("/", "--")}')
    
    result = {
        "cache_dir": cache_dir,
        "model_path": model_cache_path,
        "exists": os.path.exists(model_cache_path),
        "cache_contents": [],
        "model_files": []
    }
    
    # List cache contents
    if os.path.exists(cache_dir):
        try:
            result["cache_contents"] = os.listdir(cache_dir)[:10]  # First 10 items
        except:
            pass
    
    # List model files if exists
    if result["exists"]:
        try:
            for root, dirs, files in os.walk(model_cache_path):
                for file in files:
                    if file.endswith(('.safetensors', '.json', '.bin')):
                        size = os.path.getsize(os.path.join(root, file))
                        result["model_files"].append({
                            "name": file,
                            "size_mb": round(size / 1024 / 1024, 2),
                            "path": os.path.relpath(os.path.join(root, file), model_cache_path)
                        })
                if len(result["model_files"]) > 20:  # Limit output
                    break
        except:
            pass
    
    return result


@app.post("/api/v1/model/load")
async def load_model(background_tasks: BackgroundTasks):
    """Load model from local cache only - no downloads"""
    status = ocr_service.get_model_status()
    
    if status["loaded"]:
        return {"status": "already_loaded", "message": "Model is already loaded"}
    
    if status["status"] == "loading":
        return {"status": "in_progress", "message": "Model loading already in progress"}
    
    # Start loading in background
    background_tasks.add_task(ocr_service.load_model)
    
    return {"status": "started", "message": "Model loading started from cache"}


# Non-chunked submit endpoint removed - use /api/v1/jobs/submit/start + chunks instead


# Global storage for chunked uploads in memory
chunked_job_uploads: Dict[str, Dict] = {}

@app.post("/api/v1/jobs/submit/start")
async def start_chunked_job_upload(
    request: Request,
    x_user_email: Optional[str] = Header(None)
):
    """Start a new chunked upload for job submission"""
    try:
        upload_info = await request.json()
        filename = upload_info.get('filename')
        total_size = upload_info.get('total_size')
        total_chunks = upload_info.get('total_chunks')
        
        if not filename or not total_size or not total_chunks:
            raise HTTPException(status_code=400, detail="Missing required fields: filename, total_size, total_chunks")
        
        # Validate file type
        allowed_extensions = {'.pdf', '.png', '.jpg', '.jpeg', '.webp', '.tiff'}
        file_ext = os.path.splitext(filename)[1].lower()
        if file_ext not in allowed_extensions:
            raise HTTPException(status_code=400, detail=f"Invalid file type. Allowed: {allowed_extensions}")
        
        # Create upload session
        upload_id = str(uuid.uuid4())
        chunked_job_uploads[upload_id] = {
            'filename': filename,
            'total_size': total_size,
            'total_chunks': total_chunks,
            'chunks_received': 0,
            'chunks': {},  # chunk_number -> data
            'created_at': datetime.utcnow().isoformat(),
            'user_email': get_user_email_from_request(request, x_user_email)
        }
        
        return {
            "upload_id": upload_id,
            "message": "Chunked upload session created",
            "total_chunks": total_chunks
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting chunked upload: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to start upload")

@app.post("/api/v1/jobs/submit/chunk/{upload_id}")
async def upload_job_chunk(upload_id: str, file: UploadFile = File(...)):
    """Upload a chunk for job submission"""
    try:
        if upload_id not in chunked_job_uploads:
            raise HTTPException(status_code=404, detail="Upload session not found")
        
        upload_session = chunked_job_uploads[upload_id]
        
        # Get chunk info from headers or form data
        chunk_number = int(file.headers.get('X-Chunk-Number', 0))
        
        # Read chunk data
        chunk_data = await file.read()
        
        # Store chunk
        upload_session['chunks'][chunk_number] = chunk_data
        upload_session['chunks_received'] += 1
        
        # Check if all chunks received
        if upload_session['chunks_received'] == upload_session['total_chunks']:
            # Reassemble file
            complete_file_data = b''
            for i in range(upload_session['total_chunks']):
                if i in upload_session['chunks']:
                    complete_file_data += upload_session['chunks'][i]
                else:
                    raise HTTPException(status_code=400, detail=f"Missing chunk {i}")
            
            # Determine job type from filename
            filename = upload_session['filename']
            job_type = "pdf" if filename.lower().endswith('.pdf') else "image"
            
            # Submit complete file to OCR job system (get user_email from upload session)
            user_email = upload_session.get('user_email')
            job_id = ocr_service.submit_job(complete_file_data, job_type=job_type, user_email=user_email)

            
            # Clean up upload session
            del chunked_job_uploads[upload_id]
            
            # Get job status
            job_status = ocr_service.get_job_status(job_id)
            
            return {
                "upload_complete": True,
                "job_id": job_id,
                "status": job_status["status"],
                "message": "File uploaded and job submitted successfully"
            }
        else:
            return {
                "upload_complete": False,
                "chunks_received": upload_session['chunks_received'],
                "total_chunks": upload_session['total_chunks'],
                "message": f"Chunk {chunk_number} received"
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading chunk: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to upload chunk")


@app.get("/api/v1/jobs/status/{job_id}")

async def get_job_status(job_id: str):
    """Get status and result of OCR job by ID"""
    result = ocr_service.get_job_status(job_id)
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Job not found")
    return result


@app.get("/job/{job_id}")
async def job_status_page(request: Request, job_id: str):
    """HTML page showing job status with auto-refresh"""
    job = ocr_service.get_job_status(job_id)
    if job["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Format result if it exists
    if job.get("result"):
        job["result"] = format_job_result(job["result"])
    
    return templates.TemplateResponse("job_status.html", {
        "request": request,
        "job": job,
        "job_id": job_id
    })



@app.get("/job/{job_id}/result")
async def job_result_page(request: Request, job_id: str):

    """HTML page showing job result"""
    job = ocr_service.get_job_status(job_id)
    if job["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job["status"] != "completed" or not job.get("result"):
        raise HTTPException(status_code=404, detail="Job result not available")
    
    result = job["result"]
    text = format_job_result(result)
    
    return templates.TemplateResponse("job_result.html", {
        "request": request,
        "job": job,
        "job_id": job_id,
        "text": text,
        "result": result
    })


@app.get("/api/v1/jobs/{job_id}/download")
async def download_job_result(job_id: str):
    """Download job result as plain text file"""
    job = ocr_service.get_job_status(job_id)
    
    if job["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job["status"] != "completed" or not job.get("result"):
        raise HTTPException(status_code=404, detail="Job result not available")
    
    # Format the result text
    text = format_job_result(job["result"])
    
    # Create filename with timestamp
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ocr_result_{job_id}_{timestamp}.txt"
    
    # Return as downloadable file
    return Response(
        content=text,
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
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
    logger.debug("STATUS ENDPOINT - NO AUTH VERSION", session_hash=session_hash)

    
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
    logger.debug("RESULTS ENDPOINT - NO AUTH VERSION", session_hash=session_hash)

    
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
    logger.debug("FILE SERVE - NO AUTH VERSION")

    
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
    logger.debug("DOWNLOAD ENDPOINT - NO AUTH VERSION", session_hash=session_hash)

    
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
    # Model cache is now part of the container image
    return {
        "cache_info": {
            "message": "Model cache is built into container image",
            "model_loaded": ocr_service.is_ready()
        },
        "model_loaded": ocr_service.is_ready(),
        "gpu_info": ocr_service.get_gpu_info()
    }


@app.get("/debug/env")
async def debug_environment():
    """Debug endpoint to check environment and model loading"""
    import glob
    import torch
    
    cache_path = os.environ.get('MODEL_CACHE_PATH', '/cache/huggingface')
    
    # Get all HF-related env vars
    hf_env_vars = {k: v for k, v in os.environ.items() if 'HF' in k or 'TRANSFORMERS' in k or 'CACHE' in k}
    
    # Check cache directory structure
    cache_structure = {}
    if os.path.exists(cache_path):
        try:
            # List top-level directories
            cache_structure['top_level'] = os.listdir(cache_path)
            
            # Check hub directory
            hub_path = os.path.join(cache_path, 'hub')
            if os.path.exists(hub_path):
                cache_structure['hub'] = os.listdir(hub_path)
                
                # Check for our model
                model_path = os.path.join(hub_path, 'models--nanonets--Nanonets-OCR-s')
                if os.path.exists(model_path):
                    cache_structure['model'] = os.listdir(model_path)
                    
                    # Check critical directories
                    for subdir in ['refs', 'snapshots', 'blobs']:
                        subpath = os.path.join(model_path, subdir)
                        if os.path.exists(subpath):
                            files = os.listdir(subpath)
                            cache_structure[f'model_{subdir}'] = files[:10]  # First 10 files
        except Exception as e:
            cache_structure['error'] = str(e)
    
    # Check if model can be loaded
    model_load_test = {
        "ocr_service_exists": ocr_service is not None,
        "model_loaded": ocr_service.is_ready() if ocr_service else False,
        "device": str(ocr_service.device) if ocr_service and hasattr(ocr_service, 'device') else 'unknown'
    }
    
    return {
        "environment_variables": hf_env_vars,
        "cache_path": cache_path,
        "cache_exists": os.path.exists(cache_path),
        "cache_structure": cache_structure,
        "model_load_test": model_load_test,
        "cuda_available": torch.cuda.is_available(),
        "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
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
    # Debug import removed - using main ocr_service_v2
    
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

