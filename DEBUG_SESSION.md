# OCR Service Debugging Session Summary

## Problem Identified
Storage service was creating scattered files across multiple sessions instead of keeping all files in same session directory. OCR results not appearing in storage despite processing completing.

## Root Cause: Session Mismatch
1. Upload created session and saved `oklahoma.pdf` to `users/de1f5e9831fd/bd068a5c-f4a3-4581-b5cf-35be0a5d4616/`
2. OCR service created separate sessions for status files: `c6d49fc1-6706-4776-afd7-8c3164cb8a20/` and `f447e350-6888-4fc1-831e-7b12d7429ec4/`
3. Results scattered across different directories instead of unified session

## Changes Made

### Docker Volume Configuration
- Fixed `docker-compose.yml` to use Docker volume `gnosis_ocr_storage:/app/storage` instead of bind mount
- Removed conflicting volume definitions
- Updated `Dockerfile` to create `/app/storage` instead of `/tmp/ocr_sessions` with cache subdirs
- Set `STORAGE_PATH="/app/storage"` in Dockerfile

### Storage Service Fixes
- Removed unused `temp` directory creation from `_ensure_local_dirs()`
- Storage now only creates `users/` subdirectory in volume
- Fixed dual-mode operation (local volume vs GCS in cloud)

### Upload Flow Fixes
- Added file saving to storage in `upload_job_chunk()` endpoint
- Upload now creates session and saves uploaded file before calling OCR service
- Session ID passed from upload to OCR service

### OCR Service Session Management
- Updated `submit_job()` to accept `session_id` parameter
- Modified job data to store `session_id` 
- Fixed `_update_job_status_gcs()` to use session_id instead of job_id for file paths
- OCR service now uses existing upload session instead of creating new ones

## Current Status
- Volume mount working (Docker volume persists across restarts)
- Session mismatch fixed (all files should go to same session directory)
- Uploaded files saving to storage
- Status files saving to correct session

## Outstanding Issues
1. UI shows "processing" instead of "queued" during model load
2. OCR results still not appearing in storage files (need to verify if processing completes and saves results)
3. Need to confirm all files appear in same session directory after restart

## File Structure Should Be
```
/app/storage/users/{user_hash}/{session_id}/
├── oklahoma.pdf          # Original upload
├── metadata.json         # Session metadata  
├── status.json          # Job status
├── page_001.png         # Extracted images (if PDF)
├── page_001.txt         # OCR results per page
└── combined_output.md   # Final combined results
```