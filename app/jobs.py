"""
Job management system with cloud/local abstraction for gnosis-ocr-s
'Fire-and-forget' version with no individual job status files.
"""
import os
import json
import uuid
import asyncio
import logging
from enum import Enum
from datetime import datetime
from typing import Optional, Dict, List, Any
from concurrent.futures import ThreadPoolExecutor
import threading

import pdf2image
from PIL import Image
import io

from app.storage_service import StorageService

logger = logging.getLogger(__name__)


# Cloud Tasks client (lazy initialization)
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


class JobType(Enum):
    """Types of jobs that can be created"""
    EXTRACT_PAGES = "extract_pages"
    OCR = "ocr"
    SLICE_IMAGE = "slice_image"


class JobManager:
    """Manages submitting jobs to a queue without tracking their individual state in files."""

    def __init__(self, storage_service: StorageService):
        self.storage_service = storage_service
        self._is_cloud = os.environ.get('RUNNING_IN_CLOUD') == 'true'
        self._metadata_lock = asyncio.Lock()

        if not self._is_cloud:
            self.executor = ThreadPoolExecutor(max_workers=os.cpu_count() or 2)
            logger.info("JobManager initialized in LOCAL mode with ThreadPoolExecutor")
        else:
            self.executor = None
            logger.info("JobManager initialized in CLOUD mode with Cloud Tasks")

    async def create_job(
        self,
        session_id: str,
        job_type: JobType,
        input_data: Dict[str, Any],
        user_email: Optional[str] = None,
    ) -> str:
        """Creates a job by submitting it directly to the queue."""
        job_id = str(uuid.uuid4())

        # The only state saved is a reference in metadata.json
        async with self._metadata_lock:
            try:
                metadata_bytes = await self.storage_service.get_file('metadata.json', session_id)
                metadata = json.loads(metadata_bytes.decode('utf-8'))
            except FileNotFoundError:
                metadata = { "session_id": session_id, "created_at": datetime.utcnow().isoformat(), "jobs": [] }
            
            # This handles the case where metadata.json exists but has no jobs yet.
            if "jobs" not in metadata:
                metadata["jobs"] = []

            metadata["jobs"].append({
                "job_id": job_id, "job_type": job_type.value, "created_at": datetime.utcnow().isoformat()
            })

            await self.storage_service.save_file(
                json.dumps(metadata, indent=2), 'metadata.json', session_id
            )

        logger.info(f"Submitting job {job_id} of type {job_type.value} for session {session_id}")

        # The full job details must now be passed directly to the worker.
        job_payload = {
            "job_id": job_id,
            "session_id": session_id,
            "job_type": job_type,
            "input_data": input_data,
            "user_email": user_email
        }
        
        if self._is_cloud:
            await self._create_cloud_task(job_payload)
        else:
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(
                self.executor, self._process_job_local_sync_wrapper, job_payload
            )
            # Add a callback to handle completion and prevent the event loop error
            def handle_completion(fut):
                try:
                    result = fut.result()  # This will raise any exceptions that occurred
                    logger.info(f"Job completed - ID: {result['job_id']}, Type: {result['job_type']}, Status: {result['status']}, Message: {result['message']}")
                except Exception as e:
                    logger.error(f"Job {job_id} callback error: {e}")
            
            future.add_done_callback(handle_completion)
            logger.info(f"Job {job_id} submitted to ThreadPoolExecutor for local processing")

        return job_id

    def _process_job_local_sync_wrapper(self, job_payload: Dict) -> Dict:
        """Synchronous wrapper to run async job processing in a separate thread."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        job_id = job_payload.get("job_id")
        job_type = job_payload.get("job_type")
        session_id = job_payload.get("session_id")
        
        user_email = job_payload.get("user_email")
        thread_storage_service = StorageService(user_email=user_email)
        thread_job_manager = JobManager(thread_storage_service)
        processor = JobProcessor(thread_job_manager, thread_storage_service)
        
        result = {
            "job_id": job_id,
            "job_type": job_type.value if hasattr(job_type, 'value') else str(job_type),
            "session_id": session_id,
            "status": "failed",
            "message": "Unknown error"
        }
        
        try:
            loop.run_until_complete(processor.process_job(job_payload))
            result["status"] = "completed"
            result["message"] = f"Job {job_type.value if hasattr(job_type, 'value') else job_type} completed successfully"
        except Exception as e:
            logger.error(f"Error processing job in background thread: {e}", exc_info=True)
            result["message"] = str(e)
        finally:
            loop.close()
            
        return result

    async def _create_cloud_task(self, job_payload: Dict):
        """Create a Cloud Task for job processing."""
        client = get_cloud_tasks_client()
        if not client:
            logger.error("Cloud Tasks client not available.")
            return

        try:
            project = os.environ.get('GOOGLE_CLOUD_PROJECT', '')
            location = os.environ.get('CLOUD_TASKS_LOCATION', 'us-central1')
            queue = os.environ.get('CLOUD_TASKS_QUEUE', 'job-processing')
            worker_url = os.environ.get('WORKER_SERVICE_URL', '')
            if not all([project, location, queue, worker_url]):
                logger.error("Cloud Tasks environment variables not fully configured.")
                return

            parent = client.queue_path(project, location, queue)
            
            # Convert Enum to string for JSON serialization
            job_payload['job_type'] = job_payload['job_type'].value
            
            task = { 
                "http_request": { 
                    "http_method": "POST", 
                    "url": f"{worker_url}/worker/process-job", 
                    "headers": {"Content-Type": "application/json"}, 
                    "body": json.dumps(job_payload).encode('utf-8') 
                },
                "dispatch_deadline": "600s"  # 10 minutes timeout
            }
            
            input_data = job_payload.get("input_data", {})
            if input_data.get('start_page', 1) > 1:
                from google.protobuf import timestamp_pb2
                import time
                schedule_time = timestamp_pb2.Timestamp()
                schedule_time.FromSeconds(int(time.time()) + 5)
                task['schedule_time'] = schedule_time

            response = client.create_task(parent=parent, task=task)
            logger.info(f"Created Cloud Task {response.name} for job {job_payload['job_id']}")

        except Exception as e:
            logger.error(f"Failed to create Cloud Task for job {job_payload['job_id']}: {e}", exc_info=True)

    async def scan_and_build_status(self, session_id: str, total_pages: int = None) -> Dict:
        """Scans storage directories and builds status based on actual files present."""
        status_data = {
            "session_id": session_id,
            "stages": {},
            "updated_at": datetime.utcnow().isoformat()
        }
        
        # Count extracted page files
        pages_extracted = 0
        try:
            files = await self.storage_service.list_files(session_id)
            # Count PNG files in pages/ directory
            page_files = [f for f in files if f.startswith("pages/page_") and f.endswith(".png")]
            pages_extracted = len(page_files)
        except Exception as e:
            logger.debug(f"Error listing page files for {session_id}: {e}")
        
        # Count OCR result files
        ocr_completed = 0
        try:
            files = await self.storage_service.list_files(session_id)
            # Count TXT files in results/ directory
            result_files = [f for f in files if f.startswith("results/page_") and f.endswith(".txt")]
            ocr_completed = len(result_files)
        except Exception as e:
            logger.debug(f"Error listing result files for {session_id}: {e}")
        
        # Build page extraction stage
        if pages_extracted > 0 or total_pages:
            actual_total = total_pages or pages_extracted
            extraction_complete = pages_extracted == actual_total and actual_total > 0
            
            status_data["stages"]["page_extraction"] = {
                "status": "complete" if extraction_complete else "processing",
                "total_pages": actual_total,
                "pages_processed": pages_extracted,
                "progress_percent": round((pages_extracted / actual_total * 100)) if actual_total > 0 else 0
            }
        
        # Build OCR stage (only if we have pages)
        if ocr_completed > 0 or (pages_extracted > 0 and total_pages):
            ocr_total = total_pages or pages_extracted
            ocr_complete = ocr_completed == ocr_total and ocr_total > 0
            
            status_data["stages"]["ocr"] = {
                "status": "complete" if ocr_complete else "processing",
                "total_pages": ocr_total,
                "pages_processed": ocr_completed,
                "progress_percent": round((ocr_completed / ocr_total * 100)) if ocr_total > 0 else 0
            }
        
        return status_data

    async def update_session_status(self, session_id: str, stage_name: str = None, pages_processed: int = None, total_pages: int = None):
        """Updates session status by scanning directories and saving the result."""
        status_filename = "session_status.json"
        logger.info(f"Updating session status for {session_id} in {status_filename} with {total_pages} total pages and {pages_processed} processed pages.")
        # Build status from actual files
        status_data = await self.scan_and_build_status(session_id, total_pages)
        logger.info(f"Building status for session {session_id}: {status_data}")

        # Save the status file
        await self.storage_service.save_file(
            json.dumps(status_data, indent=2), status_filename, session_id
        )
        
        logger.debug(f"Updated session status for {session_id}: {status_data}")

    async def get_session_status(self, session_id: str) -> Optional[Dict]:
        """Retrieves the overall session status from its JSON file."""
        status_filename = "session_status.json"
        try:
            status_bytes = await self.storage_service.get_file(status_filename, session_id)
            return json.loads(status_bytes.decode('utf-8'))
        except FileNotFoundError:
            return None
        

class JobProcessor:
    """Processes jobs by executing their logic."""

    def __init__(self, job_manager: JobManager, storage_service: StorageService):
        self.job_manager = job_manager
        self.storage_service = storage_service

    async def process_job(self, job_payload: Dict):
        """Process a job using the details passed in the payload."""
        job_id = job_payload.get("job_id")
        job_type = job_payload.get("job_type")
        
        try:
            logger.info(f"Worker started processing job {job_id}")
            
            # Ensure job_type is an Enum member
            if not isinstance(job_type, JobType):
                job_type = JobType(job_type)

            if job_type == JobType.EXTRACT_PAGES:
                await self._handle_extract_pages(job_payload)
            elif job_type == JobType.OCR:
                await self._handle_ocr(job_payload)
            else:
                raise ValueError(f"Unknown job type: {job_type}")
            
            logger.info(f"Worker finished processing job {job_id}")

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)

    async def _handle_extract_pages(self, job_payload: dict):
        """Handles the logic for the EXTRACT_PAGES job type, including continuation."""
        session_id = job_payload["session_id"]
        
        # Create a progress callback that logs updates AND triggers status file update
        async def update_status_callback(status: str, message: str, percent: int):
            logger.info(f"PDF Extract Progress - Job {job_payload['job_id']}: {status} - {message} ({percent}%)")
            # Update session status file when progress changes
            if status in ["processing", "completed"]:
                await self.job_manager.update_session_status(session_id)
        
        # We need to wrap the async callback for the sync context
        def log_progress(status: str, message: str, percent: int):
            logger.info(f"PDF Extract Progress - Job {job_payload['job_id']}: {status} - {message} ({percent}%)")
            # Only update status on significant progress, not every callback
            if status == "completed" or (status == "processing" and percent >= 100):
                asyncio.create_task(update_status_callback(status, message, percent))
        
        result = await self._process_extract_pages_batch(job_payload, log_progress)

        if result["end_page"] < result["total_pages"]:
            # More pages remain, create and submit a continuation job
            await self.job_manager.create_job(
                session_id=job_payload["session_id"],
                job_type=JobType.EXTRACT_PAGES,
                input_data={ "filename": result["filename"], "start_page": result["end_page"] + 1 },
                user_email=job_payload.get("user_email")
            )
        else:
            logger.info(f"Successfully extracted all {result['total_pages']} pages for {result['filename']}.")
            # Final status update when all extraction is complete
            # Small delay to ensure all file operations are complete
            await asyncio.sleep(0.1)
            await self.job_manager.update_session_status(session_id, total_pages=result['total_pages'])

    async def _process_extract_pages_batch(self, job_payload: Dict, progress_callback=None) -> Dict:
        """Extracts a single batch of pages from a PDF."""
        session_id = job_payload["session_id"]
        input_data = job_payload["input_data"]
        filename = input_data["filename"]
        start_page = input_data.get("start_page", 1)

        if progress_callback:
            progress_callback("loading", f"Loading PDF file {filename}...", 0)

        pdf_data = await self.storage_service.get_file(filename, session_id)
        pdf_info = await asyncio.to_thread(pdf2image.pdfinfo_from_bytes, pdf_data)

        total_pages = pdf_info['Pages']
        end_page = min(start_page + 9, total_pages)

        logger.info(f"Job {job_payload['job_id']}: Processing pages {start_page}-{end_page} of {total_pages}")

        # Use callback for conversion start
        if progress_callback:
            progress_callback("processing", f"Converting PDF pages {start_page}-{end_page} to images...", 10)
        
        images = await asyncio.to_thread(
            pdf2image.convert_from_bytes,
            pdf_data, dpi=150, fmt='PNG',
            first_page=start_page, last_page=end_page, thread_count=2
        )
        
        if progress_callback:
            progress_callback("processing", f"Converted {len(images)} pages, now saving...", 50)

        for i, image in enumerate(images):
            page_num = start_page + i
            page_filename = f"pages/page_{page_num:03d}.png"
            
            with io.BytesIO() as img_buffer:
                image.save(img_buffer, format='PNG')
                await self.storage_service.save_file(img_buffer.getvalue(), page_filename, session_id)
            image.close()
            
            # Calculate progress AFTER saving the file
            save_progress = 50 + int(((i + 1) / len(images)) * 50)  # 50-100% range for saving
            if progress_callback:
                progress_callback("processing", f"Saved page {page_num} of {end_page}...", save_progress)
        
        if progress_callback:
            progress_callback("completed", f"Completed batch {start_page}-{end_page}", 100)

        return {
            "start_page": start_page, "end_page": end_page,
            "total_pages": total_pages, "filename": filename
        }


    async def _handle_ocr(self, job_payload: dict):
        """
        Handles an OCR job for a BATCH of pages and creates a continuation job if more pages remain.
        """
        # Lazy import to avoid startup issues
        from app.ocr_service import ocr_service
        
        session_id = job_payload["session_id"]
        input_data = job_payload["input_data"]
        total_pages = input_data.get("total_pages")
        start_page = input_data.get("start_page", 1)
    
        if not total_pages:
            raise ValueError("Missing 'total_pages' in input_data for OCR job")

        # 1. Define the batch size for this single job instance.
        # This can be adjusted based on the memory of your cloud instances.
        OCR_BATCH_SIZE = 5
        end_page = min(start_page + OCR_BATCH_SIZE - 1, total_pages)
        page_numbers_in_batch = range(start_page, end_page + 1)

        logger.info(f"Starting OCR job for pages {start_page}-{end_page} of {total_pages} in session {session_id}")

        # 2. Concurrently load ONLY the images for the current batch from storage.
        async def load_image(page_num):
            filename = f"pages/page_{page_num:03d}.png"
            try:
                image_bytes = await self.storage_service.get_file(filename, session_id)
                return (page_num, Image.open(io.BytesIO(image_bytes)))
            except FileNotFoundError:
                logger.error(f"Could not find image file for page {page_num}: {filename}")
                return (page_num, None)

        load_tasks = [load_image(p) for p in page_numbers_in_batch]
        loaded_images = await asyncio.gather(*load_tasks)
        
        valid_images = {pn: img for pn, img in loaded_images if img is not None}
        
        # 3. Process the batch of images.
        loop = asyncio.get_running_loop()
        
        # Create a progress callback that logs updates AND triggers status file update
        async def update_status_callback(status: str, message: str, percent: int):
            logger.info(f"OCR Progress - Job {job_payload['job_id']}: {status} - {message} ({percent}%)")
            # Update session status file when progress changes
            if status in ["processing", "completed"]:
                await self.job_manager.update_session_status(session_id, total_pages=total_pages)
        
        def log_progress(status: str, message: str, percent: int):
            logger.info(f"OCR Progress - Job {job_payload['job_id']}: {status} - {message} ({percent}%)")
            # Only update status on significant progress
            if status == "completed" or (status == "processing" and percent >= 100):
                asyncio.create_task(update_status_callback(status, message, percent))
        
        # The run_ocr_on_batch method is efficient for both cloud (GPU) and local (CPU)
        ocr_results_list = await loop.run_in_executor(
            None, ocr_service.run_ocr_on_batch, list(valid_images.values()), log_progress
        )
        
        # Map results back to their page numbers
        all_results = {}
        page_keys = list(valid_images.keys())
        for i, ocr_result in enumerate(ocr_results_list):
            page_num = page_keys[i]
            all_results[page_num] = ocr_result["text"]

        # 4. Concurrently save all text results for this batch.
        async def save_result(page_num, text_content):
            result_filename = f"results/page_{page_num:03d}.txt"
            await self.storage_service.save_file(text_content, result_filename, session_id)

        save_tasks = [save_result(pn, txt) for pn, txt in all_results.items()]
        await asyncio.gather(*save_tasks)
        logger.info(f"Saved {len(all_results)} OCR result files for pages {start_page}-{end_page}.")
        
        # Update status after saving all results
        await self.job_manager.update_session_status(session_id, total_pages=total_pages)

        # 6. --- The Chaining Logic ---
        if end_page < total_pages:
            # If more pages remain, create a continuation job for the next batch.
            logger.info(f"Pages {start_page}-{end_page} complete. Creating continuation job.")
            await self.job_manager.create_job(
                session_id=session_id,
                job_type=JobType.OCR,
                input_data={
                    "total_pages": total_pages,
                    "start_page": end_page + 1  # Start the next job where this one left off
                },
                user_email=job_payload.get("user_email")
            )
        else:
            # This was the final batch.
            logger.info(f"All {total_pages} pages have been processed for OCR.")
            # Optionally, you could trigger a final "combine results" job here.