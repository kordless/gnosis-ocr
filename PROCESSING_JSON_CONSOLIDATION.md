# Processing.json Consolidation Plan

## Overview
Consolidate all status tracking (status.json, metadata.json, and current processing.json) into a single, comprehensive processing.json file.

## New processing.json Structure

```json
{
  "job_id": "82ba48be-2daf-4a9a-91d8-0822b150897f",
  "session_id": "82ba48be-2daf-4a9a-91d8-0822b150897f",
  "status": "processing",
  "current_step": "extracting_images",
  "message": "Extracting page 3 of 10 from PDF...",
  "percent": 25,
  
  "file_info": {
    "filename": "paper33.pdf",
    "file_type": "pdf",
    "total_pages": 10,
    "raw_file": "paper33.pdf",
    "file_size": 356900
  },
  
  "user_email": "anonymous@gnosis-ocr.local",
  "created_at": "2025-07-15T23:12:19.184531",
  "updated_at": "2025-07-15T23:15:47.123456",
  
  "pages": {
    "1": {
      "status": "completed",
      "image": "page_001.png",
      "image_extracted_at": "2025-07-15T23:12:24.000000",
      "processing_started_at": "2025-07-15T23:12:27.432747",
      "processing_completed_at": "2025-07-15T23:12:49.000000",
      "result_file": "page_001_result.txt",
      "error": null
    }
  }
}
```

## Code Changes Required

### 1. ocr_service.py - Update submit_job()

Replace the current `submit_job()` method (around line 1000) with:

```python
def submit_job(self, file_reference, job_type="image", user_email=None, session_id=None):
    """Submit OCR job with file reference instead of binary data"""
    from datetime import datetime
    from app.storage_service import StorageService
    
    job_id = str(uuid.uuid4())
    
    # Create comprehensive job record
    job_data = {
        "job_id": job_id,
        "session_id": session_id or job_id,
        "status": "queued",
        "current_step": "queued",
        "message": "Job queued for processing",
        "percent": 0,
        
        "file_info": {
            "filename": file_reference.get("filename", "unknown"),
            "file_type": file_reference.get("file_type", job_type),
            "total_pages": file_reference.get("page_count", 1),
            "raw_file": file_reference.get("raw_file"),
            "file_size": file_reference.get("file_size", 0)
        },
        
        "user_email": user_email or "anonymous@gnosis-ocr.local",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        
        "pages": {},
        "file_reference": file_reference,  # Keep for backward compatibility
        "type": job_type
    }
    
    # Initialize page tracking if we have page images
    if "page_images" in file_reference:
        for i, image_file in enumerate(file_reference["page_images"], 1):
            job_data["pages"][str(i)] = {
                "status": "pending",
                "image": image_file,
                "image_extracted_at": datetime.utcnow().isoformat(),
                "processing_started_at": None,
                "processing_completed_at": None,
                "result_file": None,
                "error": None
            }
    
    self.jobs[job_id] = job_data
    
    # Persist to GCS if in cloud mode
    if os.environ.get('RUNNING_IN_CLOUD') == 'true':
        try:
            storage_service = StorageService(user_email=user_email)
            storage_service.force_cloud_mode()
            
            # Save processing.json
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(storage_service.save_file(
                    json.dumps(job_data, indent=2).encode('utf-8'),
                    'processing.json',
                    session_id or job_id
                ))
                logger.info(f"✅ Job {job_id} processing.json persisted to GCS")
            finally:
                loop.close()
                
        except Exception as e:
            logger.error(f"❌ Failed to persist processing.json for job {job_id}: {e}")
    
    # Queue or process based on model status
    if not self._model_loaded:
        if self._loading:
            self.job_queue.append(job_id)
            logger.info(f"📋 Job {job_id} queued - model still loading")
        else:
            if os.environ.get('RUNNING_IN_CLOUD') == 'true':
                logger.info(f"🔄 Starting model loading for cloud job {job_id}...")
                threading.Thread(target=self._background_load, daemon=True).start()
                self.job_queue.append(job_id)
    else:
        self.process_job_async(job_id)
        logger.info(f"🚀 Job {job_id} submitted for immediate processing")
    
    return job_id
```

### 2. ocr_service.py - Replace _update_job_status_gcs()

Replace the entire `_update_job_status_gcs()` method with:

