diff --git a/app/main.py b/app/main.py
index 21502ae..3dee88d 100644
--- a/app/main.py
+++ b/app/main.py
@@ -344,30 +344,6 @@ async def combine_results(storage_service: StorageService, session_id: str, proc
     logger.info(f"Combined results for {len(sorted_pages)} pages saved to combined_output.md")
 
 
-async def update_status(storage_service: StorageService, session_id: str, status: str) -> None:
-    """Update the overall job status"""
-    try:
-        # Try to load existing status.json
-        status_json = await storage_service.get_file('status.json', session_id)
-        status_data = json.loads(status_json)
-    except FileNotFoundError:
-        # Create basic status if not found
-        status_data = {
-            "status": "unknown",
-            "progress": {"percent": 0},
-            "created": datetime.utcnow().isoformat()
-        }
-    
-    # Update status
-    status_data["status"] = status
-    status_data["updated"] = datetime.utcnow().isoformat()
-    
-    if status == "completed":
-        status_data["progress"]["percent"] = 100
-        status_data["progress"]["message"] = "All pages processed successfully"
-    
-    # Save updated status
-    await storage_service.save_file(json.dumps(status_data, indent=2), "status.json", session_id)
 
 
 @app.post("/process-ocr-batch")
@@ -474,8 +450,7 @@ async def process_ocr_batch(request: ProcessBatchRequest):
             # Combine results into final output
             await combine_results(storage_service, request.session_id, processing_data)
             
-            # Update overall status to completed
-            await update_status(storage_service, request.session_id, 'completed')
+            # Overall status is now handled by OCR service processing.json
             
             return {
                 "status": "job_completed",
@@ -623,7 +598,7 @@ async def create_cloud_processing_job(storage_service, session_id: str, file_ref
         status = "extracting"  # Initial status for raw file processing
     else:
         total_pages = file_reference.get("page_count", 1)
-        status = "queued"
+        status = "pending"
     
     # Create processing.json structure as per PLAN 2B
     processing_data = {
@@ -664,24 +639,7 @@ async def create_cloud_processing_job(storage_service, session_id: str, file_ref
     processing_json = json.dumps(processing_data, indent=2)
     await storage_service.save_file(processing_json, "processing.json", session_id)
     
-    # Create status.json for compatibility with existing status checks
-    status_data = {
-        "job_id": job_id,
-        "status": "queued",
-        "progress": {
-            "current_step": "queued",
-            "message": "Job queued for cloud processing",
-            "current_page": 0,
-            "total_pages": file_reference.get("page_count", 1),
-            "percent": 0
-        },
-        "created": datetime.utcnow().isoformat(),
-        "result": None,
-        "error": None
-    }
-    
-    status_json = json.dumps(status_data, indent=2)
-    await storage_service.save_file(status_json, "status.json", session_id)
+    # All status information now consolidated in processing.json
     
     logger.info(f"Created cloud processing job {job_id} with {file_reference.get('page_count', 1)} pages")
     
@@ -741,7 +699,7 @@ async def extract_pdf_pages(storage_service, session_id: str, processing_data: d
     
     # Update total pages and status
     processing_data['total_pages'] = len(images)
-    processing_data['status'] = 'queued'  # Ready for processing
+    processing_data['status'] = 'pending'  # Ready for processing
     processing_data['updated_at'] = datetime.utcnow().isoformat()
     
     # Update file_reference to indicate extraction is complete
@@ -802,7 +760,7 @@ async def get_cloud_job_status(job_id: str, session_id: str) -> dict:
             status = "processing"
             message = f"Processing page {completed_pages + processing_pages} of {total_pages}"
         else:
-            status = "queued"
+            status = "pending"
             message = "Waiting for processing to start"
         
         # Calculate percentage
@@ -834,12 +792,7 @@ async def get_cloud_job_status(job_id: str, session_id: str) -> dict:
         }
         
     except FileNotFoundError:
-        # Try status.json as fallback
-        try:
-            status_json = await storage_service.get_file('status.json', session_id)
-            return json.loads(status_json)
-        except FileNotFoundError:
-            raise HTTPException(status_code=404, detail="Job not found")
+        raise HTTPException(status_code=404, detail="Job not found")
 
 
 @app.post("/api/v1/jobs/submit/start")
@@ -996,7 +949,7 @@ async def upload_job_chunk(upload_id: str, file: UploadFile = File(...), request
                 user_email = session_data.get('user_email')
                 from app.storage_service import StorageService
                 storage_service = StorageService(user_email=user_email)
-                session_id = await storage_service.create_session()
+                session_id = upload_id  # Use the upload session ID instead of creating new one
                 await storage_service.save_file(complete_file_data, filename, session_id)
                 
                 logger.info(f"File {filename} saved to session {session_id}. Processing file type: {job_type}")
@@ -1175,7 +1128,7 @@ async def upload_job_chunk(upload_id: str, file: UploadFile = File(...), request
                 user_email = upload_session.get('user_email')
                 from app.storage_service import StorageService
                 storage_service = StorageService(user_email=user_email)
-                session_id = await storage_service.create_session()
+                session_id = upload_id  # Use the upload session ID instead of creating new one
                 await storage_service.save_file(complete_file_data, filename, session_id)
                 
                 logger.info(f"File {filename} saved to session {session_id}. Processing file type: {job_type}")
@@ -1401,27 +1354,21 @@ async def get_status(
     # Just assume the session exists and try to read files directly
     
     try:
-        # Get status file
-        logger.debug("Attempting to get status file", session_hash=session_hash)
-        status_content = await storage_service.get_file('status.json', session_hash)
-        status = json.loads(status_content)
-        logger.debug("Status file loaded", session_hash=session_hash, status=status)
-        
-        # Get metadata
-        logger.debug("Attempting to get metadata file", session_hash=session_hash)
-        metadata_content = await storage_service.get_file('metadata.json', session_hash)
-        metadata = json.loads(metadata_content)
-        logger.debug("Metadata file loaded", session_hash=session_hash, metadata=metadata)
+        # Get processing.json (consolidated status and metadata)
+        logger.debug("Attempting to get processing file", session_hash=session_hash)
+        processing_content = await storage_service.get_file('processing.json', session_hash)
+        processing_data = json.loads(processing_content)
+        logger.debug("Processing file loaded", session_hash=session_hash, status=processing_data.get('status'))
         
         result = SessionStatus(
             session_hash=session_hash,
-            status=ProcessingStatus(status.get('status', ProcessingStatus.PENDING.value)),
-            progress=status.get('progress', 0.0),
-            current_page=status.get('current_page'),
-            total_pages=metadata.get('total_pages', 0),
-            message=status.get('message'),
-            started_at=datetime.fromisoformat(metadata.get('created_at', datetime.utcnow().isoformat())),
-            completed_at=datetime.fromisoformat(status['updated_at']) if status.get('status') == 'completed' else None,
+            status=ProcessingStatus(processing_data.get('status', ProcessingStatus.PENDING.value)),
+            progress=processing_data.get('percent', 0.0),
+            current_page=len([p for p in processing_data.get('pages', {}).values() if p.get('status') == 'completed']),
+            total_pages=processing_data.get('file_info', {}).get('total_pages', 0),
+            message=processing_data.get('message'),
+            started_at=datetime.fromisoformat(processing_data.get('created_at', datetime.utcnow().isoformat())),
+            completed_at=datetime.fromisoformat(processing_data['updated_at']) if processing_data.get('status') == 'completed' else None,
             processing_time=None  # Could calculate from timestamps
         )
         
@@ -1493,23 +1440,19 @@ async def get_results(
 
     
     try:
-        # Check session status
-        status_content = await storage_service.get_file('status.json', session_hash)
-        status = json.loads(status_content)
+        # Check session status from processing.json
+        processing_content = await storage_service.get_file('processing.json', session_hash)
+        processing_data = json.loads(processing_content)
         
-        if status.get('status') != ProcessingStatus.COMPLETED.value:
+        if processing_data.get('status') != ProcessingStatus.COMPLETED.value:
             raise HTTPException(
                 status_code=400, 
-                detail=f"Processing not completed. Current status: {status.get('status')}"
+                detail=f"Processing not completed. Current status: {processing_data.get('status')}"
             )
         
-        # Get metadata
-        metadata_content = await storage_service.get_file('metadata.json', session_hash)
-        metadata = json.loads(metadata_content)
-        
         # Build page results
         page_results = []
-        total_pages = metadata.get('total_pages', 0)
+        total_pages = processing_data.get('file_info', {}).get('total_pages', 0)
         
         for page_num in range(1, total_pages + 1):
             try:
@@ -1643,10 +1586,10 @@ async def download_results(
     
     # Check if processing is completed
     try:
-        status_content = await storage_service.get_file('status.json', session_hash)
-        status = json.loads(status_content)
+        processing_content = await storage_service.get_file('processing.json', session_hash)
+        processing_data = json.loads(processing_content)
         
-        if status.get('status') != ProcessingStatus.COMPLETED.value:
+        if processing_data.get('status') != ProcessingStatus.COMPLETED.value:
             raise HTTPException(
                 status_code=400,
                 detail="Processing not completed"
diff --git a/app/ocr_service.py b/app/ocr_service.py
index 124e518..2aa42ba 100644
--- a/app/ocr_service.py
+++ b/app/ocr_service.py
@@ -563,15 +563,16 @@ class OCRService:
         """Extract images from raw PDF file in background thread"""
         try:
             from app.storage_service import StorageService
+            from datetime import datetime
             storage_service = StorageService(user_email=job.get('user_email'))
             
-            # Update job progress
-            job['progress'] = {
-                "current_step": "extracting",
-                "message": "Extracting images from PDF...",
-                "percent": 10
-            }
-            self._update_job_status_gcs(job_id, 'processing', 'Extracting images from PDF...')
+            # Update status to extracting
+            self._update_processing_status(job_id, {
+                "status": "extracting",
+                "current_step": "extracting_images",
+                "message": "Loading PDF file...",
+                "percent": 5
+            })
             
             # Load raw file from storage
             raw_file_data = asyncio.run(storage_service.get_file(raw_filename, session_id))
@@ -583,9 +584,10 @@ class OCRService:
                 logger.info(f"Converting PDF to images for session {session_id}")
                 
                 # Update progress
-                job['progress']['message'] = "Converting PDF to images..."
-                job['progress']['percent'] = 20
-                self._update_job_status_gcs(job_id, 'processing', 'Converting PDF to images...')
+                self._update_processing_status(job_id, {
+                    "message": "Converting PDF to images...",
+                    "percent": 10
+                })
                 
                 # Convert PDF to images
                 images = pdf2image.convert_from_bytes(
@@ -598,14 +600,21 @@ class OCRService:
                 page_count = len(images)
                 logger.info(f"Extracted {page_count} pages from PDF")
                 
-                # Update progress
-                job['progress']['message'] = f"Saving {page_count} page images..."
-                job['progress']['percent'] = 30
-                self._update_job_status_gcs(job_id, 'processing', f'Saving {page_count} page images...')
-                
+                # Initialize page tracking
+                pages = {}
                 page_images = []
+                
                 for i, image in enumerate(images):
-                    image_filename = f"page_{i+1:03d}.png"
+                    current_page = i + 1
+                    image_filename = f"page_{current_page:03d}.png"
+                    
+                    # Update progress for this page
+                    progress = 10 + (current_page / page_count * 30)  # 10-40%
+                    self._update_processing_status(job_id, {
+                        "current_step": "extracting_images",
+                        "message": f"Saving page {current_page} of {page_count}...",
+                        "percent": int(progress)
+                    })
                     
                     # Convert PIL image to bytes
                     img_buffer = io.BytesIO()
@@ -616,26 +625,65 @@ class OCRService:
                     asyncio.run(storage_service.save_file(image_bytes, image_filename, session_id))
                     page_images.append(image_filename)
                     
-                    # Update progress incrementally
-                    progress = 30 + (i + 1) / page_count * 20  # 30-50%
-                    job['progress']['percent'] = progress
-                    job['progress']['message'] = f"Saved image {i+1}/{page_count}"
-                    
-                    # Update status every 10 pages to avoid too many updates
-                    if i % 10 == 0 or i == page_count - 1:
-                        self._update_job_status_gcs(job_id, 'processing', f'Saved image {i+1}/{page_count}')
+                    # Add page to tracking
+                    pages[str(current_page)] = {
+                        "status": "pending",
+                        "image": image_filename,
+                        "image_extracted_at": datetime.utcnow().isoformat(),
+                        "processing_started_at": None,
+                        "processing_completed_at": None,
+                        "result_file": None,
+                        "error": None
+                    }
+                
+                # Update job with extracted pages
+                self._update_processing_status(job_id, {
+                    "status": "pending",
+                    "current_step": "extraction_complete",
+                    "message": f"Extracted {page_count} pages, ready for OCR",
+                    "percent": 40,
+                    "pages": pages,
+                    "file_info": {
+                        **job.get("file_info", {}),
+                        "total_pages": page_count
+                    }
+                })
                 
                 return page_images
+                
             else:
-                # For single images, save as page_001
-                image_filename = f"page_001.png"
+                # For single images
+                image_filename = "page_001.png"
                 asyncio.run(storage_service.save_file(raw_file_data, image_filename, session_id))
+                
+                self._update_processing_status(job_id, {
+                    "status": "pending",
+                    "current_step": "extraction_complete",
+                    "message": "Image ready for OCR",
+                    "percent": 40,
+                    "pages": {
+                        "1": {
+                            "status": "pending",
+                            "image": image_filename,
+                            "image_extracted_at": datetime.utcnow().isoformat(),
+                            "processing_started_at": None,
+                            "processing_completed_at": None,
+                            "result_file": None,
+                            "error": None
+                        }
+                    }
+                })
+                
                 return [image_filename]
                 
         except Exception as e:
             logger.error(f"Failed to extract images from {raw_filename}: {e}")
-            job['status'] = 'failed'
-            job['error'] = f"Failed to extract images: {str(e)}"
+            self._update_processing_status(job_id, {
+                "status": "failed",
+                "current_step": "extraction_failed",
+                "message": f"Failed to extract images: {str(e)}",
+                "percent": 0
+            })
             raise
 
     async def cleanup(self):
@@ -675,89 +723,91 @@ class OCRService:
         
         job_id = str(uuid.uuid4())
         
-        # Create job record with file reference
+        # Create comprehensive job record
         job_data = {
-            "status": "queued",
-            "type": job_type,
-            "file_reference": file_reference,  # Store file reference instead of binary data
-            "user_email": user_email,  # Store user context
-            "session_id": session_id,  # Store session context
-            "created": datetime.utcnow().isoformat(),
-            "result": None,
-            "error": None,
-            "progress": {
-                "current_step": "queued",
-                "message": "Job queued, waiting for model to be ready",
-                "current_page": 0,
-                "total_pages": file_reference.get("page_count", 1) if isinstance(file_reference, dict) else 1,
-                "percent": 0
-            }
+            "job_id": job_id,
+            "session_id": session_id,
+            "status": "pending",
+            "current_step": "queued",
+            "message": "Job queued for processing",
+            "percent": 0,
+            
+            "file_info": {
+                "filename": file_reference.get("filename", "unknown"),
+                "file_type": file_reference.get("file_type", job_type),
+                "total_pages": file_reference.get("page_count", 1),
+                "raw_file": file_reference.get("raw_file"),
+                "file_size": file_reference.get("file_size", 0)
+            },
+            
+            "user_email": user_email or "anonymous@gnosis-ocr.local",
+            "created_at": datetime.utcnow().isoformat(),
+            "updated_at": datetime.utcnow().isoformat(),
+            
+            "pages": {},
+            "file_reference": file_reference,  # Keep for backward compatibility
+            "type": job_type
         }
+        
+        # Initialize page tracking if we have page images
+        if "page_images" in file_reference:
+            for i, image_file in enumerate(file_reference["page_images"], 1):
+                job_data["pages"][str(i)] = {
+                    "status": "pending",
+                    "image": image_file,
+                    "image_extracted_at": datetime.utcnow().isoformat(),
+                    "processing_started_at": None,
+                    "processing_completed_at": None,
+                    "result_file": None,
+                    "error": None
+                }
 
         
         self.jobs[job_id] = job_data
         
-        # CRITICAL FIX: Persist job to GCS immediately
-        try:
-            # Create storage service with user context
-            storage_service = StorageService(user_email=user_email)
-
-            # Only persist to GCS in cloud mode
-            if os.environ.get('RUNNING_IN_CLOUD') == 'true':
-                storage_service.force_cloud_mode()
-                
-                # Save job metadata to GCS using job_id as session_hash
-                
-                # Calculate file size from file_reference if available
-                file_size = 0
-                if isinstance(file_reference, dict) and 'page_count' in file_reference:
-                    file_size = file_reference.get('page_count', 0) * 1024  # Rough estimate
-                
-                job_metadata = {
-                    'job_id': job_id,
-                    'job_type': job_type,
-                    'status': 'queued',
-                    'created_at': datetime.utcnow().isoformat(),
-                    'file_size': file_size
-                }
+        # Always create processing.json file for status tracking
+        if session_id:
+            logger.info(f"Creating processing.json for job {job_id} in session {session_id}")
+        else:
+            logger.error(f"No session_id provided for job {job_id} - cannot create processing.json")
             
-            # Use existing session_id or create new one
-            # (this runs in main thread, not ThreadPoolExecutor)
+        if session_id:
             try:
-                loop = asyncio.get_event_loop()
-                
-                if session_id:
-                    # Use existing session from upload
-                    used_session_id = session_id
-                else:
-                    # Create new session if none provided
-                    session_task = loop.create_task(storage_service.create_session(job_metadata, session_hash=job_id))
-                    used_session_id = job_id
+                storage_service = StorageService(user_email=user_email)
+                if os.environ.get('RUNNING_IN_CLOUD') == 'true':
+                    storage_service.force_cloud_mode()
                 
-                # Save initial status to the session
-                status_data = {
-                    'status': 'queued',
-                    'progress': 0.0,
-                    'message': 'Job queued, waiting for model to be ready',
-                    'updated_at': datetime.utcnow().isoformat()
-                }
-                status_task = loop.create_task(storage_service.save_file(
-                    json.dumps(status_data, indent=2).encode('utf-8'),
-                    'status.json',
-                    used_session_id
-                ))
-
-            except RuntimeError:
-                # If no event loop in this thread, skip GCS persistence for now
-                logger.warning(f"No event loop available for job {job_id} GCS persistence")
-
-            
-            logger.info(f"✅ Job {job_id} persisted to GCS")
-            
-        except Exception as e:
-            logger.error(f"❌ Failed to persist job {job_id} to GCS: {e}")
-            # Continue anyway - job is still in memory
+                # Save processing.json for both local and cloud
+                # Check if we're in an async context
+                try:
+                    loop = asyncio.get_running_loop()
+                    # We're in an async context, schedule the coroutine
+                    task = loop.create_task(storage_service.save_file(
+                        json.dumps(job_data, indent=2).encode('utf-8'),
+                        'processing.json',
+                        session_id
+                    ))
+                    # Don't wait for it to complete to avoid blocking
+                    logger.info(f"✅ Job {job_id} processing.json save scheduled for session {session_id}")
+                except RuntimeError:
+                    # No running loop, create one
+                    loop = asyncio.new_event_loop()
+                    asyncio.set_event_loop(loop)
+                    try:
+                        loop.run_until_complete(storage_service.save_file(
+                            json.dumps(job_data, indent=2).encode('utf-8'),
+                            'processing.json',
+                            session_id
+                        ))
+                        logger.info(f"✅ Job {job_id} processing.json created in session {session_id}")
+                    finally:
+                        loop.close()
+                    
+            except Exception as e:
+                logger.error(f"❌ Failed to create processing.json for job {job_id}: {e}")
 
+        # Add job to in-memory tracking
+        self.jobs[job_id] = job_data
         
         if not self._model_loaded:
             if self._loading:
@@ -792,8 +842,12 @@ class OCRService:
                 job['status'] = 'processing'
                 logger.info(f"🔄 Processing job {job_id}")
                 
-                # Update GCS with processing status
-                self._update_job_status_gcs(job_id, 'processing', 'Starting OCR processing...')
+                # Update processing status
+                self._update_processing_status(job_id, {
+                    "status": "processing",
+                    "current_step": "ocr_processing", 
+                    "message": "Starting OCR processing..."
+                })
 
                 
                 # Handle file reference - check if we need to extract images
@@ -904,8 +958,13 @@ class OCRService:
                 }
                 logger.info(f"✅ Job {job_id} completed successfully")
                 
-                # Update GCS with completion status
-                self._update_job_status_gcs(job_id, 'completed', 'Processing complete!')
+                # Update processing status to completed
+                self._update_processing_status(job_id, {
+                    "status": "completed",
+                    "current_step": "completed", 
+                    "message": "Processing complete!",
+                    "percent": 100
+                })
                 
                 # CRITICAL: Save the actual OCR results to storage
                 try:
@@ -978,70 +1037,61 @@ class OCRService:
                 }
                 logger.error(f"❌ Job {job_id} failed: {e}")
                 
-                # Update GCS with error status
-                self._update_job_status_gcs(job_id, 'failed', f'Processing failed: {str(e)}')
+                # Update processing status to failed
+                self._update_processing_status(job_id, {
+                    "status": "failed",
+                    "current_step": "failed", 
+                    "message": f"Processing failed: {str(e)}",
+                    "percent": 0
+                })
 
         
         self.executor.submit(_process)
     
-    def _update_job_status_gcs(self, job_id, status, message):
-        """Helper method to update job status in GCS"""
+    def _update_processing_status(self, job_id, updates):
+        """Update processing.json with new status information
+        
+        Args:
+            job_id: The job ID
+            updates: Dictionary of fields to update in processing.json
+        """
         try:
             from app.storage_service import StorageService
             from datetime import datetime
             
-            # Get job data to extract user and session context
             job = self.jobs.get(job_id, {})
-            user_email = job.get('user_email')
-            session_id = job.get('session_id', job_id)  # Use session_id if available, fallback to job_id
             
-            # Create storage service with user context
-            storage_service = StorageService(user_email=user_email)
-
+            # Update in-memory job data
+            job.update(updates)
+            job["updated_at"] = datetime.utcnow().isoformat()
+            
+            # Update in GCS
             if os.environ.get('RUNNING_IN_CLOUD') == 'true':
+                user_email = job.get('user_email')
+                session_id = job.get('session_id', job_id)
+                
+                storage_service = StorageService(user_email=user_email)
                 storage_service.force_cloud_mode()
-            
-            # Get current job data for progress info
-            progress_data = job.get('progress', {})
-            
-            # Create status update
-            status_data = {
-                'status': status,
-                'progress': progress_data.get('percent', 0),
-                'current_page': progress_data.get('current_page', 0),
-                'total_pages': progress_data.get('total_pages', 0),
-                'message': message,
-                'updated_at': datetime.utcnow().isoformat()
-            }
-            
-            # Save to session directory (not job_id directory)
-            try:
+                
                 # Create new event loop for this thread
                 loop = asyncio.new_event_loop()
                 asyncio.set_event_loop(loop)
                 
-                # Run the save operation using session_id
-                loop.run_until_complete(storage_service.save_file(
-                    json.dumps(status_data, indent=2).encode('utf-8'),
-                    'status.json',
-                    session_id
-                ))
-
-            finally:
-                # Clean up the loop
                 try:
+                    loop.run_until_complete(storage_service.save_file(
+                        json.dumps(job, indent=2).encode('utf-8'),
+                        'processing.json',
+                        session_id
+                    ))
+                    logger.debug(f"📝 Updated processing.json for job {job_id}")
+                finally:
                     loop.close()
-                except:
-                    pass
-
-            
-            logger.debug(f"📝 Updated job {job_id} status in GCS: {status}")
-            
+                    
         except Exception as e:
-            logger.error(f"❌ Failed to update job {job_id} status in GCS: {e}")
+            logger.error(f"❌ Failed to update processing.json for job {job_id}: {e}")
     
     def get_job_status(self, job_id):
-        """Get job result by ID - check memory first, then GCS"""
+        """Get job result by ID - check memory first, then GCS processing.json"""
         # First check in-memory jobs
         if job_id in self.jobs:
             return self.jobs[job_id]
@@ -1050,52 +1100,40 @@ class OCRService:
         try:
             from app.storage_service import StorageService
             
-            # Try to load job status from GCS
-            storage_service = StorageService(user_email=None)  # Anonymous fallback
+            storage_service = StorageService(user_email=None)
             if os.environ.get('RUNNING_IN_CLOUD') == 'true':
                 storage_service.force_cloud_mode()
             
-            # Try to get status file - create new event loop if needed
+            # Try to get processing.json
             try:
-                # Try to get existing loop first
                 loop = asyncio.get_event_loop()
-                status_content = loop.run_until_complete(storage_service.get_file('status.json', job_id))
+                processing_content = loop.run_until_complete(
+                    storage_service.get_file('processing.json', job_id)
+                )
             except RuntimeError:
                 # No event loop, create a new one
                 loop = asyncio.new_event_loop()
                 try:
                     asyncio.set_event_loop(loop)
-                    status_content = loop.run_until_complete(storage_service.get_file('status.json', job_id))
+                    processing_content = loop.run_until_complete(
+                        storage_service.get_file('processing.json', job_id)
+                    )
                 finally:
                     loop.close()
-
             
-            if status_content:
-                status_data = json.loads(status_content.decode('utf-8'))
-                logger.info(f"🔄 Recovered job {job_id} status from GCS: {status_data.get('status')}")
-                
-                # Reconstruct basic job data
-                recovered_job = {
-                    "status": status_data.get('status', 'unknown'),
-                    "progress": {
-                        "current_step": status_data.get('status', 'unknown'),
-                        "message": status_data.get('message', 'Recovered from storage'),
-                        "current_page": status_data.get('current_page', 0),
-                        "total_pages": status_data.get('total_pages', 0),
-                        "percent": status_data.get('progress', 0)
-                    },
-                    "result": None,  # Result would need separate recovery
-                    "created": "unknown",
-                    "type": "unknown"
-                }
+            if processing_content:
+                job_data = json.loads(processing_content.decode('utf-8'))
+                logger.info(f"🔄 Recovered job {job_id} from GCS: {job_data.get('status')}")
                 
-                return recovered_job
+                # Cache it in memory for future requests
+                self.jobs[job_id] = job_data
+                return job_data
                 
         except Exception as e:
             logger.debug(f"Could not recover job {job_id} from GCS: {e}")
         
         # Not found anywhere
-        return {"status": "not_found"}
+        return {"status": "not_found", "error": "Job not found"}
 
 
 
diff --git a/app/static/script.js b/app/static/script.js
index 407dc9e..282dcdc 100644
--- a/app/static/script.js
+++ b/app/static/script.js
@@ -1,230 +1,69 @@
-// DOM Elements
-const uploadSection = document.getElementById('upload-section');
-const progressSection = document.getElementById('progress-section');
-const resultsSection = document.getElementById('results-section');
-const errorMessage = document.getElementById('error-message');
+// Global variables
+let currentJobId = null;
+let currentSessionId = null;
+let pollingInterval = null;
+let lastProcessingData = null;
 
-const uploadArea = document.getElementById('upload-area');
-const fileInput = document.getElementById('file-input');
-const browseBtn = document.getElementById('browse-btn');
+// Configuration
+const POLLING_INTERVAL = 2000; // 2 seconds for smoother updates
+const API_BASE = window.location.origin;
 
-const progressFill = document.getElementById('progress-fill');
-const progressPercent = document.getElementById('progress-percent');
-const progressMessage = document.getElementById('progress-message');
-const progressDetails = document.getElementById('progress-details');
-const progressPages = document.getElementById('progress-pages');
-
-const pageSelect = document.getElementById('page-select');
-const imagePageSelect = document.getElementById('image-page-select');
-const textOutput = document.getElementById('text-output');
-const imageOutput = document.getElementById('image-output');
-const metadataOutput = document.getElementById('metadata-output');
-
-const downloadMarkdown = document.getElementById('download-markdown');
-const downloadAll = document.getElementById('download-all');
-const newUpload = document.getElementById('new-upload');
-const copyText = document.getElementById('copy-text');
-const errorRetry = document.getElementById('error-retry');
-
-// Model status tracking
-let modelReady = false;
-let checkingModel = false;
-
-// Check model status
-async function checkModelStatus() {
-    if (checkingModel) return;
-    checkingModel = true;
-    
-    try {
-        const response = await fetch('/health');
-        const health = await response.json();
-        
-        if (health.status === 'healthy' && health.model_loaded) {
-            modelReady = true;
-            updateUploadArea('ready');
-        } else if (health.status === 'starting' || !health.model_loaded) {
-            modelReady = false;
-            updateUploadArea('loading');
-            // Check again in 2 seconds
-            setTimeout(checkModelStatus, 2000);
-        } else {
-            modelReady = false;
-            updateUploadArea('failed');
-        }
-    } catch (error) {
-        modelReady = false;
-        updateUploadArea('error');
-    } finally {
-        checkingModel = false;
-    }
-}
-
-// Update upload area based on model status
-function updateUploadArea(status) {
-    const uploadArea = document.getElementById('upload-area');
-    const h2 = uploadArea.querySelector('h2');
-    const p = uploadArea.querySelector('p');
-    const button = uploadArea.querySelector('button');
-    
-    switch (status) {
-        case 'loading':
-            h2.textContent = 'Loading OCR Model...';
-            p.textContent = 'You can upload files - they will be queued until ready';
-            button.disabled = false;
-            button.textContent = 'Upload (Will Queue)';
-            uploadArea.style.opacity = '0.8';
-            break;
-        case 'ready':
-            h2.textContent = 'Drop PDF file here or click to browse';
-            p.textContent = 'Maximum file size: 500MB';
-            button.disabled = false;
-            button.textContent = 'Browse Files';
-            uploadArea.style.opacity = '1';
-            break;
-        case 'failed':
-            h2.textContent = 'OCR Model Failed to Load';
-            p.textContent = 'Please refresh the page to try again';
-            button.disabled = true;
-            button.textContent = 'Model Failed';
-            uploadArea.style.opacity = '0.6';
-            break;
-        case 'error':
-            h2.textContent = 'Connection Error';
-            p.textContent = 'Unable to check model status';
-            button.disabled = true;
-            button.textContent = 'Connection Error';
-            uploadArea.style.opacity = '0.6';
-            break;
-    }
-}
-
-
-// State
-let currentSession = null;
-let ocrResults = null;
-let statusCheckInterval = null;
-// WebSocket removed - using polling only
-let uploadPaused = false;
-let currentUploadSession = null;
-
-// Initialize
-document.addEventListener('DOMContentLoaded', () => {
-    setupEventListeners();
+// Initialize the app
+document.addEventListener('DOMContentLoaded', function() {
+    initializeEventListeners();
 });
 
-// Event Listeners
-function setupEventListeners() {
-    // Model loading is automatic in background
-    // No manual load model button needed
-    
-    // File upload
-    if (browseBtn) {
-        browseBtn.addEventListener('click', (e) => {
-            e.stopPropagation();
-            console.log('Browse button clicked');
-            fileInput.click();
-        });
-    } else {
-        console.error('Browse button not found');
-    }
-    if (fileInput) {
-        fileInput.addEventListener('change', handleFileSelect);
-    }
-
+function initializeEventListeners() {
+    // Upload area events
+    const uploadArea = document.getElementById('upload-area');
+    const fileInput = document.getElementById('file-input');
+    const browseBtn = document.getElementById('browse-btn');
     
-    // Drag and drop
+    uploadArea.addEventListener('click', () => fileInput.click());
     uploadArea.addEventListener('dragover', handleDragOver);
     uploadArea.addEventListener('dragleave', handleDragLeave);
     uploadArea.addEventListener('drop', handleDrop);
-    uploadArea.addEventListener('click', (e) => {
-        // Only trigger if not clicking the browse button
-        if (!e.target.closest('#browse-btn')) {
-            fileInput.click();
-        }
-    });
-    
-    // Results actions
-    newUpload.addEventListener('click', resetToUpload);
-    downloadMarkdown.addEventListener('click', () => downloadFile('markdown'));
-    downloadAll.addEventListener('click', () => downloadFile('all'));
-    copyText.addEventListener('click', copyTextToClipboard);
-    errorRetry.addEventListener('click', resetToUpload);
+    fileInput.addEventListener('change', handleFileSelect);
     
-    // Tabs
+    // Results navigation
     document.querySelectorAll('.tab-btn').forEach(btn => {
-        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
+        btn.addEventListener('click', (e) => switchTab(e.target.dataset.tab));
     });
     
-    // Page navigation
-    pageSelect.addEventListener('change', () => displayPage(pageSelect.value));
-    imagePageSelect.addEventListener('change', () => displayImage(imagePageSelect.value));
+    // Download buttons
+    document.getElementById('download-markdown').addEventListener('click', downloadMarkdown);
+    document.getElementById('download-all').addEventListener('click', downloadAll);
+    document.getElementById('new-upload').addEventListener('click', resetInterface);
+    
+    // Error retry
+    document.getElementById('error-retry').addEventListener('click', resetInterface);
 }
 
-// File Handling
-function handleFileSelect(e) {
-    const file = e.target.files[0];
+// File upload handling
+async function handleFileSelect(event) {
+    const file = event.target.files[0];
     if (file) {
-        uploadFile(file);
+        await uploadFile(file);
     }
 }
 
-function handleDragOver(e) {
-    e.preventDefault();
-    uploadArea.classList.add('dragover');
-}
-
-function handleDragLeave(e) {
-    e.preventDefault();
-    uploadArea.classList.remove('dragover');
-}
-
-function handleDrop(e) {
-    e.preventDefault();
-    uploadArea.classList.remove('dragover');
-    
-    const file = e.dataTransfer.files[0];
-    if (file && file.type === 'application/pdf') {
-        uploadFile(file);
-    } else {
-        showError('Please upload a PDF file');
-    }
-}
-
-// Upload File - Always use chunked upload for cloud compatibility
 async function uploadFile(file) {
-    // Validate file type
-    const validTypes = [
-        'application/pdf',
-        'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 
-        'image/webp', 'image/bmp', 'image/tiff', 'image/tif'
-    ];
-    
-    const fileExt = file.name.toLowerCase().split('.').pop();
-    const validExtensions = ['pdf', 'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'tif'];
-    
-    if (!validTypes.includes(file.type) && !validExtensions.includes(fileExt)) {
-        showError('Please upload a PDF or image file (PDF, JPG, PNG, GIF, WEBP, BMP, TIFF)');
-        return;
-    }
-    
     // Show progress section
     showSection('progress');
     updateProgress(0, 'Preparing upload...');
     
-    // Always use chunked upload for Google Cloud Run compatibility
+    // Update stage indicator
+    updateStageIndicator('upload');
+    
+    // Always use chunked upload for cloud compatibility
     await uploadFileChunked(file);
 }
 
-// Non-chunked upload removed - using only chunked upload for cloud compatibility
-
-// Chunked upload - now used for all files for cloud compatibility
 async function uploadFileChunked(file) {
-    const CHUNK_SIZE = 1024 * 1024; // 1MB chunks - optimal for Google Cloud Run
+    const CHUNK_SIZE = 1024 * 1024; // 1MB chunks
     const totalChunks = Math.ceil(file.size / CHUNK_SIZE);
     
     try {
-        updateProgress(0, `Preparing chunked upload (${totalChunks} chunks)...`);
-        
         // Start upload session
         const startResponse = await fetch('/api/v1/jobs/submit/start', {
             method: 'POST',
@@ -235,506 +74,484 @@ async function uploadFileChunked(file) {
                 total_chunks: totalChunks
             })
         });
-
         
         if (!startResponse.ok) {
-            const error = await startResponse.json();
-            throw new Error(error.message || 'Failed to start upload');
+            throw new Error('Failed to start upload');
         }
         
         const sessionData = await startResponse.json();
+        currentSessionId = sessionData.upload_id;
         
-        currentSession = sessionData.upload_id;
-        currentUploadSession = sessionData;
-        
-        
-        // WebSocket functionality removed - using polling instead
-
-        
-        
-        // Upload chunks
-        let jobId = null;
-        for (let chunkNumber = 0; chunkNumber < totalChunks; chunkNumber++) {
-            if (uploadPaused) {
-                // Wait for resume
-                await waitForResume();
-            }
-            
-            const start = chunkNumber * CHUNK_SIZE;
+        // Upload chunks with progress
+        for (let i = 0; i < totalChunks; i++) {
+            const start = i * CHUNK_SIZE;
             const end = Math.min(start + CHUNK_SIZE, file.size);
             const chunk = file.slice(start, end);
             
-            const chunkResult = await uploadChunk(currentSession, chunkNumber, chunk);
+            const progress = Math.round((i / totalChunks) * 30); // Upload is 30% of total
+            updateProgress(progress, `Uploading chunk ${i + 1} of ${totalChunks}...`);
+            
+            const formData = new FormData();
+            formData.append('file', chunk, `chunk_${i}`);
+            
+            const chunkResponse = await fetch(`/api/v1/jobs/submit/chunk/${currentSessionId}`, {
+                method: 'POST',
+                headers: { 'X-Chunk-Number': i.toString() },
+                body: formData
+            });
             
-            // Check if upload is complete (last chunk)
-            if (chunkResult.upload_complete) {
-                jobId = chunkResult.job_id;
-                updateProgress(100, 'Upload complete, processing...');
-                break;
+            if (!chunkResponse.ok) {
+                throw new Error(`Failed to upload chunk ${i + 1}`);
             }
             
-            // Update progress for partial upload
-            const progress = ((chunkNumber + 1) / totalChunks) * 100;
-            updateProgress(progress, `Uploading chunk ${chunkNumber + 1} of ${totalChunks}...`);
-        }
-        
-        // If we have a job ID, start polling for job status instead of session status
-        if (jobId) {
-            currentSession = jobId; // Switch to using job ID for status checks
-            startJobStatusChecking(jobId);
-        }
-
-        
-    } catch (error) {
-        logError('Chunked upload failed', { session: currentSession, error: error.message });
-        showError(error.message);
-    }
-}
-
-// Upload single chunk
-async function uploadChunk(sessionHash, chunkNumber, chunk) {
-    return new Promise((resolve, reject) => {
-        const reader = new FileReader();
-        
-        reader.onload = async function(e) {
-            try {
-                
-                const arrayBuffer = e.target.result;
-                // Convert to base64 safely for large chunks
-                const uint8Array = new Uint8Array(arrayBuffer);
-                let binaryString = '';
-                for (let i = 0; i < uint8Array.length; i++) {
-                    binaryString += String.fromCharCode(uint8Array[i]);
-                }
-                const base64 = btoa(binaryString);
-                
-                // Create form data for file upload (new endpoint expects file upload)
-                const formData = new FormData();
-                const chunkBlob = new Blob([uint8Array]);
-                formData.append('file', chunkBlob, `chunk_${chunkNumber}`);
-                
-                
-                const controller = new AbortController();
-                const timeoutId = setTimeout(() => controller.abort(), 30000); // 30 second timeout
-                
-                const response = await fetch(`/api/v1/jobs/submit/chunk/${sessionHash}`, {
-                    method: 'POST',
-                    headers: { 'X-Chunk-Number': chunkNumber.toString() },
-                    body: formData,
-                    signal: controller.signal
-                });
-                
-                clearTimeout(timeoutId);
-                
-
-                
-                if (!response.ok) {
-                    let errorMessage = `HTTP ${response.status}: Failed to upload chunk ${chunkNumber}`;
-                    try {
-                        const error = await response.json();
-                        errorMessage = error.message || errorMessage;
-                    } catch (e) {
-                        // If response is not JSON (e.g., HTML error page), use status text
-                        errorMessage = `HTTP ${response.status} ${response.statusText}: ${errorMessage}`;
-                    }
-                    throw new Error(errorMessage);
-                }
-                
-                const result = await response.json();
-                resolve(result);
+            const chunkResult = await chunkResponse.json();
+            
+            // Check if this was the last chunk
+            if (chunkResult.upload_complete && chunkResult.job_id) {
+                currentJobId = chunkResult.job_id;
+                updateProgress(30, 'Upload complete, processing starting...');
                 
-            } catch (error) {
-                logError('Chunk upload failed', { chunkNumber, sessionHash, error: error.message });
-                reject(error);
+                // Start polling for processing status
+                startPolling();
+                return;
             }
-        };
+        }
         
-        reader.onerror = () => reject(new Error('Failed to read chunk'));
-        reader.readAsArrayBuffer(chunk);
-    });
-}
-
-// WebSocket functionality removed - using status polling instead
-
-// WebSocket progress updates removed - using status polling instead
-
-// Wait for upload resume (placeholder for pause/resume functionality)
-async function waitForResume() {
-    return new Promise(resolve => {
-        const checkInterval = setInterval(() => {
-            if (!uploadPaused) {
-                clearInterval(checkInterval);
-                resolve();
-            }
-        }, 100);
-    });
-}
-
-// Status Checking with retry logic
-let statusCheckFailureCount = 0;
-const MAX_STATUS_FAILURES = 5; // Allow 5 consecutive failures before giving up
-
-function startStatusChecking() {
-    // Clear any existing interval first
-    if (statusCheckInterval) {
-        clearInterval(statusCheckInterval);
+    } catch (error) {
+        showError('Upload failed: ' + error.message);
     }
-    // Reset failure count
-    statusCheckFailureCount = 0;
-    statusCheckInterval = setInterval(checkStatus, 10000);
 }
 
-// Job status checking for new job system
-function startJobStatusChecking(jobId) {
-    // Clear any existing interval first
-    if (statusCheckInterval) {
-        clearInterval(statusCheckInterval);
+// Polling for processing status
+function startPolling() {
+    // Clear any existing polling
+    if (pollingInterval) {
+        clearInterval(pollingInterval);
     }
-    // Reset failure count
-    statusCheckFailureCount = 0;
-    statusCheckInterval = setInterval(() => checkJobStatus(jobId), 10000);
+    
+    // Poll immediately
+    pollProcessingStatus();
+    
+    // Then poll at intervals
+    pollingInterval = setInterval(pollProcessingStatus, POLLING_INTERVAL);
 }
 
-async function checkJobStatus(jobId) {
-    if (!jobId) return;
+async function pollProcessingStatus() {
+    if (!currentSessionId) return;
     
     try {
-        const response = await fetch(`/api/v1/jobs/status/${jobId}`);
-        
+        // Use the existing /status endpoint
+        const response = await fetch(`${API_BASE}/status/${currentSessionId}`);
         if (!response.ok) {
-            statusCheckFailureCount++;
-            if (statusCheckFailureCount >= MAX_STATUS_FAILURES) {
-                showError('Unable to check job status. Please refresh the page.');
-                clearInterval(statusCheckInterval);
-            }
+            console.error('Failed to fetch status');
             return;
         }
         
-        // Reset failure count on successful response
-        statusCheckFailureCount = 0;
+        const data = await response.json();
         
-        const status = await response.json();
+        // Convert status response to processing.json format for UI
+        const processingData = {
+            status: data.status,
+            percent: data.progress || 0,
+            message: data.message || 'Processing...',
+            current_step: data.status === 'pending' ? 'queued' : 
+                         data.status === 'processing' ? 'ocr_processing' : 
+                         data.status,
+            file_info: {
+                total_pages: data.total_pages || 1
+            },
+            pages: {} // We don't have individual page status from this endpoint
+        };
         
-        if (status.status === 'completed') {
-            clearInterval(statusCheckInterval);
-            updateProgress(100, 'Processing complete!');
-            
-            // Show results
-            if (status.result) {
-                showResults(jobId, status.result);
+        // For now, create fake page status based on progress
+        if (data.total_pages > 1) {
+            const completedPages = data.current_page || 0;
+            for (let i = 1; i <= data.total_pages; i++) {
+                processingData.pages[i] = {
+                    status: i <= completedPages ? 'completed' : 
+                           i === completedPages + 1 ? 'processing' : 'pending',
+                    image: `page_${String(i).padStart(3, '0')}.png`
+                };
             }
-        } else if (status.status === 'failed') {
-            clearInterval(statusCheckInterval);
-            showError(`Processing failed: ${status.error || 'Unknown error'}`);
-        } else if (status.status === 'processing') {
-            // Update progress based on job progress
-            const progress = status.progress || {};
-            updateProgress(
-                progress.percent || 0, 
-                progress.message || 'Processing...',
-                progress.current_page,
-                progress.total_pages
-            );
         }
         
-    } catch (error) {
-        statusCheckFailureCount++;
-        logError('Status check failed', error);
+        updateProcessingUI(processingData);
+        
+        // Store for reference
+        lastProcessingData = processingData;
         
-        if (statusCheckFailureCount >= MAX_STATUS_FAILURES) {
-            showError('Unable to check job status. Please refresh the page.');
-            clearInterval(statusCheckInterval);
+        // Check if completed
+        if (data.status === 'completed' || data.status === 'failed') {
+            clearInterval(pollingInterval);
+            pollingInterval = null;
+            
+            if (data.status === 'completed') {
+                await loadResults();
+            } else {
+                showError(data.message || 'Processing failed');
+            }
         }
+        
+    } catch (error) {
+        console.error('Polling error:', error);
     }
 }
 
-
-async function checkStatus() {
-    if (!currentSession) {
-        return;
+function updateProcessingUI(data) {
+    // Update main progress
+    const percent = data.percent || 0;
+    updateProgress(percent, data.message || 'Processing...');
+    
+    // Update stage indicator based on current_step
+    if (data.current_step === 'queued') {
+        updateStageIndicator('upload');
+    } else if (data.current_step === 'extracting_images' || data.current_step === 'extraction_complete') {
+        updateStageIndicator('extract');
+    } else if (data.current_step === 'ocr_processing' || data.current_step === 'processing') {
+        updateStageIndicator('ocr');
     }
     
+    // Show page grid for PDFs
+    if (data.file_info && data.file_info.total_pages > 1) {
+        updatePageGrid(data.pages);
+        document.getElementById('page-grid-container').classList.remove('hidden');
+    }
     
-    try {
-        const response = await fetch(`/status/${currentSession}`, {
-            timeout: 10000 // 10 second timeout
-        });
-        
+    // Show live preview if processing
+    if (data.current_step === 'ocr_processing' && data.pages) {
+        updateLivePreview(data);
+    }
+}
+
+function updateProgress(percent, message) {
+    document.getElementById('main-progress-fill').style.width = percent + '%';
+    document.getElementById('progress-percent').textContent = percent + '%';
+    document.getElementById('progress-message').textContent = message;
+}
 
+function updateStageIndicator(activeStage) {
+    const stages = document.querySelectorAll('.stage');
+    const stageOrder = ['upload', 'extract', 'ocr'];
+    const activeIndex = stageOrder.indexOf(activeStage);
+    
+    stages.forEach((stage, index) => {
+        const stageName = stage.dataset.stage;
+        const stageIndex = stageOrder.indexOf(stageName);
         
-        if (!response.ok) {
-            const errorText = await response.text();
-            logError('Status check failed', {
-                session: currentSession,
-                status: response.status,
-                statusText: response.statusText,
-                error: errorText,
-                failure_count: statusCheckFailureCount + 1
-            });
-            throw new Error(`Status check failed: ${response.status} ${response.statusText}`);
+        if (stageIndex < activeIndex) {
+            stage.classList.add('completed');
+            stage.classList.remove('active');
+        } else if (stageIndex === activeIndex) {
+            stage.classList.add('active');
+            stage.classList.remove('completed');
+        } else {
+            stage.classList.remove('active', 'completed');
         }
+    });
+}
+
+function updatePageGrid(pages) {
+    const grid = document.getElementById('page-grid');
+    grid.innerHTML = '';
+    
+    Object.entries(pages).forEach(([pageNum, pageData]) => {
+        const pageItem = document.createElement('div');
+        pageItem.className = 'page-item';
+        pageItem.classList.add(pageData.status);
+        pageItem.dataset.page = pageNum;
         
-        const status = await response.json();
-        
-        // Reset failure count on successful response
-        statusCheckFailureCount = 0;
+        pageItem.innerHTML = `
+            <div class="page-number">${pageNum}</div>
+            <div class="page-status-icon">
+                ${pageData.status === 'completed' ? '✓' : 
+                  pageData.status === 'processing' ? '⏳' : 
+                  pageData.status === 'failed' ? '✗' : ''}
+            </div>
+        `;
         
-        // Update progress
-        updateProgress(
-            status.progress,
-            status.message || 'Processing...',
-            status.current_page,
-            status.total_pages
-        );
+        // Click to preview
+        pageItem.addEventListener('click', () => previewPage(pageNum));
         
-        // Check if completed
-        if (status.status === 'completed') {
-            clearInterval(statusCheckInterval);
-            await loadResults();
-        } else if (status.status === 'failed') {
-            logError('Processing failed', { session: currentSession, message: status.message });
-            clearInterval(statusCheckInterval);
-            showError(status.message || 'Processing failed');
-        }
+        grid.appendChild(pageItem);
+    });
+}
 
+function updateLivePreview(data) {
+    // Find the currently processing page
+    const processingPage = Object.entries(data.pages).find(([_, pageData]) => 
+        pageData.status === 'processing'
+    );
+    
+    if (processingPage) {
+        const [pageNum, pageData] = processingPage;
+        const preview = document.getElementById('live-preview');
+        preview.classList.remove('hidden');
         
-    } catch (error) {
-        statusCheckFailureCount++;
-        
-        logError('Status check error', {
-            session: currentSession,
-            error: error.message,
-            failure_count: statusCheckFailureCount,
-            max_failures: MAX_STATUS_FAILURES
-        });
-        
-        // Only show error and stop if we've exceeded max failures
-        if (statusCheckFailureCount >= MAX_STATUS_FAILURES) {
-            clearInterval(statusCheckInterval);
-            showError(`Connection lost after ${MAX_STATUS_FAILURES} attempts. Please try refreshing the page.`);
+        // Show page image
+        if (pageData.image) {
+            const imageUrl = `${API_BASE}/api/sessions/${currentSessionId}/files/${pageData.image}`;
+            document.getElementById('current-page-image').src = imageUrl;
         }
     }
-
 }
 
-// Load Results
 async function loadResults() {
+    showSection('results');
+    
     try {
-        const response = await fetch(`/results/${currentSession}`);
-        if (!response.ok) throw new Error('Failed to load results');
+        // We need to get the results from the /results endpoint
+        const resultsResponse = await fetch(`${API_BASE}/results/${currentSessionId}`);
+        if (!resultsResponse.ok) {
+            throw new Error('Failed to load results');
+        }
+        
+        const results = await resultsResponse.json();
+        
+        // Display combined text from first page or construct from all pages
+        const combinedText = results.pages.map(page => 
+            `# Page ${page.page_number}\n\n${page.text}\n\n`
+        ).join('');
+        displayCombinedText(combinedText);
         
-        ocrResults = await response.json();
-        displayResults();
+        // Store results for page navigation
+        window.ocrResults = results;
+        
+        // Populate page selector from results
+        if (results.pages && results.pages.length > 0) {
+            const pages = {};
+            results.pages.forEach(page => {
+                pages[page.page_number] = {
+                    status: 'completed',
+                    image: `page_${String(page.page_number).padStart(3, '0')}.png`,
+                    result_file: `page_${String(page.page_number).padStart(3, '0')}_result.txt`,
+                    text: page.text
+                };
+            });
+            populatePageSelector(pages);
+        }
+        
+        // Show metadata
+        document.getElementById('metadata-output').textContent = 
+            JSON.stringify(results, null, 2);
         
     } catch (error) {
-        showError(error.message);
+        showError('Failed to load results: ' + error.message);
     }
 }
 
-// Display Results
-function displayResults() {
-    showSection('results');
+function displayCombinedText(text) {
+    const output = document.getElementById('combined-text-output');
     
-    // Populate page selectors
-    populatePageSelectors();
+    // Render markdown if possible
+    if (window.marked) {
+        output.innerHTML = marked.parse(text);
+    } else {
+        output.textContent = text;
+    }
+}
+
+function populatePageSelector(pages) {
+    const select = document.getElementById('page-select');
+    select.innerHTML = '';
     
-    // Display first page
-    displayPage(1);
-    displayImage(1);
+    Object.entries(pages).forEach(([pageNum, pageData]) => {
+        const option = document.createElement('option');
+        option.value = pageNum;
+        option.textContent = `Page ${pageNum}`;
+        select.appendChild(option);
+    });
     
-    // Display metadata
-    displayMetadata();
+    // Load first page
+    if (select.options.length > 0) {
+        select.selectedIndex = 0;
+        loadPageContent(select.value);
+    }
+    
+    // Add change listener
+    select.addEventListener('change', (e) => loadPageContent(e.target.value));
 }
 
-function populatePageSelectors() {
-    pageSelect.innerHTML = '';
-    imagePageSelect.innerHTML = '';
-    
-    for (let i = 1; i <= ocrResults.total_pages; i++) {
-        const option = new Option(`Page ${i}`, i);
-        pageSelect.add(option.cloneNode(true));
-        imagePageSelect.add(option);
+async function loadPageContent(pageNum) {
+    // First check if we have results from the /results endpoint
+    if (window.ocrResults && window.ocrResults.pages) {
+        const page = window.ocrResults.pages.find(p => p.page_number == pageNum);
+        if (page) {
+            // Show page image using the URL from results
+            if (page.image_url) {
+                document.getElementById('page-image').src = page.image_url;
+            }
+            
+            // Show page text directly from results
+            if (page.text) {
+                document.getElementById('page-text-output').textContent = page.text;
+            }
+            return;
+        }
+    }
+    
+    // Fallback to processing data if available
+    const pageData = lastProcessingData && lastProcessingData.pages ? lastProcessingData.pages[pageNum] : null;
+    if (!pageData) return;
+    
+    // For processing data, we stored the text directly
+    if (pageData.text) {
+        document.getElementById('page-text-output').textContent = pageData.text;
     }
 }
 
-function displayPage(pageNumber) {
-    const page = ocrResults.pages.find(p => p.page_number == pageNumber);
-    if (page) {
-        // Convert markdown to HTML
-        const html = marked.parse(page.text);
-        textOutput.innerHTML = html;
-        
-        // Highlight code blocks
-        textOutput.querySelectorAll('pre code').forEach(block => {
-            hljs.highlightElement(block);
-        });
+// Utility functions
+function showSection(sectionName) {
+    document.querySelectorAll('section').forEach(section => {
+        section.classList.add('hidden');
+    });
+    
+    const targetSection = document.getElementById(`${sectionName}-section`);
+    if (targetSection) {
+        targetSection.classList.remove('hidden');
     }
+    
+    // Hide error message too
+    document.getElementById('error-message').classList.add('hidden');
 }
 
-function displayImage(pageNumber) {
-    // Use the actual image_url from the API response instead of hardcoded /images/ path
-    const page = ocrResults?.pages?.find(p => p.page_number === pageNumber);
-    if (page && page.image_url) {
-        imageOutput.innerHTML = `<img src="${page.image_url}" alt="Page ${pageNumber}">`;
-    } else {
-        imageOutput.innerHTML = `<p>Image not available for page ${pageNumber}</p>`;
-    }
+function showError(message) {
+    const errorDiv = document.getElementById('error-message');
+    document.getElementById('error-text').textContent = message;
+    errorDiv.classList.remove('hidden');
+    
+    // Hide all sections
+    document.querySelectorAll('section').forEach(section => {
+        section.classList.add('hidden');
+    });
 }
 
-function displayMetadata() {
-    const metadata = {
-        filename: ocrResults.filename,
-        total_pages: ocrResults.total_pages,
-        processing_time: `${ocrResults.processing_time.toFixed(2)}s`,
-        created_at: new Date(ocrResults.created_at).toLocaleString(),
-        ...ocrResults.metadata
-    };
-    
-    metadataOutput.textContent = JSON.stringify(metadata, null, 2);
+function resetInterface() {
+    currentJobId = null;
+    currentSessionId = null;
+    lastProcessingData = null;
+    
+    if (pollingInterval) {
+        clearInterval(pollingInterval);
+        pollingInterval = null;
+    }
+    
+    showSection('upload');
+    document.getElementById('file-input').value = '';
 }
 
-// Tab Switching
+// Tab switching
 function switchTab(tabName) {
-    // Update tab buttons
     document.querySelectorAll('.tab-btn').forEach(btn => {
         btn.classList.toggle('active', btn.dataset.tab === tabName);
     });
     
-    // Update tab content
     document.querySelectorAll('.tab-content').forEach(content => {
         content.classList.toggle('active', content.id === `${tabName}-content`);
     });
 }
 
-// Download Functions
-function downloadFile(type) {
-    if (!currentSession) return;
+// Download functions
+async function downloadMarkdown() {
+    if (!currentSessionId) return;
     
-    let url;
-    if (type === 'markdown') {
-        url = `/results/${currentSession}/combined.md`;
-    } else {
-        url = `/download/${currentSession}`;
+    try {
+        const response = await fetch(`${API_BASE}/api/sessions/${currentSessionId}/download/markdown`);
+        if (response.ok) {
+            const blob = await response.blob();
+            const url = window.URL.createObjectURL(blob);
+            const a = document.createElement('a');
+            a.href = url;
+            a.download = `ocr_results_${currentSessionId}.md`;
+            a.click();
+            window.URL.revokeObjectURL(url);
+        }
+    } catch (error) {
+        showError('Download failed: ' + error.message);
     }
-    
-    // Create temporary link and click it
-    const link = document.createElement('a');
-    link.href = url;
-    link.download = '';
-    document.body.appendChild(link);
-    link.click();
-    document.body.removeChild(link);
 }
 
-// Copy to Clipboard
-async function copyTextToClipboard() {
-    const currentPage = pageSelect.value;
-    const page = ocrResults.pages.find(p => p.page_number == currentPage);
-    
-    if (page) {
-        try {
-            await navigator.clipboard.writeText(page.text);
-            
-            // Show feedback
-            const originalHTML = copyText.innerHTML;
-            copyText.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><polyline points="20 6 9 17 4 12"></polyline></svg>';
-            copyText.style.color = 'var(--success-color)';
-            
-            setTimeout(() => {
-                copyText.innerHTML = originalHTML;
-                copyText.style.color = '';
-            }, 2000);
-            
-        } catch (error) {
-            console.error('Failed to copy:', error);
+async function downloadAll() {
+    if (!currentSessionId) return;
+    
+    try {
+        const response = await fetch(`${API_BASE}/api/sessions/${currentSessionId}/download/all`);
+        if (response.ok) {
+            const blob = await response.blob();
+            const url = window.URL.createObjectURL(blob);
+            const a = document.createElement('a');
+            a.href = url;
+            a.download = `ocr_results_${currentSessionId}.zip`;
+            a.click();
+            window.URL.revokeObjectURL(url);
         }
+    } catch (error) {
+        showError('Download failed: ' + error.message);
     }
 }
 
-// Progress Updates
-function updateProgress(percent, message, currentPage = null, totalPages = null, chunkInfo = null) {
-    progressFill.style.width = `${percent}%`;
-    progressPercent.textContent = `${Math.round(percent)}%`;
-    progressMessage.textContent = message;
-    
-    if (currentPage && totalPages) {
-        progressPages.textContent = `Page ${currentPage} of ${totalPages}`;
-        progressDetails.textContent = '';
-    } else if (chunkInfo) {
-        progressPages.textContent = chunkInfo;
-        progressDetails.textContent = '';
-    } else {
-        progressPages.textContent = '';
-        progressDetails.textContent = '';
-    }
+// Drag and drop handlers
+function handleDragOver(e) {
+    e.preventDefault();
+    e.currentTarget.classList.add('dragover');
 }
 
-// Section Management
-function showSection(section) {
-    // Hide all sections
-    uploadSection.classList.add('hidden');
-    progressSection.classList.add('hidden');
-    resultsSection.classList.add('hidden');
-    errorMessage.classList.add('hidden');
-    
-    // Show requested section
-    switch (section) {
-        case 'upload':
-            uploadSection.classList.remove('hidden');
-            break;
-        case 'progress':
-            progressSection.classList.remove('hidden');
-            break;
-        case 'results':
-            resultsSection.classList.remove('hidden');
-            break;
-    }
+function handleDragLeave(e) {
+    e.currentTarget.classList.remove('dragover');
 }
 
-// Error Handling
-function showError(message) {
-    errorMessage.classList.remove('hidden');
-    document.getElementById('error-text').textContent = message;
+function handleDrop(e) {
+    e.preventDefault();
+    e.currentTarget.classList.remove('dragover');
     
-    // Hide other sections
-    uploadSection.classList.add('hidden');
-    progressSection.classList.add('hidden');
-    resultsSection.classList.add('hidden');
-}
-
-// Reset
-function resetToUpload() {
-    // Clear state
-    currentSession = null;
-    ocrResults = null;
-    currentUploadSession = null;
-    uploadPaused = false;
-    statusCheckFailureCount = 0; // Reset failure count
-    
-    if (statusCheckInterval) {
-        clearInterval(statusCheckInterval);
+    const files = e.dataTransfer.files;
+    if (files.length > 0) {
+        uploadFile(files[0]);
     }
-    
-    // WebSocket cleanup removed - using polling only
-    
-    // Reset file input
-    fileInput.value = '';
-    
-    // Show upload section
-    showSection('upload');
 }
 
-
-// Logging Functions - only log errors in client
-function logError(message, context = {}) {
-    console.error('[ERROR]', message, context);
+// Preview page (when clicking on page grid)
+function previewPage(pageNum) {
+    const pageData = lastProcessingData.pages[pageNum];
+    if (!pageData || !pageData.image) return;
+    
+    // Update live preview with selected page
+    const preview = document.getElementById('live-preview');
+    preview.classList.remove('hidden');
+    
+    const imageUrl = `${API_BASE}/api/sessions/${currentSessionId}/files/${pageData.image}`;
+    document.getElementById('current-page-image').src = imageUrl;
+    
+    // If page has results, show text too
+    if (pageData.result_file) {
+        fetch(`${API_BASE}/api/sessions/${currentSessionId}/files/${pageData.result_file}`)
+            .then(response => response.text())
+            .then(text => {
+                document.getElementById('page-text-content').textContent = text;
+                document.getElementById('current-page-text').classList.remove('hidden');
+            })
+            .catch(console.error);
+    }
 }
 
-// Initialize on page load
-document.addEventListener('DOMContentLoaded', function() {
-    // Check model status immediately
-    checkModelStatus();
+// Copy page text functionality
+document.getElementById('copy-page-text').addEventListener('click', async () => {
+    const pageNum = document.getElementById('page-select').value;
+    const pageText = document.getElementById('page-text-output').textContent;
     
-    // Job system allows uploads even when model is loading
-    // Jobs are queued until model is ready
+    try {
+        await navigator.clipboard.writeText(pageText);
+        
+        // Visual feedback
+        const btn = document.getElementById('copy-page-text');
+        const originalTitle = btn.title;
+        btn.title = 'Copied!';
+        btn.style.color = 'var(--success-color)';
+        
+        setTimeout(() => {
+            btn.title = originalTitle;
+            btn.style.color = '';
+        }, 2000);
+    } catch (error) {
+        console.error('Failed to copy:', error);
+    }
 });
diff --git a/app/static/style.css b/app/static/style.css
index d1e93be..54b9470 100644
--- a/app/static/style.css
+++ b/app/static/style.css
@@ -1,563 +1,862 @@
-/* Global Styles */
-:root {
-    --primary-color: #2563eb;
-    --primary-hover: #1d4ed8;
-    --secondary-color: #64748b;
-    --secondary-hover: #475569;
-    --success-color: #10b981;
-    --error-color: #ef4444;
-    --warning-color: #f59e0b;
-    --bg-primary: #ffffff;
-    --bg-secondary: #f8fafc;
-    --bg-tertiary: #e2e8f0;
-    --text-primary: #1e293b;
-    --text-secondary: #64748b;
-    --border-color: #e2e8f0;
-    --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
-    --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
-    --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
-}
-
-* {
-    margin: 0;
-    padding: 0;
-    box-sizing: border-box;
-}
-
-body {
-    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
-    background-color: var(--bg-secondary);
-    color: var(--text-primary);
-    line-height: 1.6;
-}
-
-.container {
-    min-height: 100vh;
-    display: flex;
-    flex-direction: column;
-}
-
-/* Header */
-header {
-    background-color: var(--bg-primary);
-    border-bottom: 1px solid var(--border-color);
-    padding: 1.5rem 0;
-    box-shadow: var(--shadow-sm);
-}
-
-header h1 {
-    text-align: center;
-    font-size: 2rem;
-    font-weight: 700;
-    color: var(--primary-color);
-    margin-bottom: 0.25rem;
-}
-
-header p {
-    text-align: center;
-    color: var(--text-secondary);
-    font-size: 0.875rem;
-}
-
-/* Model Status Banner */
-.model-status {
-    background-color: var(--warning-color);
-    color: white;
-    padding: 0.75rem 1rem;
-    text-align: center;
-    transition: all 0.3s ease;
-}
-
-.model-status.ready {
-    background-color: var(--success-color);
-}
-
-.model-status.error {
-    background-color: var(--error-color);
-}
-
-.model-status-content {
-    max-width: 1200px;
-    margin: 0 auto;
-    display: flex;
-    align-items: center;
-    justify-content: center;
-    gap: 1rem;
-    flex-wrap: wrap;
-}
-
-.model-progress {
-    display: flex;
-    align-items: center;
-    gap: 0.5rem;
-}
-
-.progress-bar {
-    width: 200px;
-    height: 20px;
-    background-color: rgba(255, 255, 255, 0.3);
-    border-radius: 10px;
-    overflow: hidden;
-}
-
-.progress-fill {
-    height: 100%;
-    background-color: white;
-    transition: width 0.3s ease;
-}
-
-.progress-text {
-    font-size: 0.875rem;
-    font-weight: 600;
-}
-
-.btn-sm {
-    padding: 0.25rem 0.75rem;
-    font-size: 0.875rem;
-}
-
-/* Main Content */
-main {
-    flex: 1;
-    max-width: 1200px;
-    width: 100%;
-    margin: 0 auto;
-    padding: 2rem;
-}
-
-/* Upload Section */
-.upload-section {
-    background-color: var(--bg-primary);
-    border-radius: 0.75rem;
-    padding: 3rem;
-    box-shadow: var(--shadow-md);
-}
-
-.upload-area {
-    border: 2px dashed var(--border-color);
-    border-radius: 0.5rem;
-    padding: 3rem;
-    text-align: center;
-    transition: all 0.3s ease;
-    cursor: pointer;
-}
-
-.upload-area:hover {
-    border-color: var(--primary-color);
-    background-color: var(--bg-secondary);
-}
-
-.upload-area.dragover {
-    border-color: var(--primary-color);
-    background-color: #eff6ff;
-    transform: scale(1.02);
-}
-
-.upload-area.disabled {
-    opacity: 0.5;
-    pointer-events: none;
-    cursor: not-allowed;
-}
-
-.upload-icon {
-    width: 4rem;
-    height: 4rem;
-    color: var(--text-secondary);
-    margin-bottom: 1rem;
-}
-
-.upload-area h2 {
-    font-size: 1.5rem;
-    margin-bottom: 0.5rem;
-    color: var(--text-primary);
-}
-
-.upload-area p {
-    color: var(--text-secondary);
-    margin-bottom: 1.5rem;
-}
-
-/* Buttons */
-.btn-primary, .btn-secondary, .btn-icon {
-    border: none;
-    padding: 0.75rem 1.5rem;
-    border-radius: 0.375rem;
-    font-size: 1rem;
-    font-weight: 500;
-    cursor: pointer;
-    transition: all 0.2s ease;
-    display: inline-flex;
-    align-items: center;
-    gap: 0.5rem;
-}
-
-.btn-primary {
-    background-color: var(--primary-color);
-    color: white;
-}
-
-.btn-primary:hover {
-    background-color: var(--primary-hover);
-    transform: translateY(-1px);
-    box-shadow: var(--shadow-md);
-}
-
-.btn-secondary {
-    background-color: var(--secondary-color);
-    color: white;
-}
-
-.btn-secondary:hover {
-    background-color: var(--secondary-hover);
-}
-
-.btn-icon {
-    padding: 0.5rem;
-    background-color: transparent;
-    color: var(--text-secondary);
-}
-
-.btn-icon:hover {
-    background-color: var(--bg-tertiary);
-    color: var(--text-primary);
-}
-
-.btn-icon svg {
-    width: 1.25rem;
-    height: 1.25rem;
-}
-
-/* Progress Section */
-.progress-section {
-    background-color: var(--bg-primary);
-    border-radius: 0.75rem;
-    padding: 2rem;
-    box-shadow: var(--shadow-md);
-}
-
-.progress-info {
-    margin-bottom: 1.5rem;
-}
-
-.progress-info h2 {
-    font-size: 1.5rem;
-    margin-bottom: 0.5rem;
-}
-
-.progress-info p {
-    color: var(--text-secondary);
-}
-
-.progress-bar {
-    height: 0.5rem;
-    background-color: var(--bg-tertiary);
-    border-radius: 0.25rem;
-    overflow: hidden;
-    margin-bottom: 1rem;
-}
-
-.progress-fill {
-    height: 100%;
-    background-color: var(--primary-color);
-    transition: width 0.3s ease;
-    width: 0;
-}
-
-.progress-stats {
-    display: flex;
-    justify-content: space-between;
-    font-size: 0.875rem;
-    color: var(--text-secondary);
-}
-
-/* Results Section */
-.results-section {
-    background-color: var(--bg-primary);
-    border-radius: 0.75rem;
-    padding: 2rem;
-    box-shadow: var(--shadow-md);
-}
-
-.results-header {
-    display: flex;
-    justify-content: space-between;
-    align-items: center;
-    margin-bottom: 1.5rem;
-    flex-wrap: wrap;
-    gap: 1rem;
-}
-
-.results-header h2 {
-    font-size: 1.5rem;
-}
-
-.results-actions {
-    display: flex;
-    gap: 0.75rem;
-    flex-wrap: wrap;
-}
-
-/* Tabs */
-.results-tabs {
-    display: flex;
-    gap: 0.5rem;
-    border-bottom: 2px solid var(--border-color);
-    margin-bottom: 1.5rem;
-}
-
-.tab-btn {
-    padding: 0.75rem 1.5rem;
-    background: none;
-    border: none;
-    color: var(--text-secondary);
-    font-weight: 500;
-    cursor: pointer;
-    border-bottom: 2px solid transparent;
-    transition: all 0.2s ease;
-}
-
-.tab-btn:hover {
-    color: var(--text-primary);
-}
-
-.tab-btn.active {
-    color: var(--primary-color);
-    border-bottom-color: var(--primary-color);
-}
-
-.tab-content {
-    display: none;
-}
-
-.tab-content.active {
-    display: block;
-}
-
-/* Page Navigation */
-.page-navigation {
-    display: flex;
-    align-items: center;
-    gap: 1rem;
-    margin-bottom: 1rem;
-}
-
-.page-navigation select {
-    padding: 0.5rem 1rem;
-    border: 1px solid var(--border-color);
-    border-radius: 0.375rem;
-    background-color: var(--bg-primary);
-    font-size: 0.875rem;
-}
-
-/* Text Output */
-.text-output {
-    background-color: var(--bg-secondary);
-    border: 1px solid var(--border-color);
-    border-radius: 0.5rem;
-    padding: 1.5rem;
-    max-height: 600px;
-    overflow-y: auto;
-    font-family: 'Consolas', 'Monaco', monospace;
-    font-size: 0.875rem;
-    line-height: 1.6;
-}
-
-.text-output pre {
-    white-space: pre-wrap;
-    word-wrap: break-word;
-}
-
-.text-output h1, .text-output h2, .text-output h3 {
-    margin-top: 1.5rem;
-    margin-bottom: 0.75rem;
-}
-
-.text-output h1:first-child, 
-.text-output h2:first-child, 
-.text-output h3:first-child {
-    margin-top: 0;
-}
-
-.text-output code {
-    background-color: var(--bg-tertiary);
-    padding: 0.125rem 0.375rem;
-    border-radius: 0.25rem;
-    font-size: 0.85em;
-}
-
-.text-output pre code {
-    display: block;
-    padding: 1rem;
-    overflow-x: auto;
-}
-
-/* Image Output */
-.image-output {
-    text-align: center;
-}
-
-.image-output img {
-    max-width: 100%;
-    height: auto;
-    border-radius: 0.5rem;
-    box-shadow: var(--shadow-lg);
-}
-
-/* Metadata Output */
-#metadata-output {
-    background-color: var(--bg-secondary);
-    border: 1px solid var(--border-color);
-    border-radius: 0.5rem;
-    padding: 1.5rem;
-    overflow-x: auto;
-    font-family: 'Consolas', 'Monaco', monospace;
-    font-size: 0.875rem;
-}
-
-/* Error Message */
-.error-message {
-    background-color: #fef2f2;
-    border: 1px solid #fecaca;
-    border-radius: 0.5rem;
-    padding: 1.5rem;
-    text-align: center;
-    margin-top: 2rem;
-}
-
-.error-message svg {
-    width: 3rem;
-    height: 3rem;
-    color: var(--error-color);
-    margin-bottom: 1rem;
-}
-
-.error-message p {
-    color: var(--error-color);
-    margin-bottom: 1rem;
-    font-weight: 500;
-}
-
-/* Footer */
-footer {
-    background-color: var(--bg-primary);
-    border-top: 1px solid var(--border-color);
-    padding: 1.5rem 0;
-    text-align: center;
-    font-size: 0.875rem;
-    color: var(--text-secondary);
-}
-
-footer a {
-    color: var(--primary-color);
-    text-decoration: none;
-}
-
-footer a:hover {
-    text-decoration: underline;
-}
-
-/* Utility Classes */
-.hidden {
-    display: none !important;
-}
-
-/* Loading Animation */
-@keyframes pulse {
-    0%, 100% {
-        opacity: 1;
-    }
-    50% {
-        opacity: 0.5;
-    }
-}
-
-.loading {
-    animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
-}
-
-/* Scrollbar Styling */
-.text-output::-webkit-scrollbar,
-#metadata-output::-webkit-scrollbar {
-    width: 8px;
-}
-
-.text-output::-webkit-scrollbar-track,
-#metadata-output::-webkit-scrollbar-track {
-    background: var(--bg-secondary);
-}
-
-.text-output::-webkit-scrollbar-thumb,
-#metadata-output::-webkit-scrollbar-thumb {
-    background: var(--border-color);
-    border-radius: 4px;
-}
-
-.text-output::-webkit-scrollbar-thumb:hover,
-#metadata-output::-webkit-scrollbar-thumb:hover {
-    background: var(--text-secondary);
-}
-
-/* Responsive Design */
-@media (max-width: 768px) {
-    main {
-        padding: 1rem;
-    }
-    
-    .upload-section,
-    .progress-section,
-    .results-section {
-        padding: 1.5rem;
-    }
-    
-    .upload-area {
-        padding: 2rem;
-    }
-    
-    .upload-icon {
-        width: 3rem;
-        height: 3rem;
-    }
-    
-    .results-header {
-        flex-direction: column;
-        align-items: flex-start;
-    }
-    
-    .results-tabs {
-        overflow-x: auto;
-        -webkit-overflow-scrolling: touch;
-    }
-    
-    .tab-btn {
-        white-space: nowrap;
-    }
-}
-
-/* Dark Mode Support */
-@media (prefers-color-scheme: dark) {
-    :root {
-        --bg-primary: #1e293b;
-        --bg-secondary: #0f172a;
-        --bg-tertiary: #334155;
-        --text-primary: #f1f5f9;
-        --text-secondary: #94a3b8;
-        --border-color: #334155;
-    }
-    
-    .upload-area:hover {
-        background-color: var(--bg-tertiary);
-    }
-    
-    .upload-area.dragover {
-        background-color: #1e3a8a;
-    }
-    
-    .error-message {
-        background-color: #7f1d1d;
-        border-color: #991b1b;
-    }
-    
-    .text-output code {
-        background-color: var(--bg-tertiary);
-    }
+/* Global Styles */
+:root {
+    --primary-color: #2563eb;
+    --primary-hover: #1d4ed8;
+    --secondary-color: #64748b;
+    --secondary-hover: #475569;
+    --success-color: #10b981;
+    --error-color: #ef4444;
+    --warning-color: #f59e0b;
+    --bg-primary: #ffffff;
+    --bg-secondary: #f8fafc;
+    --bg-tertiary: #e2e8f0;
+    --text-primary: #1e293b;
+    --text-secondary: #64748b;
+    --border-color: #e2e8f0;
+    --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
+    --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
+    --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
+}
+
+* {
+    margin: 0;
+    padding: 0;
+    box-sizing: border-box;
+}
+
+body {
+    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
+    background-color: var(--bg-secondary);
+    color: var(--text-primary);
+    line-height: 1.6;
+}
+
+.container {
+    min-height: 100vh;
+    display: flex;
+    flex-direction: column;
+}
+
+/* Header */
+header {
+    background-color: var(--bg-primary);
+    border-bottom: 1px solid var(--border-color);
+    padding: 1.5rem 0;
+    box-shadow: var(--shadow-sm);
+}
+
+header h1 {
+    text-align: center;
+    font-size: 2rem;
+    font-weight: 700;
+    color: var(--primary-color);
+    margin-bottom: 0.25rem;
+}
+
+header p {
+    text-align: center;
+    color: var(--text-secondary);
+    font-size: 0.875rem;
+}
+
+/* Model Status Banner */
+.model-status {
+    background-color: var(--warning-color);
+    color: white;
+    padding: 0.75rem 1rem;
+    text-align: center;
+    transition: all 0.3s ease;
+}
+
+.model-status.ready {
+    background-color: var(--success-color);
+}
+
+.model-status.error {
+    background-color: var(--error-color);
+}
+
+.model-status-content {
+    max-width: 1200px;
+    margin: 0 auto;
+    display: flex;
+    align-items: center;
+    justify-content: center;
+    gap: 1rem;
+    flex-wrap: wrap;
+}
+
+.model-progress {
+    display: flex;
+    align-items: center;
+    gap: 0.5rem;
+}
+
+.progress-bar {
+    width: 200px;
+    height: 20px;
+    background-color: rgba(255, 255, 255, 0.3);
+    border-radius: 10px;
+    overflow: hidden;
+}
+
+.progress-fill {
+    height: 100%;
+    background-color: white;
+    transition: width 0.3s ease;
+}
+
+.progress-text {
+    font-size: 0.875rem;
+    font-weight: 600;
+}
+
+.btn-sm {
+    padding: 0.25rem 0.75rem;
+    font-size: 0.875rem;
+}
+
+/* Main Content */
+main {
+    flex: 1;
+    max-width: 1200px;
+    width: 100%;
+    margin: 0 auto;
+    padding: 2rem;
+}
+
+/* Upload Section */
+.upload-section {
+    background-color: var(--bg-primary);
+    border-radius: 0.75rem;
+    padding: 3rem;
+    box-shadow: var(--shadow-md);
+}
+
+.upload-area {
+    border: 2px dashed var(--border-color);
+    border-radius: 0.5rem;
+    padding: 3rem;
+    text-align: center;
+    transition: all 0.3s ease;
+    cursor: pointer;
+}
+
+.upload-area:hover {
+    border-color: var(--primary-color);
+    background-color: var(--bg-secondary);
+}
+
+.upload-area.dragover {
+    border-color: var(--primary-color);
+    background-color: #eff6ff;
+    transform: scale(1.02);
+}
+
+.upload-area.disabled {
+    opacity: 0.5;
+    pointer-events: none;
+    cursor: not-allowed;
+}
+
+.upload-icon {
+    width: 4rem;
+    height: 4rem;
+    color: var(--text-secondary);
+    margin-bottom: 1rem;
+}
+
+.upload-area h2 {
+    font-size: 1.5rem;
+    margin-bottom: 0.5rem;
+    color: var(--text-primary);
+}
+
+.upload-area p {
+    color: var(--text-secondary);
+    margin-bottom: 1.5rem;
+}
+
+/* Buttons */
+.btn-primary, .btn-secondary, .btn-icon {
+    border: none;
+    padding: 0.75rem 1.5rem;
+    border-radius: 0.375rem;
+    font-size: 1rem;
+    font-weight: 500;
+    cursor: pointer;
+    transition: all 0.2s ease;
+    display: inline-flex;
+    align-items: center;
+    gap: 0.5rem;
+}
+
+.btn-primary {
+    background-color: var(--primary-color);
+    color: white;
+}
+
+.btn-primary:hover {
+    background-color: var(--primary-hover);
+    transform: translateY(-1px);
+    box-shadow: var(--shadow-md);
+}
+
+.btn-secondary {
+    background-color: var(--secondary-color);
+    color: white;
+}
+
+.btn-secondary:hover {
+    background-color: var(--secondary-hover);
+}
+
+.btn-icon {
+    padding: 0.5rem;
+    background-color: transparent;
+    color: var(--text-secondary);
+}
+
+.btn-icon:hover {
+    background-color: var(--bg-tertiary);
+    color: var(--text-primary);
+}
+
+.btn-icon svg {
+    width: 1.25rem;
+    height: 1.25rem;
+}
+
+/* Progress Section */
+.progress-section {
+    background-color: var(--bg-primary);
+    border-radius: 0.75rem;
+    padding: 2rem;
+    box-shadow: var(--shadow-md);
+}
+
+.progress-info {
+    margin-bottom: 1.5rem;
+}
+
+.progress-info h2 {
+    font-size: 1.5rem;
+    margin-bottom: 0.5rem;
+}
+
+.progress-info p {
+    color: var(--text-secondary);
+}
+
+.progress-bar {
+    height: 0.5rem;
+    background-color: var(--bg-tertiary);
+    border-radius: 0.25rem;
+    overflow: hidden;
+    margin-bottom: 1rem;
+}
+
+.progress-fill {
+    height: 100%;
+    background-color: var(--primary-color);
+    transition: width 0.3s ease;
+    width: 0;
+}
+
+.progress-stats {
+    display: flex;
+    justify-content: space-between;
+    font-size: 0.875rem;
+    color: var(--text-secondary);
+}
+
+/* Results Section */
+.results-section {
+    background-color: var(--bg-primary);
+    border-radius: 0.75rem;
+    padding: 2rem;
+    box-shadow: var(--shadow-md);
+}
+
+.results-header {
+    display: flex;
+    justify-content: space-between;
+    align-items: center;
+    margin-bottom: 1.5rem;
+    flex-wrap: wrap;
+    gap: 1rem;
+}
+
+.results-header h2 {
+    font-size: 1.5rem;
+}
+
+.results-actions {
+    display: flex;
+    gap: 0.75rem;
+    flex-wrap: wrap;
+}
+
+/* Tabs */
+.results-tabs {
+    display: flex;
+    gap: 0.5rem;
+    border-bottom: 2px solid var(--border-color);
+    margin-bottom: 1.5rem;
+}
+
+.tab-btn {
+    padding: 0.75rem 1.5rem;
+    background: none;
+    border: none;
+    color: var(--text-secondary);
+    font-weight: 500;
+    cursor: pointer;
+    border-bottom: 2px solid transparent;
+    transition: all 0.2s ease;
+}
+
+.tab-btn:hover {
+    color: var(--text-primary);
+}
+
+.tab-btn.active {
+    color: var(--primary-color);
+    border-bottom-color: var(--primary-color);
+}
+
+.tab-content {
+    display: none;
+}
+
+.tab-content.active {
+    display: block;
+}
+
+/* Page Navigation */
+.page-navigation {
+    display: flex;
+    align-items: center;
+    gap: 1rem;
+    margin-bottom: 1rem;
+}
+
+.page-navigation select {
+    padding: 0.5rem 1rem;
+    border: 1px solid var(--border-color);
+    border-radius: 0.375rem;
+    background-color: var(--bg-primary);
+    font-size: 0.875rem;
+}
+
+/* Text Output */
+.text-output {
+    background-color: var(--bg-secondary);
+    border: 1px solid var(--border-color);
+    border-radius: 0.5rem;
+    padding: 1.5rem;
+    max-height: 600px;
+    overflow-y: auto;
+    font-family: 'Consolas', 'Monaco', monospace;
+    font-size: 0.875rem;
+    line-height: 1.6;
+}
+
+.text-output pre {
+    white-space: pre-wrap;
+    word-wrap: break-word;
+}
+
+.text-output h1, .text-output h2, .text-output h3 {
+    margin-top: 1.5rem;
+    margin-bottom: 0.75rem;
+}
+
+.text-output h1:first-child, 
+.text-output h2:first-child, 
+.text-output h3:first-child {
+    margin-top: 0;
+}
+
+.text-output code {
+    background-color: var(--bg-tertiary);
+    padding: 0.125rem 0.375rem;
+    border-radius: 0.25rem;
+    font-size: 0.85em;
+}
+
+.text-output pre code {
+    display: block;
+    padding: 1rem;
+    overflow-x: auto;
+}
+
+/* Image Output */
+.image-output {
+    text-align: center;
+}
+
+.image-output img {
+    max-width: 100%;
+    height: auto;
+    border-radius: 0.5rem;
+    box-shadow: var(--shadow-lg);
+}
+
+/* Metadata Output */
+#metadata-output {
+    background-color: var(--bg-secondary);
+    border: 1px solid var(--border-color);
+    border-radius: 0.5rem;
+    padding: 1.5rem;
+    overflow-x: auto;
+    font-family: 'Consolas', 'Monaco', monospace;
+    font-size: 0.875rem;
+}
+
+/* Error Message */
+.error-message {
+    background-color: #fef2f2;
+    border: 1px solid #fecaca;
+    border-radius: 0.5rem;
+    padding: 1.5rem;
+    text-align: center;
+    margin-top: 2rem;
+}
+
+.error-message svg {
+    width: 3rem;
+    height: 3rem;
+    color: var(--error-color);
+    margin-bottom: 1rem;
+}
+
+.error-message p {
+    color: var(--error-color);
+    margin-bottom: 1rem;
+    font-weight: 500;
+}
+
+/* Footer */
+footer {
+    background-color: var(--bg-primary);
+    border-top: 1px solid var(--border-color);
+    padding: 1.5rem 0;
+    text-align: center;
+    font-size: 0.875rem;
+    color: var(--text-secondary);
+}
+
+footer a {
+    color: var(--primary-color);
+    text-decoration: none;
+}
+
+footer a:hover {
+    text-decoration: underline;
+}
+
+/* Utility Classes */
+.hidden {
+    display: none !important;
+}
+
+/* Loading Animation */
+@keyframes pulse {
+    0%, 100% {
+        opacity: 1;
+    }
+    50% {
+        opacity: 0.5;
+    }
+}
+
+.loading {
+    animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
+}
+
+/* Scrollbar Styling */
+.text-output::-webkit-scrollbar,
+#metadata-output::-webkit-scrollbar {
+    width: 8px;
+}
+
+.text-output::-webkit-scrollbar-track,
+#metadata-output::-webkit-scrollbar-track {
+    background: var(--bg-secondary);
+}
+
+.text-output::-webkit-scrollbar-thumb,
+#metadata-output::-webkit-scrollbar-thumb {
+    background: var(--border-color);
+    border-radius: 4px;
+}
+
+.text-output::-webkit-scrollbar-thumb:hover,
+#metadata-output::-webkit-scrollbar-thumb:hover {
+    background: var(--text-secondary);
+}
+
+/* Responsive Design */
+@media (max-width: 768px) {
+    main {
+        padding: 1rem;
+    }
+    
+    .upload-section,
+    .progress-section,
+    .results-section {
+        padding: 1.5rem;
+    }
+    
+    .upload-area {
+        padding: 2rem;
+    }
+    
+    .upload-icon {
+        width: 3rem;
+        height: 3rem;
+    }
+    
+    .results-header {
+        flex-direction: column;
+        align-items: flex-start;
+    }
+    
+    .results-tabs {
+        overflow-x: auto;
+        -webkit-overflow-scrolling: touch;
+    }
+    
+    .tab-btn {
+        white-space: nowrap;
+    }
+}
+
+/* Progress Card Styling */
+.progress-card {
+    background: var(--bg-primary);
+    border-radius: 1rem;
+    padding: 2.5rem;
+    box-shadow: var(--shadow-lg);
+}
+
+/* Stage Indicator */
+.stage-indicator {
+    display: flex;
+    align-items: center;
+    justify-content: center;
+    margin-bottom: 2rem;
+    gap: 0;
+}
+
+.stage {
+    display: flex;
+    flex-direction: column;
+    align-items: center;
+    gap: 0.5rem;
+    opacity: 0.3;
+    transition: all 0.3s ease;
+}
+
+.stage.active {
+    opacity: 1;
+}
+
+.stage.completed {
+    opacity: 1;
+}
+
+.stage-icon {
+    width: 3rem;
+    height: 3rem;
+    background: var(--bg-tertiary);
+    border-radius: 50%;
+    display: flex;
+    align-items: center;
+    justify-content: center;
+    font-size: 1.5rem;
+    transition: all 0.3s ease;
+}
+
+.stage.active .stage-icon {
+    background: var(--primary-color);
+    color: white;
+    transform: scale(1.1);
+}
+
+.stage.completed .stage-icon {
+    background: var(--success-color);
+    color: white;
+}
+
+.stage-label {
+    font-size: 0.875rem;
+    font-weight: 500;
+    color: var(--text-secondary);
+}
+
+.stage-connector {
+    width: 4rem;
+    height: 2px;
+    background: var(--border-color);
+    margin: 0 0.5rem;
+    margin-bottom: 2rem;
+}
+
+/* Large Progress Bar */
+.progress-container {
+    margin-bottom: 2rem;
+}
+
+.progress-bar-large {
+    height: 1.5rem;
+    background: var(--bg-tertiary);
+    border-radius: 0.75rem;
+    overflow: hidden;
+    margin-bottom: 1rem;
+}
+
+.progress-fill-large {
+    height: 100%;
+    background: linear-gradient(90deg, var(--primary-color) 0%, var(--primary-hover) 100%);
+    transition: width 0.5s ease;
+    position: relative;
+    overflow: hidden;
+}
+
+.progress-fill-large::after {
+    content: '';
+    position: absolute;
+    top: 0;
+    left: 0;
+    right: 0;
+    bottom: 0;
+    background: linear-gradient(
+        90deg,
+        transparent 0%,
+        rgba(255, 255, 255, 0.2) 50%,
+        transparent 100%
+    );
+    animation: shimmer 2s infinite;
+}
+
+@keyframes shimmer {
+    0% { transform: translateX(-100%); }
+    100% { transform: translateX(100%); }
+}
+
+.progress-percent-large {
+    font-size: 2rem;
+    font-weight: 700;
+    color: var(--primary-color);
+}
+
+.progress-message {
+    font-size: 1.125rem;
+    color: var(--text-secondary);
+}
+
+/* Page Grid */
+.page-grid-container {
+    margin-top: 2rem;
+    padding-top: 2rem;
+    border-top: 1px solid var(--border-color);
+}
+
+.page-grid {
+    display: grid;
+    grid-template-columns: repeat(auto-fill, minmax(80px, 1fr));
+    gap: 1rem;
+    margin-top: 1rem;
+}
+
+.page-item {
+    aspect-ratio: 1;
+    background: var(--bg-secondary);
+    border: 2px solid var(--border-color);
+    border-radius: 0.5rem;
+    display: flex;
+    flex-direction: column;
+    align-items: center;
+    justify-content: center;
+    position: relative;
+    transition: all 0.3s ease;
+    cursor: pointer;
+}
+
+.page-item.processing {
+    border-color: var(--primary-color);
+    background: var(--bg-primary);
+}
+
+.page-item.completed {
+    border-color: var(--success-color);
+    background: #10b98110;
+}
+
+.page-item.failed {
+    border-color: var(--error-color);
+    background: #ef444410;
+}
+
+.page-number {
+    font-size: 1.25rem;
+    font-weight: 600;
+    color: var(--text-primary);
+}
+
+.page-status-icon {
+    position: absolute;
+    bottom: 0.25rem;
+    right: 0.25rem;
+    width: 1.5rem;
+    height: 1.5rem;
+}
+
+/* Live Preview */
+.live-preview {
+    margin-top: 2rem;
+    padding-top: 2rem;
+    border-top: 1px solid var(--border-color);
+}
+
+.preview-content {
+    display: grid;
+    grid-template-columns: 1fr 1fr;
+    gap: 2rem;
+    margin-top: 1rem;
+}
+
+.current-page-image {
+    width: 100%;
+    height: auto;
+    border-radius: 0.5rem;
+    box-shadow: var(--shadow-md);
+}
+
+.current-page-text {
+    background: var(--bg-secondary);
+    border-radius: 0.5rem;
+    padding: 1rem;
+    overflow-y: auto;
+    max-height: 400px;
+}
+
+/* Results Page Display */
+.page-display {
+    display: grid;
+    grid-template-columns: 1fr 1fr;
+    gap: 2rem;
+    margin-top: 1rem;
+}
+
+.page-selector {
+    display: flex;
+    align-items: center;
+    gap: 1rem;
+    margin-bottom: 1rem;
+}
+
+.page-dropdown {
+    padding: 0.5rem 1rem;
+    border: 1px solid var(--border-color);
+    border-radius: 0.375rem;
+    background-color: var(--bg-primary);
+    font-size: 0.875rem;
+}
+
+.page-image-container {
+    background: var(--bg-secondary);
+    border-radius: 0.5rem;
+    padding: 1rem;
+    display: flex;
+    align-items: center;
+    justify-content: center;
+}
+
+.page-image {
+    max-width: 100%;
+    height: auto;
+    border-radius: 0.5rem;
+    box-shadow: var(--shadow-md);
+}
+
+.page-text-container {
+    background: var(--bg-secondary);
+    border-radius: 0.5rem;
+    padding: 1rem;
+    overflow-y: auto;
+    max-height: 600px;
+}
+
+.text-output-large {
+    background: var(--bg-secondary);
+    border-radius: 0.5rem;
+    padding: 2rem;
+    min-height: 400px;
+    max-height: 70vh;
+    overflow-y: auto;
+    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
+    line-height: 1.8;
+}
+
+.metadata-output {
+    background-color: var(--bg-secondary);
+    border: 1px solid var(--border-color);
+    border-radius: 0.5rem;
+    padding: 1.5rem;
+    overflow-x: auto;
+    font-family: 'Consolas', 'Monaco', monospace;
+    font-size: 0.875rem;
+}
+
+.icon {
+    width: 1.25rem;
+    height: 1.25rem;
+}
+
+/* Responsive Updates */
+@media (max-width: 768px) {
+    .preview-content,
+    .page-display {
+        grid-template-columns: 1fr;
+    }
+    
+    .stage-connector {
+        width: 2rem;
+    }
+    
+    .page-grid {
+        grid-template-columns: repeat(auto-fill, minmax(60px, 1fr));
+    }
+}
+
+/* Dark Mode Support */
+@media (prefers-color-scheme: dark) {
+    :root {
+        --bg-primary: #1e293b;
+        --bg-secondary: #0f172a;
+        --bg-tertiary: #334155;
+        --text-primary: #f1f5f9;
+        --text-secondary: #94a3b8;
+        --border-color: #334155;
+    }
+    
+    .upload-area:hover {
+        background-color: var(--bg-tertiary);
+    }
+    
+    .upload-area.dragover {
+        background-color: #1e3a8a;
+    }
+    
+    .error-message {
+        background-color: #7f1d1d;
+        border-color: #991b1b;
+    }
+    
+    .text-output code {
+        background-color: var(--bg-tertiary);
+    }
 }
\ No newline at end of file
diff --git a/app/storage_service.py b/app/storage_service.py
index 3c7edfc..7859cd2 100644
--- a/app/storage_service.py
+++ b/app/storage_service.py
@@ -176,7 +176,7 @@ class StorageService:
             logger.info(f"Saved file to GCS: {file_path}")
             
             # Force consistency check for critical files
-            if filename in ['metadata.json', 'status.json']:
+            if filename in ['processing.json']:
                 # Verify the file was written
                 if not blob.exists():
                     logger.warning(f"GCS consistency issue - file not immediately available: {file_path}")
@@ -360,11 +360,6 @@ class StorageService:
             'url': self.get_file_url(filename, session_hash)
         }
     
-    async def save_session_metadata(self, session_hash: str, metadata: Dict) -> str:
-        """Save session metadata"""
-        filename = "metadata.json"
-        content = json.dumps(metadata, indent=2)
-        return await self.save_file(content, filename, session_hash)
     
     # Session management
     async def create_session(self, initial_metadata: Optional[Dict] = None) -> str:
@@ -390,8 +385,7 @@ class StorageService:
         if initial_metadata:
             metadata.update(initial_metadata)
         
-        # Save metadata
-        await self.save_session_metadata(session_hash, metadata)
+        # Session metadata now handled by OCR service in processing.json
         
         logger.info(f"Session created successfully: {session_hash} at {self.get_session_path(session_hash)}")
         
@@ -409,11 +403,13 @@ class StorageService:
         
         for attempt in range(max_retries):
             try:
-                metadata_content = await self.get_file("metadata.json", session_hash)
-                metadata = json.loads(metadata_content)
-                stored_user_hash = metadata.get('user_hash')
+                processing_content = await self.get_file("processing.json", session_hash)
+                processing_data = json.loads(processing_content)
+                # For processing.json, user info is stored differently  
+                stored_user_email = processing_data.get('user_email', '')
+                stored_user_hash = hashlib.sha256(stored_user_email.encode()).hexdigest()[:12] if stored_user_email else ''
                 
-                logger.debug(f"Session metadata found: {session_hash}, stored_user={stored_user_hash}, current_user={self._user_hash}, match={stored_user_hash == self._user_hash}")
+                logger.debug(f"Session processing found: {session_hash}, stored_user={stored_user_hash}, current_user={self._user_hash}, match={stored_user_hash == self._user_hash}")
                 
                 return stored_user_hash == self._user_hash
             except FileNotFoundError:
diff --git a/app/templates/index.html b/app/templates/index.html
index 1869a7a..8ad1a9a 100644
--- a/app/templates/index.html
+++ b/app/templates/index.html
@@ -32,17 +32,58 @@
 
             <!-- Progress Section -->
             <section id="progress-section" class="progress-section hidden">
-                <h2>Processing Document</h2>
-                <div class="progress-info">
-                    <p id="progress-message">Uploading document...</p>
-                    <p id="progress-details"></p>
-                </div>
-                <div class="progress-bar">
-                    <div class="progress-fill" id="progress-fill"></div>
-                </div>
-                <div class="progress-stats">
-                    <span id="progress-percent">0%</span>
-                    <span id="progress-pages"></span>
+                <!-- Main Progress Card -->
+                <div class="progress-card">
+                    <h2 id="progress-title">Processing Document</h2>
+                    
+                    <!-- Stage Indicator -->
+                    <div class="stage-indicator">
+                        <div class="stage" data-stage="upload">
+                            <div class="stage-icon">📤</div>
+                            <div class="stage-label">Upload</div>
+                        </div>
+                        <div class="stage-connector"></div>
+                        <div class="stage" data-stage="extract">
+                            <div class="stage-icon">📄</div>
+                            <div class="stage-label">Extract</div>
+                        </div>
+                        <div class="stage-connector"></div>
+                        <div class="stage" data-stage="ocr">
+                            <div class="stage-icon">🔍</div>
+                            <div class="stage-label">OCR</div>
+                        </div>
+                    </div>
+                    
+                    <!-- Main Progress Bar -->
+                    <div class="progress-container">
+                        <div class="progress-bar-large">
+                            <div class="progress-fill-large" id="main-progress-fill"></div>
+                        </div>
+                        <div class="progress-stats">
+                            <span id="progress-percent" class="progress-percent-large">0%</span>
+                            <span id="progress-message" class="progress-message">Initializing...</span>
+                        </div>
+                    </div>
+                    
+                    <!-- Page Grid for PDFs -->
+                    <div id="page-grid-container" class="page-grid-container hidden">
+                        <h3>Page Processing Status</h3>
+                        <div id="page-grid" class="page-grid">
+                            <!-- Page items will be inserted here -->
+                        </div>
+                    </div>
+                    
+                    <!-- Live Preview -->
+                    <div id="live-preview" class="live-preview hidden">
+                        <h3>Current Page Preview</h3>
+                        <div class="preview-content">
+                            <img id="current-page-image" class="current-page-image" alt="Current page">
+                            <div id="current-page-text" class="current-page-text hidden">
+                                <h4>Extracted Text</h4>
+                                <pre id="page-text-content"></pre>
+                            </div>
+                        </div>
+                    </div>
                 </div>
             </section>
 
@@ -51,44 +92,59 @@
                 <div class="results-header">
                     <h2>OCR Results</h2>
                     <div class="results-actions">
-                        <button class="btn-secondary" id="download-markdown">Download Markdown</button>
-                        <button class="btn-secondary" id="download-all">Download All</button>
+                        <button class="btn-secondary" id="download-markdown">
+                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" class="icon">
+                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
+                                <polyline points="7 10 12 15 17 10"></polyline>
+                                <line x1="12" y1="15" x2="12" y2="3"></line>
+                            </svg>
+                            Download Markdown
+                        </button>
+                        <button class="btn-secondary" id="download-all">Download All Files</button>
                         <button class="btn-primary" id="new-upload">New Upload</button>
                     </div>
                 </div>
                 
                 <div class="results-tabs">
-                    <button class="tab-btn active" data-tab="text">Extracted Text</button>
-                    <button class="tab-btn" data-tab="images">Page Images</button>
-                    <button class="tab-btn" data-tab="metadata">Metadata</button>
+                    <button class="tab-btn active" data-tab="combined">Combined Text</button>
+                    <button class="tab-btn" data-tab="pages">Individual Pages</button>
+                    <button class="tab-btn" data-tab="metadata">Processing Details</button>
                 </div>
 
                 <div class="results-content">
-                    <!-- Text Content -->
-                    <div id="text-content" class="tab-content active">
-                        <div class="page-navigation">
-                            <select id="page-select"></select>
-                            <button class="btn-icon" id="copy-text" title="Copy to clipboard">
+                    <!-- Combined Text Content -->
+                    <div id="combined-content" class="tab-content active">
+                        <div class="text-output-large" id="combined-text-output">
+                            <!-- Combined markdown will be rendered here -->
+                        </div>
+                    </div>
+
+                    <!-- Individual Pages Content -->
+                    <div id="pages-content" class="tab-content">
+                        <div class="page-selector">
+                            <select id="page-select" class="page-dropdown">
+                                <!-- Options will be populated -->
+                            </select>
+                            <button class="btn-icon" id="copy-page-text" title="Copy page text">
                                 <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                                     <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                                     <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                                 </svg>
                             </button>
                         </div>
-                        <div id="text-output" class="text-output"></div>
-                    </div>
-
-                    <!-- Images Content -->
-                    <div id="images-content" class="tab-content">
-                        <div class="page-navigation">
-                            <select id="image-page-select"></select>
+                        <div class="page-display">
+                            <div class="page-image-container">
+                                <img id="page-image" class="page-image" alt="Page image">
+                            </div>
+                            <div class="page-text-container">
+                                <pre id="page-text-output" class="text-output"></pre>
+                            </div>
                         </div>
-                        <div id="image-output" class="image-output"></div>
                     </div>
 
                     <!-- Metadata Content -->
                     <div id="metadata-content" class="tab-content">
-                        <pre id="metadata-output"></pre>
+                        <pre id="metadata-output" class="metadata-output"></pre>
                     </div>
                 </div>
             </section>
