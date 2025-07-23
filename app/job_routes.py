"""Job API routes for gnosis-ocr-s"""
from fastapi import APIRouter, HTTPException, Request, Depends
from typing import Optional, List
from pydantic import BaseModel
import logging
import json

from app.jobs import JobType, JobManager
from app.storage_service import StorageService
from app.uploader import get_user_email_from_request

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# --- Request/Response Models ---

class CreateJobRequest(BaseModel):
    session_id: str
    job_type: str
    input_data: dict = {}

class CreateJobResponse(BaseModel):
    job_id: str
    session_id: str
    message: str

class StageStatus(BaseModel):
    status: str
    total_pages: int
    pages_processed: int
    progress_percent: int

class SessionStatusResponse(BaseModel):
    session_id: str
    stages: dict[str, StageStatus]
    updated_at: str


# --- Dependencies ---

async def get_storage_service(request: Request) -> StorageService:
    user_email = get_user_email_from_request(request)
    return StorageService(user_email=user_email)


# --- API Endpoints ---

@router.post("/create", response_model=CreateJobResponse)
async def create_job(
    request: CreateJobRequest,
    req: Request,
    storage_service: StorageService = Depends(get_storage_service)
):
    """Submits a new job to the queue."""
    try:
        try:
            job_type = JobType(request.job_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid job type: {request.job_type}"
            )
        
        user_email = get_user_email_from_request(req)
        job_manager = JobManager(storage_service)
        
        job_id = await job_manager.create_job(
            session_id=request.session_id,
            job_type=job_type,
            input_data=request.input_data,
            user_email=user_email
        )
        
        return CreateJobResponse(
            job_id=job_id,
            session_id=request.session_id,
            message="Job submitted successfully."
        )
        
    except Exception as e:
        logger.error(f"Error creating job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_id}/status")
async def get_session_status(
    session_id: str,
    storage_service: StorageService = Depends(get_storage_service)
):
    """Gets the overall progress status for a session."""
    try:
        # This method reads the 'session_status.json' file
        status_data = await JobManager(storage_service).get_session_status(session_id)
        if not status_data:
            raise HTTPException(status_code=404, detail="Session status not found.")
        
        # Return the raw status data which includes the stages
        return status_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/rebuild-status")
async def rebuild_session_status(
    session_id: str,
    storage_service: StorageService = Depends(get_storage_service)
):
    """Rebuild session status by scanning actual files in storage"""
    try:
        from app.jobs import JobManager
        job_manager = JobManager(storage_service)
        
        # Scan directories and rebuild status
        status = await job_manager.scan_and_build_status(session_id)
        
        # Save the rebuilt status
        await job_manager.update_session_status(session_id)
        
        logger.info(f"Rebuilt session status for {session_id}")
        return {
            "session_id": session_id,
            "status": "rebuilt",
            "message": "Session status has been rebuilt from actual files",
            "data": status
        }
    except Exception as e:
        logger.error(f"Error rebuilding session status for {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to rebuild session status: {str(e)}")
