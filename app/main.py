from fastapi import FastAPI, Request, HTTPException, Header, File, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, Response
from typing import Optional
import os
import uuid
import logging
from datetime import datetime

from app.storage_service import StorageService
from app.models import HealthResponse
from app.uploader import UploadManager, get_user_email_from_request, get_user_hash_from_request
from app.jobs import JobProcessor
from app import __version__
from app.job_routes import router as job_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


# Create FastAPI app instance
app = FastAPI(
    title="Gnosis OCR-S",
    description="OCR Service for Gnosis",
    version="0.1.0"
)

# Get the directory where this file is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Mount static files
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# Set up Jinja2 templates
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Include routers
app.include_router(job_router)


@app.get("/", response_class=HTMLResponse)

async def read_root(request: Request):
    """Serve the root index.html file"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Basic 404 error handling"""
    return templates.TemplateResponse("index.html", {"request": request}, status_code=404)


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc):
    """Basic 500 error handling"""
    return templates.TemplateResponse("index.html", {"request": request}, status_code=500)


@app.get("/storage/{user_hash}/{session_hash}/{filename:path}")
@app.head("/storage/{user_hash}/{session_hash}/{filename:path}")
async def serve_user_file(
    user_hash: str,
    session_hash: str,
    filename: str,
    request: Request,
    x_user_email: Optional[str] = Header(None)
):
    """Serve files from user storage - NO AUTH"""
    logger.debug(f"FILE SERVE - NO AUTH VERSION: user_hash={user_hash}, session_hash={session_hash}, filename={filename}")
    
    # Create anonymous storage service
    storage_service = StorageService(user_email=None)
    
    # Force GCS in cloud environment
    if os.environ.get('RUNNING_IN_CLOUD') == 'true':
        storage_service.force_cloud_mode()
    
    # Override user hash to match URL
    storage_service._user_hash = user_hash
    logger.info(f"FILE SERVE USING URL HASH: user_hash={user_hash}, session_hash={session_hash}, filename={filename}")

    try:
        # Get file content
        content = await storage_service.get_file(filename, session_hash)
        
        # Check if content is None
        if content is None:
            logger.error(f"File content is None for: {filename} in session {session_hash}")
            raise HTTPException(status_code=404, detail="File content not found")
        
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
        
        # Build headers
        headers = {
            "Content-Disposition": f"inline; filename={filename}"
        }
        
        # Add cache headers only for JSON files
        if filename.endswith('.json'):
            headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            headers["Pragma"] = "no-cache"
            headers["Expires"] = "0"
        else:
            headers["Cache-Control"] = "public, max-age=3600"
        
        return Response(
            content=content,
            media_type=content_type,
            headers=headers
        )
        
    except FileNotFoundError:
        logger.error(f"File not found: {filename} in session {session_hash}")
        raise HTTPException(status_code=404, detail="File not found")
    except Exception as e:
        logger.error(f"Error serving file: {filename}, error: {str(e)}, type: {type(e).__name__}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error retrieving file: {str(e)}")



