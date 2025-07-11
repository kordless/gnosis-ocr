# OCR Service Local Storage Fix and Chunked Upload Implementation Plan

## Overview
Fix broken local storage and implement chunked upload support for 500MB files while maintaining local processing capabilities. **DO NOT MODIFY ANYTHING RELATED TO model-cache** - it is working correctly.

## Mount Points and Storage Structure

### Docker Volume Mounts
- **Storage Volume**: Host `./storage` → Container `/app/storage`
- **Model Cache**: Host `./model-cache` → Container `/app/cache` (DO NOT MODIFY)

### Storage Directory Structure
```
/app/storage/                    # Main storage mount point
├── users/                       # User-partitioned storage
│   └── {user_hash}/            # 12-char user hash
│       └── {session_id}/       # Session-based organization
│           ├── original.pdf    # Original uploaded file
│           ├── page_001.png    # Extracted images
│           ├── page_002.png
│           ├── metadata.json   # Session metadata
│           └── status.json     # Processing status
└── temp/                       # Temporary chunked upload storage
    └── {upload_id}/            # Temporary chunks during upload
        ├── chunk_000
        ├── chunk_001
        └── metadata.json
```

## Phase 1: Critical Storage Service Fix

### 1.1 Fix app/storage_service.py
**CRITICAL**: Restore dual-mode operation following gnosis-wraith pattern

**Changes needed:**
- Replace forced GCS initialization with conditional `is_running_in_cloud()` check
- Restore proper `_init_local()` method that sets up local file operations
- Add `_ensure_local_dirs()` method for local directory creation
- Implement dual-path operations in all methods:
  - `save_file()` - GCS branch vs local file system branch
  - `get_file()` - GCS branch vs local file system branch  
  - `delete_file()` - GCS branch vs local file system branch
  - `list_files()` - GCS branch vs local file system branch
- Add graceful GCS import with `GCS_AVAILABLE` flag and fallback
- Fix `force_cloud_mode()` to only run when actually in cloud

### 1.2 Update docker-compose.yml
**Add storage volume mount:**
```yaml
volumes:
  - ./storage:/app/storage        # Add this line
  - ./model-cache:/app/cache      # Keep existing - DO NOT MODIFY
```

**Ensure storage directory exists on host:**
- Create `./storage` directory if it doesn't exist
- Set proper permissions for container access

## Phase 2: Chunked Upload Implementation

### 2.1 Create app/chunked_upload_service.py
**New service class for handling chunked uploads:**
- `ChunkedUploadService` class
- Temporary chunk storage in `/app/storage/temp/{upload_id}/`
- Chunk validation and integrity checking
- Chunk reassembly logic
- Cleanup of temporary chunks after successful reassembly
- Progress tracking during upload

**Key methods:**
- `start_upload_session(filename, total_size, total_chunks, user_email)`
- `save_chunk(upload_id, chunk_number, chunk_data)`
- `validate_chunk(upload_id, chunk_number, expected_size)`
- `assemble_complete_file(upload_id)`
- `cleanup_temp_chunks(upload_id)`

### 2.2 Update app/main.py Upload Endpoints
**Modify existing endpoints to support chunked uploads:**
- Keep `/api/v1/jobs/submit` for direct upload (small files)
- Add `/api/v1/jobs/submit/start` for starting chunked upload session
- Add `/api/v1/jobs/submit/chunk/{upload_id}` for individual chunk upload
- Configure chunk size: 32MB chunks (to support 500MB total files)
- Update progress tracking for chunked uploads

**Key changes:**
- Add user email handling to all upload endpoints
- Implement chunk validation and reassembly
- Return proper upload session IDs
- Handle transition from upload completion to OCR job creation

### 2.3 Update app/static/script.js
**Frontend chunked upload logic:**
- Detect file size and automatically use chunked upload for files > 32MB
- Implement chunk creation and upload logic
- Update progress bar to show upload progress vs processing progress
- Handle upload session management
- Switch from session-based to job-based status checking after upload

## Phase 3: Upload-Time Processing

### 3.1 File Processing Pipeline Modification
**Move PDF extraction from task processing to upload time:**
- Detect file type immediately after upload completion
- For PDF files: extract images during upload processing
- For single images (PNG, JPG, etc.): store directly without conversion
- Generate metadata about processing results

### 3.2 Create app/file_processors.py
**New file processing classes:**

**PDFProcessor:**
- Extract images from PDF immediately after upload
- Store original PDF and extracted images in session storage
- Generate metadata about extracted pages
- Update session metadata with processing results

