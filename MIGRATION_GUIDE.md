# Storage Architecture Migration Guide

This guide helps you migrate from the current storage system to the new user-partitioned storage architecture.

## Overview of Changes

### Old Architecture
- **Local Storage**: `/tmp/ocr_sessions/{session}/`
- **No User Isolation**: All sessions mixed together
- **Limited Cloud Support**: Hardcoded local paths
- **Manual Environment Config**: Required code changes for cloud

### New Architecture
- **Local Storage**: `./storage/users/{user_hash}/{session}/`
- **User Isolation**: Hash-based user partitioning
- **Cloud Native**: Automatic GCS integration
- **Environment Detection**: Same code works everywhere

## Migration Steps

### Step 1: Test New Implementation

1. **Keep existing code running**:
   ```bash
   # Current setup continues to work
   docker-compose up
   ```

2. **Test new version in parallel**:
   ```bash
   # Use new docker-compose file
   docker-compose -f docker-compose.v2.yml up
   ```

3. **Initialize storage structure**:
   ```bash
   # Create storage directories
   docker-compose -f docker-compose.v2.yml run storage-init
   ```

### Step 2: Update Application Code

1. **Update imports** in your code:
   ```python
   # Old
   from app.storage_service import storage_service
   from app.ocr_service import ocr_service
   
   # New
   from app.storage_service_v2 import StorageService
   from app.ocr_service_v2 import OCRService, ocr_service
   ```

2. **Create storage with user context**:
   ```python
   # Old - global storage
   storage_service.save_file(...)
   
   # New - user-scoped storage
   storage = StorageService(user_email="user@example.com")
   await storage.save_file(...)
   ```

3. **Update API endpoints** to extract user context:
   ```python
   # Add user email header or extract from auth
   x_user_email: Optional[str] = Header(None)
   storage = StorageService(user_email=x_user_email)
   ```

### Step 3: Environment Configuration

1. **Update .env file**:
   ```bash
   # Copy new example
   cp .env.example.v2 .env
   
   # Edit with your settings
   STORAGE_PATH=./storage
   RUNNING_IN_CLOUD=false
   HF_CACHE_HOST_PATH=~/.cache/huggingface
   ```

2. **For cloud deployment**:
   ```bash
   RUNNING_IN_CLOUD=true
   GCS_BUCKET_NAME=your-bucket-name
   GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
   ```

### Step 4: Data Migration (Optional)

If you have existing sessions to preserve:

```python
# Migration script example
import shutil
from app.storage_service_v2 import StorageService

# Old session path
old_session = "/tmp/ocr_sessions/old-session-id"

# Create new storage
storage = StorageService(user_email="migrated@example.com")
new_session = await storage.create_session()

# Copy files
for file in Path(old_session).glob("**/*"):
    if file.is_file():
        content = file.read_bytes()
        relative_path = file.relative_to(old_session)
        await storage.save_file(content, str(relative_path), new_session)
```

### Step 5: Testing

1. **Test file upload**:
   ```bash
   curl -X POST http://localhost:7799/upload \
     -H "X-User-Email: test@example.com" \
     -F "file=@test.pdf"
   ```

2. **Verify user isolation**:
   ```bash
   # Check storage structure
   ls -la storage/users/
   # Should see hash directories for each user
   ```

3. **Test cloud mode**:
   ```bash
   # Set cloud mode
   export RUNNING_IN_CLOUD=true
   export GCS_BUCKET_NAME=test-bucket
   
   # Files should save to GCS instead of local
   ```

## Cache Management

### Model Cache Setup

1. **Option A: Use existing HuggingFace cache**:
   ```yaml
   volumes:
     - ~/.cache/huggingface:/root/.cache/huggingface
   ```

2. **Option B: Use storage-integrated cache**:
   ```yaml
   volumes:
     - ./storage/cache/huggingface:/root/.cache/huggingface
   ```

3. **Verify cache**:
   ```bash
   # Check cache info
   curl http://localhost:7799/cache/info
   ```

### Cloud Cache Deployment

1. **Upload cache to GCS**:
   ```bash
   gsutil -m cp -r ~/.cache/huggingface/* gs://gnosis-ocr-models/huggingface/
   ```

2. **Mount in Cloud Run**:
   ```yaml
   annotations:
     run.googleapis.com/volume-mounts: '[{"name":"cache","path":"/cache"}]'
     run.googleapis.com/volumes: '[{"name":"cache","gcs":{"bucket":"gnosis-ocr-models"}}]'
   ```

## Rollback Plan

If issues arise:

1. **Quick rollback**:
   ```bash
   # Switch back to original docker-compose
   docker-compose down
   docker-compose up
   ```

2. **Code rollback**:
   ```python
   # Revert imports to use v1 services
   from app.storage_service import storage_service
   from app.ocr_service import ocr_service
   ```

## Benefits After Migration

1. **User Isolation**: Each user's data is completely separated
2. **Cloud Ready**: Deploy to Google Cloud Run without code changes
3. **Unified Storage**: Same API for local and cloud storage
4. **Better Organization**: Clear directory structure
5. **Cache Management**: Integrated model cache handling
6. **Security**: User-based access control built-in

## Troubleshooting

### Issue: "Model not found in cache"
```bash
# Verify cache path
echo $HF_CACHE_HOST_PATH
# Ensure model exists
ls ~/.cache/huggingface/hub/models--nanonets--Nanonets-OCR-s/
```

### Issue: "Access denied" errors
```python
# Ensure user email is consistent
storage1 = StorageService(user_email="user@example.com")
storage2 = StorageService(user_email="user@example.com")  # Same email
```

### Issue: "Session not found"
```python
# Check session belongs to user
valid = await storage.validate_session(session_hash)
if not valid:
    # Session doesn't exist or belongs to different user
```

## Support

For issues or questions:
1. Check logs: `docker-compose logs -f app`
2. Review test suite: `pytest tests/test_storage_v2.py -v`
3. Enable debug mode: `LOG_LEVEL=DEBUG`