@app.post("/storage/upload")
async def upload_file(
    request: Request,
    file: Optional[UploadFile] = File(None),
    x_user_email: Optional[str] = Header(None),
    x_user_hash: Optional[str] = Header(None)
):
    """Handle both normal uploads and chunked upload starts"""
    user_email = get_user_email_from_request(request, x_user_email)
    user_hash = get_user_hash_from_request(request, x_user_hash)
    
    storage_service = StorageService(user_email=user_email)
    # Override user hash if explicitly provided via header
    if x_user_hash:  # Only override if header was actually provided
        storage_service._user_hash = user_hash

    
    try:
        if file:
            # Normal file upload
            content = await file.read()
            session_id = await storage_service.create_session()
            await storage_service.save_file(content, file.filename, session_id)
            
            logger.info(f"Uploaded {file.filename} ({len(content)} bytes) to session {session_id}")
            
            return {
                "type": "normal_upload",
                "session_id": session_id,
                "filename": file.filename,
                "size": len(content),
                "message": f"File {file.filename} uploaded successfully"
            }
        else:
            # Chunked upload start - expect JSON
            upload_data = await request.json()
            filename = upload_data.get("filename")
            total_size = upload_data.get("total_size")
            total_chunks = upload_data.get("total_chunks")
            
            if not all([filename, total_size, total_chunks]):
                raise HTTPException(
                    status_code=400, 
                    detail="Missing required fields: filename, total_size, total_chunks"
                )
            
            # Create session and start chunked upload
            session_id = await storage_service.create_session()
            upload_manager = UploadManager(storage_service, session_id)
            chunker_data = await upload_manager.start_chunked_upload(filename, total_size, total_chunks)
            
            logger.info(f"Started chunked upload for {filename} in session {session_id}")
            
            return {
                "type": "chunked_upload_start",
                "session_id": session_id,
                "filename": filename,
                "total_size": total_size,
                "total_chunks": total_chunks,
                "status": chunker_data["status"],
                "message": f"Chunked upload started for {filename}"
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in upload: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")


@app.post("/storage/upload/{session_id}/chunk")
async def upload_chunk(
    session_id: str,
    file: UploadFile = File(...),
    request: Request = None,
    x_user_email: Optional[str] = Header(None),
    x_user_hash: Optional[str] = Header(None),
    x_chunk_number: Optional[int] = Header(None)
):
    """Upload a chunk to an existing chunked upload session"""
    user_email = get_user_email_from_request(request, x_user_email)
    user_hash = get_user_hash_from_request(request, x_user_hash)
    
    storage_service = StorageService(user_email=user_email)
    if x_user_hash:
        storage_service._user_hash = user_hash
    
    chunk_number = x_chunk_number
    if chunk_number is None:
        raise HTTPException(status_code=400, detail="Missing X-Chunk-Number header")
    
    try:
        chunk_data = await file.read()
        upload_manager = UploadManager(storage_service, session_id)
        
        # Call the stateless method, which returns None
        await upload_manager.add_chunk(chunk_number, chunk_data)
        
        # Since the call succeeded, return a simple success message.
        # The check for 'if not chunker_data' has been removed.
        return {
            "session_id": session_id,
            "chunk_number": chunk_number,
            "status": "received"
        }
        
    except Exception as e:
        logger.error(f"Error uploading chunk: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chunk upload failed: {str(e)}")


@app.get("/storage/upload/{session_id}")
async def get_upload_status(
    session_id: str,
    request: Request = None,  # Add request back for helper functions
    x_user_email: Optional[str] = Header(None),
    x_user_hash: Optional[str] = Header(None)
):
    """Get status of an upload session"""
    user_email = get_user_email_from_request(request, x_user_email)
    user_hash = get_user_hash_from_request(request, x_user_hash)
    
    storage_service = StorageService(user_email=user_email)
    if x_user_hash:
        storage_service._user_hash = user_hash
    
    try:
        upload_manager = UploadManager(storage_service, session_id)
        
        # CORRECTED: Call the method that includes the 'missing_chunks' field
        chunker_data = await upload_manager.get_status_with_derived_fields()
        
        if not chunker_data:
            raise HTTPException(status_code=404, detail="Upload session not found")
        
        # The return dictionary can now be simplified since the fields are already there
        return chunker_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting upload status: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get status: {str(e)}")


@app.post("/storage/upload/{session_id}/assemble")
async def assemble_chunked_upload(
    session_id: str,
    request: Request = None,
    x_user_email: Optional[str] = Header(None),
    x_user_hash: Optional[str] = Header(None)
):
    """
    Triggers the final assembly of a chunked upload after the client
    has verified all chunks are present.
    """
    user_email = get_user_email_from_request(request, x_user_email)
    user_hash = get_user_hash_from_request(request, x_user_hash)
    
    storage_service = StorageService(user_email=user_email)
    if x_user_hash:
        storage_service._user_hash = user_hash

    try:
        upload_manager = UploadManager(storage_service, session_id)
        final_status = await upload_manager.assemble_file()
        return final_status
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error assembling file for session {session_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="File assembly failed")


@app.get("/health", response_model=HealthResponse)
async def health_check():

    """Health check endpoint"""
    # Simple health check without OCR service dependency
    cache_info = {
        "message": "Cache handled by container - model cache at /app/cache",
        "cache_path": "/app/cache", 
        "available": True
    }
    
    return HealthResponse(
        status="healthy",
        version=__version__,
        gpu_available=False,  # Will be updated when OCR service is added
        gpu_name=None,
        model_loaded=False,  # Will be updated when OCR service is added
        storage_available=True,
        active_sessions=0,
        cache_info=cache_info
    )


@app.post("/worker/process-job")
async def process_job_worker(request: Request):
    """Worker endpoint called by Cloud Tasks to process jobs"""
    try:
        # Get job details from request
        job_data = await request.json()
        job_id = job_data.get("job_id")
        session_id = job_data.get("session_id")
        user_email = job_data.get("user_email")
        
        if not job_id or not session_id:
            raise HTTPException(status_code=400, detail="Missing job_id or session_id")
        
        logger.info(f"Worker processing job {job_id} for session {session_id}")
        
        # Create storage service with user context
        storage_service = StorageService(user_email=user_email)
        
        # We still need a JobManager instance for the processor's __init__
        from app.jobs import JobManager
        job_manager = JobManager(storage_service)
        processor = JobProcessor(job_manager, storage_service)
        
        # --- THIS IS THE FIX ---
        # Pass the entire job_data dictionary to the processor
        await processor.process_job(job_data)
        
        return {"status": "success", "job_id": job_id}
        
    except Exception as e:
        logger.error(f"Worker failed to process job {job_id}: {e}", exc_info=True)
        # Return 500 to trigger Cloud Tasks retry
        raise HTTPException(status_code=500, detail=str(e))

