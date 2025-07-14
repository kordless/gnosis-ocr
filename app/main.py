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
from pydantic import BaseModel
import structlog

from app import __version__
from app.config import settings, validate_file_extension, format_file_size
from app.models import (
    SessionStatus, OCRResult, ErrorResponse, 
    HealthResponse, ProcessingStatus, PageResult
)
from app.storage_service import StorageService
from app.ocr_service import OCRService, ocr_service
from app.chunked_upload import ChunkedUploadSession

# Cloud Tasks client (only imported when needed)
_cloud_tasks_client = None

def get_cloud_tasks_client():
    """Get or create Cloud Tasks client (lazy initialization)"""
    global _cloud_tasks_client
    if _cloud_tasks_client is None and os.environ.get('RUNNING_IN_CLOUD') == 'true':
        try:
            from google.cloud import tasks_v2
            _cloud_tasks_client = tasks_v2.CloudTasksClient()
            logger.info("Cloud Tasks client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Cloud Tasks client: {e}")
            _cloud_tasks_client = None
    return _cloud_tasks_client

async def create_ocr_processing_task(session_id: str, user_email: Optional[str] = None):
    """Create a Cloud Task to trigger OCR batch processing"""
    if os.environ.get('RUNNING_IN_CLOUD') != 'true':
        logger.debug("Not in cloud mode, skipping task creation")
        return
        
    try:
        client = get_cloud_tasks_client()
        if not client:
            logger.error("Cloud Tasks client not available")
            return
            
        # Build task queue path
        parent = client.queue_path(
            settings.cloud_tasks_project,
            settings.cloud_tasks_location, 
            settings.cloud_tasks_queue
        )
        
        # Create task payload
        payload = {
            "session_id": session_id,
            "user_email": user_email,
            "batch_size": int(os.environ.get('OCR_BATCH_SIZE', '10'))
        }
        
        # Create HTTP task for worker endpoint  
        from google.cloud import tasks_v2
        from google.protobuf.duration_pb2 import Duration
        
        # Set task timeout to 15 minutes for OCR processing
        timeout = Duration()
        timeout.seconds = 900  # 15 minutes
        
        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{settings.worker_service_url}/process-ocr-batch",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(payload).encode('utf-8')
            },
            "dispatch_deadline": timeout
        }
        
        # Submit the task
        response = client.create_task(parent=parent, task=task)
        logger.info(f"Created Cloud Task {response.name} for session {session_id}")
        
    except Exception as e:
        logger.error(f"Failed to create Cloud Task for session {session_id}: {e}")


class ProcessBatchRequest(BaseModel):
    """Request model for batch processing endpoint"""
    session_id: str
    user_email: Optional[str] = None
    batch_size: Optional[int] = 10

# Configure standard Python logging for Cloud Run console visibility
import logging

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # Ensure logs go to stdout/stderr
)

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


# === CLOUD WORKER ENDPOINTS ===

def get_pending_pages(processing_data: dict, batch_size: int) -> List[int]:
    """Get next batch of pending pages to process"""
    pending_pages = []
    for page_num_str, page_info in processing_data['pages'].items():
        if page_info['status'] == 'pending' and len(pending_pages) < batch_size:
            pending_pages.append(int(page_num_str))
    return sorted(pending_pages)


def all_pages_processed(processing_data: dict) -> bool:
    """Check if all pages have been processed (completed or failed)"""
    for page_info in processing_data['pages'].values():
        if page_info['status'] in ['pending', 'processing']:
            return False
    return True


