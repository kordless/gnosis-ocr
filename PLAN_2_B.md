# PLAN 2B: Cloud Tasks Implementation for OCR Processing

## Current State - What's Been Fixed

### ✅ Completed Fixes
1. **OCR Results Saving** - Text results are now saved to storage using storage service methods
2. **PDF Page Images Saving** - Extracted page images are saved during processing
3. **Storage Service Integration** - Proper use of storage service for saving artifacts
4. **Session-Based File Organization** - All files saved to correct session directories

### 🔄 Still Using Old Architecture
- **Binary data still in job records** - `job['data']` contains file content
- **ThreadPoolExecutor** - Both local and cloud use same in-memory processing
- **In-memory job tracking** - Jobs only exist in `self.jobs` dictionary

## PLAN 2B: Cloud Tasks Architecture

### Design Principles
1. **No changes to local development** - Local continues using ThreadPoolExecutor
2. **Cloud Run uses Cloud Tasks** - Only when `RUNNING_IN_CLOUD=true`
3. **Serialized processing** - One task processor at a time to avoid deadlocks
4. **File-based state tracking** - All state stored in JSON files, not memory
5. **Batch processing** - Process N images per task (configurable, default 10)

### Architecture Overview

```
Cloud Run Instance (Web)          Cloud Tasks              Cloud Run (Worker)
┌─────────────────────┐          ┌─────────────┐         ┌─────────────────┐
│  1. Upload PDF      │          │             │         │  4. Process     │
│  2. Extract images  │ -------> │  Task Queue │ ------> │     N images    │
│  3. Create task     │          │             │         │  5. Update JSON │
│  6. Poll status     │          └─────────────┘         │  6. Save results│
└─────────────────────┘                                  └─────────────────┘
         │                                                        │
         │                    Google Cloud Storage                │
         └────────────────────────┬───────────────────────────────┘
                                  │
                         ┌────────────────────┐
                         │ Session Directory: │
                         │ - original.pdf     │
                         │ - page_001.png     │
                         │ - page_002.png     │
                         │ - processing.json  │
                         │ - page_001.txt     │
                         │ - status.json      │
                         └────────────────────┘
```

### Implementation Plan

## Phase 1: File-Based Job Tracking

### 1.1 Create processing.json Structure
```json
{
  "job_id": "uuid",
  "session_id": "uuid",
  "total_pages": 5,
  "batch_size": 10,
  "pages": {
    "1": {
      "image": "page_001.png",
      "status": "pending",  // pending, processing, completed, failed
      "started_at": null,
      "completed_at": null,
      "result_file": null,
      "error": null
    },
    "2": {
      "image": "page_002.png",
      "status": "pending",
      "started_at": null,
      "completed_at": null,
      "result_file": null,
      "error": null
    }
  },
  "created_at": "2025-07-11T18:00:00Z",
  "updated_at": "2025-07-11T18:00:00Z"
}
```

### 1.2 Update Upload Flow (main.py)
```python
# When RUNNING_IN_CLOUD=true and job_type=pdf:
if os.environ.get('RUNNING_IN_CLOUD') == 'true' and job_type == 'pdf':
    # Extract and save images BEFORE creating job
    images = pdf2image.convert_from_bytes(file_data)
    
    # Save all images to storage
    for i, image in enumerate(images):
        await storage_service.save_page_image(session_id, i+1, image_bytes)
    
    # Create processing.json
    processing_data = create_processing_json(session_id, len(images))
    await storage_service.save_file(
        json.dumps(processing_data),
        'processing.json',
        session_id
    )
    
    # Create Cloud Task
    create_ocr_processing_task(session_id, user_email)
else:
    # Local: use existing ThreadPoolExecutor flow
    job_id = ocr_service.submit_job(file_data, job_type, user_email, session_id)
```

## Phase 2: Cloud Task Worker

### 2.1 Worker Endpoint (app/worker.py)
```python
@app.post("/process-ocr-batch")
async def process_ocr_batch(request: ProcessBatchRequest):
    """Process a batch of OCR pages from Cloud Tasks"""
    
    # Load processing.json
    storage = StorageService(request.user_email)
    processing_data = await storage.get_file('processing.json', request.session_id)
    
    # Find next N unprocessed pages
    pending_pages = get_pending_pages(processing_data, batch_size=10)
    
    if not pending_pages:
        return {"status": "no_pending_pages"}
    
    # Lock pages by marking as processing
    for page_num in pending_pages:
        processing_data['pages'][str(page_num)]['status'] = 'processing'
        processing_data['pages'][str(page_num)]['started_at'] = datetime.utcnow().isoformat()
    
    # Save updated processing.json (atomic write)
    await storage.save_file(
        json.dumps(processing_data),
        'processing.json',
        request.session_id
    )
    
    # Process each page
    for page_num in pending_pages:
        try:
            # Load image from storage
            image_data = await storage.get_file(f'page_{page_num:03d}.png', request.session_id)
            
            # Process OCR
            result = ocr_service.process_image(Image.open(io.BytesIO(image_data)))
            
            # Save result
            await storage.save_page_result(request.session_id, page_num, result['text'])
            
            # Update processing.json
            processing_data['pages'][str(page_num)]['status'] = 'completed'
            processing_data['pages'][str(page_num)]['completed_at'] = datetime.utcnow().isoformat()
            processing_data['pages'][str(page_num)]['result_file'] = f'page_{page_num:03d}_result.txt'
            
        except Exception as e:
            processing_data['pages'][str(page_num)]['status'] = 'failed'
            processing_data['pages'][str(page_num)]['error'] = str(e)
    
    # Save final processing.json
    await storage.save_file(
        json.dumps(processing_data),
        'processing.json',
        request.session_id
    )
    
    # Check if all pages done
    if all_pages_processed(processing_data):
        # Combine results
        await combine_results(storage, request.session_id, processing_data)
        
        # Update status.json to completed
        await update_status(storage, request.session_id, 'completed')
    else:
        # Create another task for remaining pages
        create_ocr_processing_task(request.session_id, request.user_email)
    
    return {"status": "batch_processed", "pages_processed": len(pending_pages)}
```