**ImageProcessor:**
- Handle single image uploads (PNG, JPG, JPEG, WEBP, TIFF)
- Store directly without conversion
- Generate appropriate metadata
- Skip extraction step entirely

### 3.3 Update app/ocr_service.py
**Modify to work with pre-processed files:**
- Remove PDF extraction logic from task processing
- Work with pre-extracted images from storage
- Update job submission to handle pre-processed file metadata
- Maintain existing OCR processing logic for extracted images

## Phase 4: Storage Service Enhancements

### 4.1 Add Storage Methods
**New methods in storage_service.py:**
- `save_original_file(session_hash, filename, content)` - Store uploaded file
- `save_extracted_images(session_hash, images_data)` - Store PDF-extracted images
- `get_session_files(session_hash)` - List all files in session
- `create_temp_upload_dir(upload_id)` - Create temporary upload directory
- `cleanup_temp_upload(upload_id)` - Remove temporary upload files

### 4.2 Session and File Management
**Enhanced session handling:**
- Store both original files and extracted images in same session
- Maintain file relationship metadata (PDF → images)
- Proper cleanup of temporary files
- Session-based organization for easy management

## Implementation Order

### Step 1: Emergency Storage Fix (Do First)
1. Backup current `app/storage_service.py`
2. Fix storage service to follow gnosis-wraith dual-mode pattern
3. Update `docker-compose.yml` with storage volume mount
4. Test local storage functionality

### Step 2: Chunked Upload Infrastructure
1. Create `app/chunked_upload_service.py`
2. Update `app/main.py` upload endpoints
3. Update `app/static/script.js` frontend logic
4. Test chunked upload with small files first

### Step 3: Upload-Time Processing
1. Create `app/file_processors.py`
2. Integrate PDF and image processing at upload time
3. Update OCR service to work with pre-processed files
4. Test with both PDF and image files

### Step 4: Integration and Testing
1. End-to-end testing with 500MB files
2. Verify local and cloud compatibility
3. Performance testing and optimization

## Critical Requirements

### Must Not Break:
- **model-cache functionality** - DO NOT MODIFY anything related to `/app/cache` or model caching
- **Cloud deployment compatibility** - All changes must work in both local and cloud environments
- **Existing OCR processing** - Maintain current OCR capabilities
- **Current API endpoints** - Ensure backward compatibility where possible

### Must Implement:
- **Local storage volume mounting** - Files must persist on host filesystem
- **500MB file support** - Through chunked upload methodology
- **Upload-time processing** - PDF extraction during upload, not during OCR tasks
- **Dual storage support** - Work correctly in both local and cloud environments
- **Single image handling** - Direct storage without conversion for PNG/JPG files

## Testing Strategy

### Local Storage Tests:
1. Verify storage volume mount works
2. Test file persistence across container restarts
3. Verify user partitioning in local storage

### Chunked Upload Tests:
1. Upload 500MB test file in chunks
2. Test chunk validation and reassembly
3. Test upload failure recovery

### File Processing Tests:
1. Test PDF upload and image extraction
2. Test single image upload (PNG, JPG)
3. Verify proper storage location for all file types

### Integration Tests:
1. End-to-end workflow: upload → extract → OCR → results
2. Test both local and cloud environments
3. Performance testing with large files

## Success Criteria

- ✅ Local storage works with proper volume mounting to `/app/storage`
- ✅ Files persist on host filesystem in `./storage` directory
- ✅ 500MB files can be uploaded via 32MB chunks
- ✅ PDF images extracted at upload time, stored in session directory
- ✅ Single images stored directly without conversion
- ✅ Both local and cloud deployments work correctly
- ✅ model-cache functionality remains unchanged
- ✅ Current OCR processing capabilities maintained
- ✅ Proper cleanup of temporary files
- ✅ User partitioning works in local storage

## Files to Create/Modify

### Create:
- `app/chunked_upload_service.py` - Chunked upload handling
- `app/file_processors.py` - PDF and image processing

### Modify:
- `app/storage_service.py` - Fix local storage (CRITICAL)
- `docker-compose.yml` - Add storage volume mount
- `app/main.py` - Update upload endpoints
- `app/static/script.js` - Frontend chunked upload
- `app/ocr_service.py` - Work with pre-processed files

### Do Not Modify:
- Anything related to `model-cache` or `/app/cache`
- Model loading or caching logic
- GPU/CUDA configuration