```python
def _update_processing_status(self, job_id, updates):
    """Update processing.json with new status information
    
    Args:
        job_id: The job ID
        updates: Dictionary of fields to update in processing.json
    """
    try:
        from app.storage_service import StorageService
        from datetime import datetime
        
        job = self.jobs.get(job_id, {})
        
        # Update in-memory job data
        job.update(updates)
        job["updated_at"] = datetime.utcnow().isoformat()
        
        # Update in GCS
        if os.environ.get('RUNNING_IN_CLOUD') == 'true':
            user_email = job.get('user_email')
            session_id = job.get('session_id', job_id)
            
            storage_service = StorageService(user_email=user_email)
            storage_service.force_cloud_mode()
            
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                loop.run_until_complete(storage_service.save_file(
                    json.dumps(job, indent=2).encode('utf-8'),
                    'processing.json',
                    session_id
                ))
                logger.debug(f"📝 Updated processing.json for job {job_id}")
            finally:
                loop.close()
                
    except Exception as e:
        logger.error(f"❌ Failed to update processing.json for job {job_id}: {e}")
```

### 3. ocr_service.py - Update _extract_images_from_raw_file()

Update the image extraction method to properly update processing.json:

```python
def _extract_images_from_raw_file(self, raw_filename, session_id, file_type, job, job_id):
    """Extract images from raw PDF file in background thread"""
    try:
        from app.storage_service import StorageService
        storage_service = StorageService(user_email=job.get('user_email'))
        
        # Update status to extracting
        self._update_processing_status(job_id, {
            "status": "extracting",
            "current_step": "extracting_images",
            "message": "Loading PDF file...",
            "percent": 5
        })
        
        # Load raw file from storage
        raw_file_data = asyncio.run(storage_service.get_file(raw_filename, session_id))
        
        if file_type == "pdf":
            import pdf2image
            import io
            
            logger.info(f"Converting PDF to images for session {session_id}")
            
            # Update progress
            self._update_processing_status(job_id, {
                "message": "Converting PDF to images...",
                "percent": 10
            })
            
            # Convert PDF to images
            images = pdf2image.convert_from_bytes(
                raw_file_data,
                dpi=150,
                fmt='PNG',
                thread_count=2
            )
            
            page_count = len(images)
            logger.info(f"Extracted {page_count} pages from PDF")
            
            # Initialize page tracking
            pages = {}
            page_images = []
            
            for i, image in enumerate(images):
                current_page = i + 1
                image_filename = f"page_{current_page:03d}.png"
                
                # Update progress for this page
                progress = 10 + (current_page / page_count * 30)  # 10-40%
                self._update_processing_status(job_id, {
                    "current_step": "extracting_images",
                    "message": f"Saving page {current_page} of {page_count}...",
                    "percent": int(progress)
                })
                
                # Convert PIL image to bytes
                img_buffer = io.BytesIO()
                image.save(img_buffer, format='PNG')
                image_bytes = img_buffer.getvalue()
                
                # Save image to storage
                asyncio.run(storage_service.save_file(image_bytes, image_filename, session_id))
                page_images.append(image_filename)
                
                # Add page to tracking
                pages[str(current_page)] = {
                    "status": "pending",
                    "image": image_filename,
                    "image_extracted_at": datetime.utcnow().isoformat(),
                    "processing_started_at": None,
                    "processing_completed_at": None,
                    "result_file": None,
                    "error": None
                }
            
            # Update job with extracted pages
            self._update_processing_status(job_id, {
                "status": "queued",
                "current_step": "extraction_complete",
                "message": f"Extracted {page_count} pages, ready for OCR",
                "percent": 40,
                "pages": pages,
                "file_info": {
                    **job.get("file_info", {}),
                    "total_pages": page_count
                }
            })
            
            return page_images
            
        else:
            # For single images
            image_filename = "page_001.png"
            asyncio.run(storage_service.save_file(raw_file_data, image_filename, session_id))
            
            self._update_processing_status(job_id, {
                "status": "queued",
                "current_step": "extraction_complete",
                "message": "Image ready for OCR",
                "percent": 40,
                "pages": {
                    "1": {
                        "status": "pending",
                        "image": image_filename,
                        "image_extracted_at": datetime.utcnow().isoformat(),
                        "processing_started_at": None,
                        "processing_completed_at": None,
                        "result_file": None,
                        "error": None
                    }
                }
            })
            
            return [image_filename]
            
    except Exception as e:
        logger.error(f"Failed to extract images from {raw_filename}: {e}")
        self._update_processing_status(job_id, {
            "status": "failed",
            "current_step": "extraction_failed",
            "message": f"Failed to extract images: {str(e)}",
            "percent": 0
        })
        raise
```

### 4. ocr_service.py - Update process_job_async()

Update the main processing loop to properly track page-by-page progress:

