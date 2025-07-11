# PLAN 2: Cloud Tasks Storage Reference Architecture

## Problem Analysis

Claude Code correctly identified and fixed the UnicodeDecodeError by filtering binary data from JSON responses. However, this reveals a fundamental architectural issue: **binary data should never be stored in job records in the first place**.

## Root Cause: Wrong Data Flow Pattern

**Current (Broken) Pattern:**
```
Upload → Store binary in job.data → Try to return job via JSON → UnicodeDecodeError
```

**Correct Pattern for Cloud Tasks:**
```
Upload → Store file in storage → Store file reference in job → Return job reference via JSON → Worker downloads file from storage
```

## The Fix: Storage Reference Architecture

### Core Principle
**Never store binary data in job records. Always store file references.**

### Data Separation Strategy

**Job Records Should Contain:**
- Job metadata (status, progress, timestamps)
- File references (storage paths, session IDs)
- Processing configuration
- User context

**Storage Should Contain:**
- Original uploaded files
- Extracted images
- Processing results
- Session metadata

## Implementation Plan

### Phase 1: Immediate Fix - Remove Binary Data from Jobs

**1.1 Modify ocr_service.py job submission:**
```python
# BEFORE (current broken pattern):
job_data = {
    "data": image_data,  # ❌ WRONG - binary in job record
    "status": "queued"
}

# AFTER (correct pattern):
job_data = {
    "file_reference": {  # ✅ CORRECT - reference only
        "session_id": session_id,
        "filename": "original.pdf",
        "file_path": storage_path
    },
    "status": "queued"
}
```

**1.2 Update job processing to use storage:**
- Remove `job['data']` usage from processing logic
- Add file retrieval from storage service
- Process files from storage, not from job memory

### Phase 2: Storage-First Upload Flow

**2.1 Modify upload endpoints in main.py:**
- Save uploaded file to storage immediately
- Create job with file reference, not binary data
- Return job ID for status tracking

**2.2 Upload flow sequence:**
```
1. Chunked upload → storage service → file saved
2. Create job record with file reference only
3. Submit job to processing queue (ThreadPoolExecutor or Cloud Tasks)
4. Worker retrieves file from storage using reference
5. Worker processes file and saves results to storage
```

### Phase 3: Cloud Tasks Ready Architecture

**3.1 Task payload structure:**
```json
{
  "job_id": "uuid",
  "session_id": "session_hash",
  "file_reference": {
    "storage_path": "users/hash123/session456/original.pdf",
    "filename": "original.pdf",
    "file_size": 1048576,
    "content_type": "application/pdf"
  },
  "user_email": "user@example.com",
  "processing_options": {},
  "job_type": "pdf"
}
```

**3.2 Worker service pattern:**
```python
# Cloud Tasks worker receives reference
async def process_ocr_task(task_payload):
    file_ref = task_payload["file_reference"]
    
    # Download file from storage
    storage = StorageService(task_payload["user_email"])
    file_data = await storage.get_file(
        file_ref["filename"], 
        task_payload["session_id"]
    )
    
    # Process file
    results = process_ocr(file_data)
    
    # Save results back to storage
    await storage.save_combined_result(session_id, results)
```

## Specific Code Changes Required

### 1. Fix ocr_service.py submit_job()

**Remove binary data storage:**
```python
# Change from storing binary data
job_data = {
    "status": "queued",
    "type": job_type,
    "data": image_data,  # ❌ REMOVE THIS
    # ... rest
}

# To storing file reference
job_data = {
    "status": "queued", 
    "type": job_type,
    "file_reference": {  # ✅ ADD THIS
        "session_id": session_id,
        "filename": original_filename,
        "storage_path": file_path,
        "file_size": len(image_data)
    },
    # ... rest
}
```

### 2. Update job processing logic

**Modify _process() function in ocr_service.py:**
```python
# Change from using job data directly
file_data = job['data']  # ❌ REMOVE

# To retrieving from storage
file_ref = job['file_reference']  # ✅ ADD
storage = StorageService(job.get('user_email'))
file_data = await storage.get_file(
    file_ref['filename'], 
    file_ref['session_id']
)
```

### 3. Update upload endpoints

**Modify main.py upload flow:**
```python
# Save file to storage first
storage = StorageService(user_email)
session_id = await storage.create_session()
file_path = await storage.save_file(file_data, filename, session_id)

# Create job with reference only
job_id = ocr_service.submit_job_with_reference(
    file_reference={
        "session_id": session_id,
        "filename": filename,
        "storage_path": file_path,
        "file_size": len(file_data)
    },
    job_type=job_type,
    user_email=user_email
)
```

## Cloud Tasks Compatibility

### Task Size Benefits
- **Before**: Task payload = job metadata + 500MB binary data = FAIL
- **After**: Task payload = job metadata + file reference = ~1KB = SUCCESS

### Worker Service Implementation
```python
# Worker can be separate Cloud Run service
@app.post("/process-task")
async def handle_cloud_task(task_data: dict):
    # Receive small reference payload
    file_ref = task_data["file_reference"]
    
    # Download file from GCS/storage
    storage = StorageService(task_data["user_email"])
    file_content = await storage.get_file(
        file_ref["filename"],
        file_ref["session_id"] 
    )
    
    # Process and save results
    # Worker is stateless and scalable
```

## Migration Strategy

### Step 1: Emergency Fix (Immediate)
1. Remove binary data from job records
2. Store files in storage service during upload
3. Update job processing to read from storage
4. Test local deployment thoroughly

### Step 2: Validate Architecture (Next)
1. Verify job records contain only references
2. Confirm all file operations use storage service
3. Test chunked upload → storage → processing flow
4. Validate both local and cloud storage work

### Step 3: Cloud Tasks Ready (Future)
1. Task payloads are small and JSON-serializable
2. Worker services can be separate and stateless
3. Horizontal scaling possible
4. No size limits for file processing

## Success Criteria

### Immediate Fixes:
- ✅ No binary data in job records
- ✅ No UnicodeDecodeError in JSON responses
- ✅ Files stored and retrieved from storage service
- ✅ Local deployment continues working

### Cloud Tasks Readiness:
- ✅ Task payloads under 1MB (file references only)
- ✅ Stateless worker processing possible
- ✅ Horizontal scaling capability
- ✅ Storage-based file handling throughout

### Architecture Validation:
- ✅ Clean separation: job metadata vs file storage
- ✅ JSON-serializable job records
- ✅ Storage service handles all file operations
- ✅ No memory leaks from large binary data in jobs

## Files to Modify

### Priority 1 (Critical):
1. **app/ocr_service.py** - Remove binary data from job records
2. **app/main.py** - Update upload flow to use storage first

### Priority 2 (Important):
3. **app/storage_service.py** - Ensure robust file operations
4. Test upload → storage → processing → results flow

### Priority 3 (Future):
5. Create separate worker service for Cloud Tasks
6. Implement task queue management

This architecture fix resolves the immediate UnicodeDecodeError while establishing the correct foundation for Cloud Tasks migration.