async def combine_results(storage_service: StorageService, session_id: str, processing_data: dict) -> None:
    """Combine all page results into a single markdown file"""
    combined_text = []
    
    # Sort pages by number
    sorted_pages = sorted(processing_data['pages'].items(), key=lambda x: int(x[0]))
    
    for page_num_str, page_info in sorted_pages:
        if page_info['status'] == 'completed' and page_info['result_file']:
            try:
                # Load page result
                result_data = await storage_service.get_file(page_info['result_file'], session_id)
                page_text = result_data.decode('utf-8')
                
                # Debug: Log page result content
                logger.info(f"📄 Page {page_num_str} result length: {len(page_text)} chars")
                logger.info(f"📄 Page {page_num_str} preview: {page_text[:100]}")
                
                # Add page header and content
                combined_text.append(f"# Page {page_num_str}\n\n{page_text}\n\n")
                
            except FileNotFoundError:
                logger.warning(f"Result file not found for page {page_num_str}: {page_info['result_file']}")
                combined_text.append(f"# Page {page_num_str}\n\n*[Processing failed or result not available]*\n\n")
    
    # Save combined result
    combined_content = "".join(combined_text)
    await storage_service.save_file(combined_content, "combined_output.md", session_id)
    logger.info(f"Combined results for {len(sorted_pages)} pages saved to combined_output.md")


async def update_status(storage_service: StorageService, session_id: str, status: str) -> None:
    """Update the overall job status"""
    try:
        # Try to load existing status.json
        status_json = await storage_service.get_file('status.json', session_id)
        status_data = json.loads(status_json)
    except FileNotFoundError:
        # Create basic status if not found
        status_data = {
            "status": "unknown",
            "progress": {"percent": 0},
            "created": datetime.utcnow().isoformat()
        }
    
    # Update status
    status_data["status"] = status
    status_data["updated"] = datetime.utcnow().isoformat()
    
    if status == "completed":
        status_data["progress"]["percent"] = 100
        status_data["progress"]["message"] = "All pages processed successfully"
    
    # Save updated status
    await storage_service.save_file(json.dumps(status_data, indent=2), "status.json", session_id)