```python
# In process_job_async(), replace the PDF processing section with:

elif job['type'] == "pdf":
    # PDF processing with detailed status updates
    total_pages = len(page_images)
    
    self._update_processing_status(job_id, {
        "status": "processing",
        "current_step": "ocr_processing",
        "message": f"Starting OCR on {total_pages} pages...",
        "percent": 40
    })
    
    logger.info(f"Loading {total_pages} pre-extracted images from storage")
    
    result = []
    from PIL import Image
    import io
    
    for i, image_filename in enumerate(page_images):
        current_page = i + 1
        
        # Update page status to processing
        job['pages'][str(current_page)]['status'] = 'processing'
        job['pages'][str(current_page)]['processing_started_at'] = datetime.utcnow().isoformat()
        
        # Calculate progress (40-90% range for OCR)
        percent = 40 + int((current_page - 1) / total_pages * 50)
        
        self._update_processing_status(job_id, {
            "current_step": "ocr_processing",
            "message": f"Processing page {current_page} of {total_pages}...",
            "percent": percent,
            "pages": job['pages']
        })
        
        logger.info(f"🔍 Processing page {current_page}/{total_pages} - {image_filename}")
        
        try:
            # Load image from storage
            image_data = asyncio.run(storage_service.get_file(image_filename, session_id))
            image = Image.open(io.BytesIO(image_data))
            
            # Process the loaded image
            page_result = self.process_image(image)
            page_result["page_number"] = current_page
            result.append(page_result)
            
            # Save the result
            text_content = page_result.get('text', '')
            result_filename = f"page_{current_page:03d}_result.txt"
            
            # Save to storage
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(storage_service.save_file(
                    text_content.encode('utf-8'),
                    result_filename,
                    session_id
                ))
            finally:
                loop.close()
            
            # Update page status to completed
            job['pages'][str(current_page)]['status'] = 'completed'
            job['pages'][str(current_page)]['processing_completed_at'] = datetime.utcnow().isoformat()
            job['pages'][str(current_page)]['result_file'] = result_filename
            
            # Update processing.json with page completion
            self._update_processing_status(job_id, {
                "pages": job['pages'],
                "message": f"Completed page {current_page} of {total_pages}",
                "percent": 40 + int(current_page / total_pages * 50)
            })
            
            # Clear GPU memory after each page
            if self.device.type == "cuda":
                torch.cuda.empty_cache()
                
        except Exception as e:
            logger.error(f"Failed to process page {current_page}: {e}")
            job['pages'][str(current_page)]['status'] = 'failed'
            job['pages'][str(current_page)]['error'] = str(e)
            
            self._update_processing_status(job_id, {
                "pages": job['pages']
            })
```

### 5. ocr_service.py - Update get_job_status()

Replace get_job_status to read from processing.json:

```python
def get_job_status(self, job_id):
    """Get job result by ID - check memory first, then GCS processing.json"""
    # First check in-memory jobs
    if job_id in self.jobs:
        return self.jobs[job_id]
    
    # If not in memory, try to load from GCS (container restart recovery)
    try:
        from app.storage_service import StorageService
        
        storage_service = StorageService(user_email=None)
        if os.environ.get('RUNNING_IN_CLOUD') == 'true':
            storage_service.force_cloud_mode()
        
        # Try to get processing.json
        try:
            loop = asyncio.get_event_loop()
            processing_content = loop.run_until_complete(
                storage_service.get_file('processing.json', job_id)
            )
        except RuntimeError:
            # No event loop, create a new one
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                processing_content = loop.run_until_complete(
                    storage_service.get_file('processing.json', job_id)
                )
            finally:
                loop.close()
        
        if processing_content:
            job_data = json.loads(processing_content.decode('utf-8'))
            logger.info(f"🔄 Recovered job {job_id} from GCS: {job_data.get('status')}")
            
            # Cache it in memory for future requests
            self.jobs[job_id] = job_data
            return job_data
            
    except Exception as e:
        logger.debug(f"Could not recover job {job_id} from GCS: {e}")
    
    # Not found anywhere
    return {"status": "not_found", "error": "Job not found"}
```

### 6. Update all calls to _update_job_status_gcs()

Search and replace all calls to `_update_job_status_gcs()` with appropriate `_update_processing_status()` calls:

```python
# Replace calls like:
self._update_job_status_gcs(job_id, 'processing', 'Starting OCR processing...')

# With:
self._update_processing_status(job_id, {
    "status": "processing",
    "current_step": "ocr_processing", 
    "message": "Starting OCR processing..."
})
```

## Frontend API Changes

The frontend will need to poll `/api/jobs/{job_id}/status` which should now return the complete processing.json structure. This gives the frontend access to:
- Overall progress percentage
- Current step and message
- Individual page statuses
- File information
- Error details if any

## Testing Checklist

1. [ ] Single image upload creates proper processing.json
2. [ ] PDF upload shows extraction progress in processing.json
3. [ ] Each page completion updates processing.json
4. [ ] Frontend can display extraction vs OCR progress
5. [ ] Container restart can recover from processing.json
6. [ ] No more status.json or metadata.json files created