### 2.2 Task Creation
```python
def create_ocr_processing_task(session_id: str, user_email: str):
    """Create a Cloud Task for OCR processing"""
    
    client = tasks_v2.CloudTasksClient()
    project = 'gnosis-ocr'
    location = 'us-central1'
    queue = 'ocr-processing'
    
    parent = client.queue_path(project, location, queue)
    
    task = {
        'http_request': {
            'http_method': tasks_v2.HttpMethod.POST,
            'url': f'{WORKER_URL}/process-ocr-batch',
            'headers': {'Content-Type': 'application/json'},
            'body': json.dumps({
                'session_id': session_id,
                'user_email': user_email
            }).encode()
        }
    }
    
    # Create task with no concurrency (serialized processing)
    response = client.create_task(request={'parent': parent, 'task': task})
```

## Phase 3: Frontend Polling

### 3.1 Status Endpoint Updates
```python
@app.get("/api/v1/jobs/{job_id}/status")
async def get_job_status_cloud(job_id: str):
    """Get job status from processing.json for cloud deployments"""
    
    if os.environ.get('RUNNING_IN_CLOUD') == 'true':
        # Load from storage
        storage = StorageService(get_current_user_email())
        
        try:
            # Load processing.json
            processing_data = await storage.get_file('processing.json', job_id)
            
            # Calculate progress
            total = len(processing_data['pages'])
            completed = sum(1 for p in processing_data['pages'].values() 
                          if p['status'] == 'completed')
            
            return {
                'status': 'completed' if completed == total else 'processing',
                'progress': {
                    'percent': int((completed / total) * 100),
                    'current_page': completed,
                    'total_pages': total,
                    'message': f'Processing page {completed + 1} of {total}...'
                }
            }
        except FileNotFoundError:
            # Fall back to in-memory check
            return ocr_service.get_job_status(job_id)
    else:
        # Local: use in-memory job status
        return ocr_service.get_job_status(job_id)
```

## Configuration

### Environment Variables
```bash
# Cloud Run Instance (Web)
RUNNING_IN_CLOUD=true
CLOUD_TASKS_ENABLED=true
OCR_BATCH_SIZE=10  # Pages per task
WORKER_URL=https://ocr-worker-xyz.run.app

# Cloud Run Instance (Worker)
RUNNING_IN_CLOUD=true
IS_WORKER=true
MODEL_CACHE_PATH=/app/cache
```

### Cloud Tasks Queue Configuration
```yaml
# queue.yaml
queue:
- name: ocr-processing
  rate_limits:
    max_concurrent_dispatches: 1  # Serialize processing
    max_dispatches_per_second: 1
  retry_config:
    max_attempts: 3
    max_retry_duration: 600s
```

## Benefits

1. **Serialized Processing** - Only one task processes at a time, no deadlocks
2. **Fault Tolerant** - If a task fails, Cloud Tasks retries automatically
3. **Progress Tracking** - Frontend can poll processing.json for real-time updates
4. **Batch Efficiency** - Process N pages per task to reduce overhead
5. **No Local Changes** - Development environment unchanged
6. **Scalable** - Can increase batch size or parallelize in future

## Migration Path

1. **Phase 1**: Implement file-based tracking (processing.json)
2. **Phase 2**: Add Cloud Tasks integration for Cloud Run only
3. **Phase 3**: Update frontend to poll from storage instead of memory
4. **Phase 4**: Deploy worker service and test end-to-end

## Success Criteria

- ✅ Local development unchanged (ThreadPoolExecutor)
- ✅ Cloud Run uses Cloud Tasks for processing
- ✅ All state tracked in JSON files
- ✅ Serialized processing (one task at a time)
- ✅ Frontend shows real-time progress
- ✅ Batch processing of configurable page count
- ✅ Automatic retry on failures
- ✅ No memory-based job tracking in cloud