@app.post("/process-ocr-batch")
async def process_ocr_batch(request: ProcessBatchRequest):
    """Process a batch of OCR pages from Cloud Tasks"""
    
    try:
        # Initialize storage service
        storage_service = StorageService(user_email=request.user_email)
        
        # Load processing.json with atomic read
        try:
            processing_json = await storage_service.get_file('processing.json', request.session_id)
            processing_data = json.loads(processing_json)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Processing job not found")
        
        # Check if this is a raw file that needs page extraction first
        file_reference = processing_data.get('file_reference', {})
        needs_extraction = (
            'raw_file' in file_reference and 
            not processing_data.get('pages') and 
            not file_reference.get('extraction_completed', False)
        )
        
        if needs_extraction:
            logger.info(f"Extracting pages from raw PDF: {file_reference['raw_file']}")
            await extract_pdf_pages(storage_service, request.session_id, processing_data)
            
            # Reload processing data after page extraction
            processing_json = await storage_service.get_file('processing.json', request.session_id)
            processing_data = json.loads(processing_json)
        
        # Find next batch of pending pages
        pending_pages = get_pending_pages(processing_data, request.batch_size)
        
        if not pending_pages:
            return {"status": "no_pending_pages", "message": "No pages to process"}
        
        logger.info(f"Processing batch of {len(pending_pages)} pages for session {request.session_id}")
        
        # Lock pages by marking as processing (atomic update)
        for page_num in pending_pages:
            processing_data['pages'][str(page_num)]['status'] = 'processing'
            processing_data['pages'][str(page_num)]['started_at'] = datetime.utcnow().isoformat()
        
        processing_data['updated_at'] = datetime.utcnow().isoformat()
        
        # Save updated processing.json (atomic write)
        await storage_service.save_file(
            json.dumps(processing_data, indent=2),
            'processing.json',
            request.session_id
        )
        
        # Process each page in the batch
        processed_count = 0
        for page_num in pending_pages:
            try:
                page_info = processing_data['pages'][str(page_num)]
                image_filename = page_info['image']
                
                logger.info(f"Processing page {page_num}: {image_filename}")
                
                # Load image from storage
                image_data = await storage_service.get_file(image_filename, request.session_id)
                
                # Process OCR using the existing OCR service
                from PIL import Image
                import io
                image = Image.open(io.BytesIO(image_data))
                result = ocr_service.process_image(image)
                
                # Save result to storage
                result_filename = f'page_{page_num:03d}_result.txt'
                await storage_service.save_file(result['text'], result_filename, request.session_id)
                
                # Update processing.json for this page
                processing_data['pages'][str(page_num)]['status'] = 'completed'
                processing_data['pages'][str(page_num)]['completed_at'] = datetime.utcnow().isoformat()
                processing_data['pages'][str(page_num)]['result_file'] = result_filename
                
                processed_count += 1
                logger.info(f"✅ Completed page {page_num}")
                
            except Exception as e:
                logger.error(f"❌ Failed to process page {page_num}: {str(e)}")
                processing_data['pages'][str(page_num)]['status'] = 'failed'
                processing_data['pages'][str(page_num)]['error'] = str(e)
                processing_data['pages'][str(page_num)]['completed_at'] = datetime.utcnow().isoformat()
        
        # Save final processing.json
        processing_data['updated_at'] = datetime.utcnow().isoformat()
        await storage_service.save_file(
            json.dumps(processing_data, indent=2),
            'processing.json',
            request.session_id
        )
        
        # Check if all pages are done
        if all_pages_processed(processing_data):
            logger.info(f"🎉 All pages processed for session {request.session_id}")
            
            # Combine results into final output
            await combine_results(storage_service, request.session_id, processing_data)
            
            # Update overall status to completed
            await update_status(storage_service, request.session_id, 'completed')
            
            return {
                "status": "job_completed",
                "pages_processed": processed_count,
                "total_pages": len(processing_data['pages']),
                "message": "All pages completed successfully"
            }
        else:
            # Create next Cloud Task for remaining pages
            await create_ocr_processing_task(request.session_id, request.user_email)
            
            remaining = sum(1 for p in processing_data['pages'].values() 
                          if p['status'] in ['pending', 'processing'])
            
            return {
                "status": "batch_processed", 
                "pages_processed": processed_count,
                "remaining_pages": remaining,
                "message": f"Processed {processed_count} pages, {remaining} remaining"
            }
            
    except Exception as e:
        logger.error(f"Batch processing failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Batch processing failed: {str(e)}")


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint (docext pattern)"""
    # Run potentially blocking calls in thread pool to avoid blocking FastAPI
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        gpu_info = await loop.run_in_executor(executor, ocr_service.get_gpu_info)
        model_health = await loop.run_in_executor(executor, ocr_service.health_check)
    
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


# Global storage for chunked uploads in memory (local mode)
chunked_job_uploads: Dict[str, Dict] = {}


async def create_cloud_processing_job(storage_service, session_id: str, file_reference: dict, user_email: str) -> str:
    """Create processing.json for cloud-based batch processing"""
    from datetime import datetime
    import uuid
    
    # In cloud mode, use session_id as job_id to avoid mapping issues
    job_id = session_id
    
    # Handle raw file case - defer page extraction to Cloud Tasks worker
    if 'raw_file' in file_reference:
        total_pages = 1  # Will be determined by worker during PDF extraction
        status = "extracting"  # Initial status for raw file processing
    else:
        total_pages = file_reference.get("page_count", 1)
        status = "queued"
    
    # Create processing.json structure as per PLAN 2B
    processing_data = {
        "job_id": job_id,
        "session_id": session_id,
        "total_pages": total_pages,
        "batch_size": int(os.environ.get('OCR_BATCH_SIZE', '3')),  # Reduced for cloud timeout
        "file_reference": file_reference,
        "user_email": user_email,
        "pages": {},
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "status": status
    }
    
    # Initialize page tracking - only if we have pre-extracted pages
    logger.error(f"[DEBUG] file_reference contents: {file_reference}")
    logger.error(f"[DEBUG] page_images in file_reference: {'page_images' in file_reference}")
    
    if 'page_images' in file_reference:
        logger.error(f"[DEBUG] Initializing {len(file_reference['page_images'])} pages")
        for i, image_filename in enumerate(file_reference["page_images"]):
            page_num = i + 1
            processing_data["pages"][str(page_num)] = {
                "image": image_filename,
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "result_file": None,
                "error": None
            }
            logger.error(f"[DEBUG] Added page {page_num} with image {image_filename}")
    else:
        logger.error(f"[DEBUG] No page_images found, pages dict will be empty")
    # For raw files, pages will be initialized by the Cloud Tasks worker after extraction
    
    # Save processing.json to storage with atomic operation support
    processing_json = json.dumps(processing_data, indent=2)
    await storage_service.save_file(processing_json, "processing.json", session_id)
    
    # Create status.json for compatibility with existing status checks
    status_data = {
        "job_id": job_id,
        "status": "queued",
        "progress": {
            "current_step": "queued",
            "message": "Job queued for cloud processing",
            "current_page": 0,
            "total_pages": file_reference.get("page_count", 1),
            "percent": 0
        },
        "created": datetime.utcnow().isoformat(),
        "result": None,
        "error": None
    }
    
    status_json = json.dumps(status_data, indent=2)
    await storage_service.save_file(status_json, "status.json", session_id)
    
    logger.info(f"Created cloud processing job {job_id} with {file_reference.get('page_count', 1)} pages")
    
    # Create Cloud Task to trigger worker processing
    await create_ocr_processing_task(session_id, user_email)
    
    return job_id


async def extract_pdf_pages(storage_service, session_id: str, processing_data: dict):
    """Extract pages from a PDF file and initialize page tracking"""
    import pdf2image
    from PIL import Image
    import io
    
    file_reference = processing_data['file_reference']
    raw_filename = file_reference['raw_file']
    
    logger.info(f"Loading PDF file: {raw_filename}")
    
    # Load the raw PDF file
    pdf_data = await storage_service.get_file(raw_filename, session_id)
    
    # Convert PDF to images
    logger.info("Converting PDF pages to images...")
    images = pdf2image.convert_from_bytes(
        pdf_data,
        dpi=150,
        fmt='PNG',
        thread_count=2
    )
    
    logger.info(f"Extracted {len(images)} pages from PDF")
    
    # Save each page as an image and update processing data
    for i, image in enumerate(images):
        page_num = i + 1
        image_filename = f"page_{page_num:03d}.png"
        
        # Save image to storage
        img_buffer = io.BytesIO()
        image.save(img_buffer, format='PNG')
        img_data = img_buffer.getvalue()
        
        await storage_service.save_file(img_data, image_filename, session_id)
        logger.info(f"Saved page {page_num} as {image_filename}")
        
        # Add page to processing data
        processing_data['pages'][str(page_num)] = {
            "image": image_filename,
            "status": "pending",
            "started_at": None,
            "completed_at": None,
            "result_file": None,
            "error": None
        }
    
    # Update total pages and status
    processing_data['total_pages'] = len(images)
    processing_data['status'] = 'queued'  # Ready for processing
    processing_data['updated_at'] = datetime.utcnow().isoformat()
    
    # Update file_reference to indicate extraction is complete
    page_image_list = [f"page_{i+1:03d}.png" for i in range(len(images))]
    processing_data['file_reference'] = {
        **processing_data['file_reference'],
        'page_images': page_image_list,
        'page_count': len(images),
        'extraction_completed': True
    }
    # Keep raw_file for reference but mark as extracted
    
    # Save updated processing.json
    await storage_service.save_file(
        json.dumps(processing_data, indent=2),
        'processing.json',
        session_id
    )
    
    logger.info(f"PDF extraction complete: {len(images)} pages ready for OCR")


async def find_session_for_job(job_id: str) -> Optional[str]:
    """Find the session_id for a given job_id"""
    # In cloud mode, job_id equals session_id (as of latest fix)
    return job_id


async def get_cloud_job_status(job_id: str, session_id: str) -> dict:
    """Get job status from processing.json for cloud deployments"""
    from app.storage_service import StorageService
    
    # Create storage service - we'll need to improve user context handling
    storage_service = StorageService(user_email=None)  # Anonymous for now
    
    try:
        # Load processing.json
        processing_json = await storage_service.get_file('processing.json', session_id)
        processing_data = json.loads(processing_json)
        
        # Calculate progress from pages
        total_pages = len(processing_data['pages'])
        completed_pages = sum(1 for p in processing_data['pages'].values() 
                            if p['status'] == 'completed')
        failed_pages = sum(1 for p in processing_data['pages'].values() 
                         if p['status'] == 'failed')
        processing_pages = sum(1 for p in processing_data['pages'].values() 
                             if p['status'] == 'processing')
        
        # Determine overall status
        if failed_pages > 0:
            status = "failed"
            message = f"Processing failed on {failed_pages} pages"
        elif completed_pages == total_pages:
            status = "completed"
            message = "All pages processed successfully"
        elif processing_pages > 0:
            status = "processing"
            message = f"Processing page {completed_pages + processing_pages} of {total_pages}"
        else:
            status = "queued"
            message = "Waiting for processing to start"
        
        # Calculate percentage
        percent = int((completed_pages / total_pages) * 100) if total_pages > 0 else 0
        
        # Try to load combined result if completed
        result = None
        if status == "completed":
            try:
                result_data = await storage_service.get_file('combined_output.md', session_id)
                result = result_data.decode('utf-8')
            except FileNotFoundError:
                # Result not yet combined
                pass
        
        return {
            "job_id": job_id,
            "status": status,
            "progress": {
                "current_step": status,
                "message": message,
                "current_page": completed_pages + processing_pages,
                "total_pages": total_pages,
                "percent": percent
            },
            "created": processing_data.get('created_at'),
            "result": result,
            "error": None if failed_pages == 0 else f"{failed_pages} pages failed"
        }
        
    except FileNotFoundError:
        # Try status.json as fallback
        try:
            status_json = await storage_service.get_file('status.json', session_id)
            return json.loads(status_json)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Job not found")


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
        user_email = get_user_email_from_request(request, x_user_email)
        
        # Use persistent storage in cloud mode, memory in local mode
        if os.environ.get('RUNNING_IN_CLOUD') == 'true':
            # Cloud mode: persistent storage
            try:
                from app.storage_service import StorageService
                storage_service = StorageService(user_email=user_email)
                upload_session = ChunkedUploadSession(storage_service, upload_id)
                await upload_session.create(filename, total_size, total_chunks, user_email)
                logger.info(f"Created persistent upload session {upload_id} for {filename}")
            except Exception as e:
                logger.error(f"Failed to create persistent session {upload_id}: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to create upload session: {str(e)}")
        else:
            # Local mode: in-memory storage
            logger.info(f"Creating in-memory upload session {upload_id} for {filename}")
            chunked_job_uploads[upload_id] = {
                'filename': filename,
                'total_size': total_size,
                'total_chunks': total_chunks,
                'chunks_received': 0,
                'chunks': {},  # chunk_number -> data
                'created_at': datetime.utcnow().isoformat(),
                'user_email': user_email
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
async def upload_job_chunk(upload_id: str, file: UploadFile = File(...), request: Request = None):
    """Upload a chunk for job submission"""
    try:
        # Get chunk number from request headers (more robust extraction)
        chunk_number = None
        if request and hasattr(request, 'headers'):
            chunk_header = request.headers.get('x-chunk-number') or request.headers.get('X-Chunk-Number')
            if chunk_header:
                chunk_number = int(chunk_header)
        
        # Fallback to file headers if request headers don't work
        if chunk_number is None:
            chunk_header = file.headers.get('X-Chunk-Number') or file.headers.get('x-chunk-number')
            if chunk_header:
                chunk_number = int(chunk_header)
            else:
                chunk_number = 0  # Default fallback
        
        logger.info(f"Uploading chunk {chunk_number} for upload {upload_id}")
        
        # Read chunk data
        chunk_data = await file.read()
        logger.info(f"Read chunk data: {len(chunk_data)} bytes")
        
        # Handle both persistent and memory storage
        if os.environ.get('RUNNING_IN_CLOUD') == 'true':
            # Cloud mode: persistent storage
            logger.info(f"Using cloud mode persistent storage for upload {upload_id}")
            try:
                from app.storage_service import StorageService
                storage_service = StorageService()
                upload_session_manager = ChunkedUploadSession(storage_service, upload_id)
                
                logger.info(f"Created ChunkedUploadSession for {upload_id}")
                
                # Add chunk to persistent storage
                logger.info(f"About to call add_chunk for chunk {chunk_number}, upload {upload_id}")
                session_data, is_duplicate = await upload_session_manager.add_chunk(chunk_number, chunk_data)
                
                logger.info(f"add_chunk returned: duplicate={is_duplicate}, chunks_received={session_data['chunks_received']}")
                logger.info(f"add_chunk session chunks: {list(session_data['chunks'].keys())}")
                
            except Exception as e:
                logger.error(f"Error in cloud mode chunk upload for {upload_id}: {e}")
                raise
            
            if is_duplicate:
                logger.warning(f"Duplicate chunk {chunk_number} received for upload {upload_id}")
                return {
                    "upload_complete": False,
                    "chunks_received": session_data['chunks_received'],
                    "total_chunks": session_data['total_chunks'],
                    "message": f"Chunk {chunk_number} already received (duplicate)"
                }
            
            logger.info(f"Chunk {chunk_number} stored persistently. Progress: {session_data['chunks_received']}/{session_data['total_chunks']}")
            
            # Check if all chunks received
            logger.info(f"Checking if all chunks received: {session_data['chunks_received']} == {session_data['total_chunks']}")
            if session_data['chunks_received'] == session_data['total_chunks']:
                logger.info(f"All chunks received for upload {upload_id}. Reassembling file...")
                
                # Reassemble file from persistent storage without re-reading session
                try:
                    logger.info(f"About to reassemble chunks for upload {upload_id}")
                    complete_file_data = b''
                    for i in range(session_data['total_chunks']):
                        chunk_file = f"upload_chunks/{upload_id}/chunk_{i:04d}.bin"
                        chunk_data_bytes = await upload_session_manager.storage_service.get_file(chunk_file, '_upload_sessions')
                        complete_file_data += chunk_data_bytes
                    logger.info(f"File reassembly successful: {len(complete_file_data)} bytes")
                except Exception as e:
                    logger.error(f"Error in file reassembly: {e}")
                    raise
                
                # Cloud mode handles file processing directly without going through local mode logic
                # Determine job type from filename extension
                filename = session_data['filename']
                file_ext = filename.lower().split('.')[-1]
                
                if file_ext == 'pdf':
                    job_type = "pdf"
                elif file_ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'tif']:
                    job_type = "image"
                else:
                    raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_ext}. Supported: PDF, JPG, PNG, GIF, WEBP, BMP, TIFF")
                
                # Save uploaded file to storage first
                user_email = session_data.get('user_email')
                from app.storage_service import StorageService
                storage_service = StorageService(user_email=user_email)
                session_id = await storage_service.create_session()
                await storage_service.save_file(complete_file_data, filename, session_id)
                
                logger.info(f"File {filename} saved to session {session_id}. Processing file type: {job_type}")
                
                # Create file reference based on file type
                if job_type == "image":
                    # For images: check if slicing is needed for tall images
                    from PIL import Image
                    import io
                    
                    # Load image to check dimensions
                    image = Image.open(io.BytesIO(complete_file_data))
                    width, height = image.size
                    max_height = 1024
                    overlap = 100  # 100 pixel overlap between slices
                    
                    page_images = []
                    
                    if height > max_height:
                        logger.info(f"Image is {height}px tall, slicing into chunks with {overlap}px overlap")
                        
                        # Calculate number of slices needed
                        effective_height = max_height - overlap
                        num_slices = ((height - overlap) + effective_height - 1) // effective_height
                        
                        # Create slices with overlap
                        for slice_idx in range(num_slices):
                            if slice_idx == 0:
                                # First slice: from top to max_height
                                crop_top = 0
                                crop_bottom = max_height
                            elif slice_idx == num_slices - 1:
                                # Last slice: from (height - max_height) to bottom
                                crop_top = height - max_height
                                crop_bottom = height
                            else:
                                # Middle slices: with overlap on both sides
                                crop_top = slice_idx * effective_height
                                crop_bottom = crop_top + max_height
                            
                            # Ensure we don't go out of bounds
                            crop_top = max(0, crop_top)
                            crop_bottom = min(height, crop_bottom)
                            
                            # Create the slice
                            slice_image = image.crop((0, crop_top, width, crop_bottom))
                            slice_filename = f"page_{slice_idx + 1:03d}.png"
                            
                            # Save slice to storage
                            img_buffer = io.BytesIO()
                            slice_image.save(img_buffer, format='PNG')
                            slice_data = img_buffer.getvalue()
                            
                            await storage_service.save_file(slice_data, slice_filename, session_id)
                            page_images.append(slice_filename)
                            logger.info(f"Saved image slice {slice_idx + 1}/{num_slices} as {slice_filename} ({crop_top}-{crop_bottom}px)")
                        
                        page_count = num_slices
                        logger.info(f"Image sliced into {num_slices} parts for processing")
                    else:
                        # Normal sized image - save as is
                        image_filename = "page_001.png"
                        await storage_service.save_file(complete_file_data, image_filename, session_id)
                        page_images = [image_filename]
                        page_count = 1
                        logger.info(f"Image saved as {image_filename} ({width}x{height}px)")
                    
                    file_reference = {
                        "session_id": session_id,
                        "filename": filename,
                        "file_type": job_type,
                        "page_count": page_count,
                        "page_images": page_images
                    }
                    logger.info(f"Image file ready for immediate processing: {len(page_images)} parts")
                else:
                    # For PDFs: keep raw file reference for extraction
                    file_reference = {
                        "session_id": session_id,
                        "filename": filename,
                        "file_type": job_type,
                        "raw_file": filename
                    }
                    logger.info(f"PDF file ready for extraction: {filename}")
                
                # Submit job based on environment
                if os.environ.get('RUNNING_IN_CLOUD') == 'true':
                    # Cloud path: Create Cloud Task for batch processing
                    job_id = await create_cloud_processing_job(
                        storage_service, session_id, file_reference, user_email
                    )
                else:
                    # Local path: Use existing ThreadPoolExecutor - submit immediately
                    job_id = ocr_service.submit_job(file_reference, job_type=job_type, user_email=user_email, session_id=session_id)
                
                # Clean up upload session
                await upload_session_manager.cleanup()
                
                return {
                    "upload_complete": True,
                    "chunks_received": session_data['chunks_received'],
                    "total_chunks": session_data['total_chunks'],
                    "job_id": job_id,
                    "session_id": session_id,
                    "message": f"Upload complete, {job_type} processing started"
                }
                
            else:
                return {
                    "upload_complete": False,
                    "chunks_received": session_data['chunks_received'],
                    "total_chunks": session_data['total_chunks'],
                    "message": f"Chunk {chunk_number} received"
                }
                
        else:
            # Local mode: in-memory storage (existing behavior)
            if upload_id not in chunked_job_uploads:
                raise HTTPException(status_code=404, detail="Upload session not found")
            
            upload_session = chunked_job_uploads[upload_id]
            
            # Check for duplicate chunks (handle race conditions)
            if str(chunk_number) in upload_session['chunks']:
                logger.warning(f"Duplicate chunk {chunk_number} received for upload {upload_id}")
                return {
                    "upload_complete": False,
                    "chunks_received": upload_session['chunks_received'],
                    "total_chunks": upload_session['total_chunks'],
                    "message": f"Chunk {chunk_number} already received (duplicate)"
                }
            
            # Store chunk
            upload_session['chunks'][str(chunk_number)] = chunk_data
            upload_session['chunks_received'] += 1
            
            logger.info(f"Chunk {chunk_number} stored in memory. Progress: {upload_session['chunks_received']}/{upload_session['total_chunks']}")
            
            # Check if all chunks received
            if upload_session['chunks_received'] == upload_session['total_chunks']:
                logger.info(f"All chunks received for upload {upload_id}. Reassembling file...")
                
                # Reassemble file in correct order
                complete_file_data = b''
                missing_chunks = []
                
                for i in range(upload_session['total_chunks']):
                    if str(i) in upload_session['chunks']:
                        complete_file_data += upload_session['chunks'][str(i)]
                    else:
                        missing_chunks.append(i)
                
                if missing_chunks:
                    logger.error(f"Missing chunks for upload {upload_id}: {missing_chunks}")
                    logger.error(f"Received chunks: {sorted(upload_session['chunks'].keys())}")
                    raise HTTPException(status_code=400, detail=f"Missing chunks: {missing_chunks}")
                
                # Determine job type from filename extension
                filename = upload_session['filename']
                file_ext = filename.lower().split('.')[-1]
                
                if file_ext == 'pdf':
                    job_type = "pdf"
                elif file_ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'tif']:
                    job_type = "image"
                else:
                    raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_ext}. Supported: PDF, JPG, PNG, GIF, WEBP, BMP, TIFF")
                
                # Save uploaded file to storage first
                user_email = upload_session.get('user_email')
                from app.storage_service import StorageService
                storage_service = StorageService(user_email=user_email)
                session_id = await storage_service.create_session()
                await storage_service.save_file(complete_file_data, filename, session_id)
                
                logger.info(f"File {filename} saved to session {session_id}. Processing file type: {job_type}")
                
                # Create file reference based on file type
                if job_type == "image":
                    # For images: save as page_001 and create immediate page reference
                    image_filename = "page_001.png"
                    await storage_service.save_file(complete_file_data, image_filename, session_id)
                    
                    file_reference = {
                        "session_id": session_id,
                        "filename": filename,
                        "file_type": job_type,
                        "page_count": 1,
                        "page_images": [image_filename]
                    }
                    logger.info(f"Image file ready for immediate processing: {image_filename}")
                else:
                    # For PDFs: keep raw file reference for extraction
                    file_reference = {
                        "session_id": session_id,
                        "filename": filename,
                        "file_type": job_type,
                        "raw_file": filename
                    }
                    logger.info(f"PDF file ready for extraction: {filename}")
                
                # Local mode: Use existing ThreadPoolExecutor - submit immediately
                job_id = ocr_service.submit_job(file_reference, job_type=job_type, user_email=user_email, session_id=session_id)
                
                # Clean up upload session
                del chunked_job_uploads[upload_id]
                
                return {
                    "upload_complete": True,
                    "chunks_received": upload_session['chunks_received'],
                    "total_chunks": upload_session['total_chunks'],
                    "job_id": job_id,
                    "session_id": session_id,
                    "message": f"Upload complete, {job_type} processing started"
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
async def get_job_status(job_id: str, request: Request):
    """Get status and result of OCR job by ID - dual-path for cloud/local"""
    
    if os.environ.get('RUNNING_IN_CLOUD') == 'true':
        # Cloud path: Read from processing.json in storage
        try:
            # Try to find the session_id for this job_id
            session_id = await find_session_for_job(job_id)
            if not session_id:
                raise HTTPException(status_code=404, detail="Job not found")
            
            return await get_cloud_job_status(job_id, session_id)
            
        except FileNotFoundError:
            # Fall back to in-memory check for compatibility
            result = ocr_service.get_job_status(job_id)
            if result["status"] == "not_found":
                raise HTTPException(status_code=404, detail="Job not found")
            safe_result = {k: v for k, v in result.items() if k != "data"}
            return safe_result
    else:
        # Local path: Use existing in-memory job status
        result = ocr_service.get_job_status(job_id)
        if result["status"] == "not_found":
            raise HTTPException(status_code=404, detail="Job not found")
        
        # Remove binary data from response to prevent UnicodeDecodeError
        safe_result = {k: v for k, v in result.items() if k != "data"}
        return safe_result


@app.get("/job/{job_id}")
async def job_status_page(request: Request, job_id: str):
    """HTML page showing job status with auto-refresh"""
    job = ocr_service.get_job_status(job_id)
    if job["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Remove binary data and format result for template
    safe_job = {k: v for k, v in job.items() if k != "data"}
    if safe_job.get("result"):
        safe_job["result"] = format_job_result(safe_job["result"])
    
    return templates.TemplateResponse("job_status.html", {
        "request": request,
        "job": safe_job,
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
    
    # Remove binary data from job for template
    safe_job = {k: v for k, v in job.items() if k != "data"}
    
    return templates.TemplateResponse("job_result.html", {
        "request": request,
        "job": safe_job,
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

