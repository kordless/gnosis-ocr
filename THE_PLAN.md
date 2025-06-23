# Gnosis OCR Storage Architecture Implementation Plan

## 🎯 Objective
Implement the same storage layer architecture from gnosis-wraith in gnosis-ocr to support:
- **Local development**: File storage in `./storage/` directory  
- **Cloud deployment**: Google Cloud Storage with hash-based user partitioning
- **Automatic detection**: Environment-based switching between local and cloud

## 📋 Current State Analysis

### Current OCR Storage Issues:
- **No user partitioning** - All files mixed together
- **Hardcoded local paths** - Won't work in cloud deployment  
- **No environment detection** - Manual configuration required
- **Limited file organization** - Basic session-based storage only

### Gnosis-Wraith Storage Strengths:
- ✅ **User hash bucketing** - `users/{hash}/` for isolation
- ✅ **Environment auto-detection** - `RUNNING_IN_CLOUD` flag
- ✅ **Unified API** - Same methods work locally and in cloud
- ✅ **Clean organization** - Separate NDB models from user files
- ✅ **URL generation** - Consistent URLs for file access

## 🏗️ Implementation Plan

### Phase 1: Core Storage Service (Priority 1)

#### 1.1 Create New Storage Service
**File**: `app/storage_service_v2.py`

```python
class StorageService:
    def __init__(self, user_email: Optional[str] = None):
        # Environment detection
        # User hash computation  
        # GCS/local initialization
        
    # Core file operations
    async def save_file(content, filename) -> str
    async def get_file(filename) -> bytes  
    async def delete_file(filename) -> bool
    async def list_files(prefix=None) -> List[Dict]
    def get_file_url(filename) -> str
    
    # OCR-specific methods
    async def save_page_image(session_hash, page_num, image_bytes) -> Dict
    async def save_page_result(session_hash, page_num, text) -> Dict  
    async def save_combined_result(session_hash, markdown) -> Dict
    def get_session_file_path(session_hash, filename, subfolder) -> str
```

#### 1.2 Environment Detection
```python
def is_running_in_cloud():
    """Detect Google Cloud environment"""
    return os.environ.get('RUNNING_IN_CLOUD', '').lower() == 'true'

def get_storage_config():
    """Get current storage configuration"""
    return {
        'file_storage': 'gcs' if is_running_in_cloud() else 'local',
        'storage_path': os.environ.get('STORAGE_PATH', './storage'),
        'users_path': 'storage/users',
        'gcs_bucket': os.environ.get('GCS_BUCKET_NAME', 'gnosis-ocr-storage')
    }
```

#### 1.3 User Hash Bucketing  
```python
def _compute_user_hash(self, email: Optional[str]) -> str:
    """Compute 12-char hash for user bucketing"""
    if not email:
        email = "anonymous@gnosis-ocr.local"
    return hashlib.sha256(email.encode()).hexdigest()[:12]

def get_user_path(self) -> str:
    """Get user-specific storage path: users/{hash}"""
    return f"users/{self._user_hash}"
```

### Phase 2: Storage Structure Migration (Priority 2)

#### 2.1 New Directory Structure
```
Local Development:
storage/
├── users/              # User-partitioned files
│   └── {user_hash}/    # 12-char hash bucket
│       └── {session}/  # OCR session files
│           ├── upload.pdf
│           ├── page_001.png
│           ├── page_001_result.txt
│           ├── combined_output.md
│           └── metadata.json
└── logs/               # Application logs
    └── gnosis-ocr.log

Cloud Production:
- Files: GCS bucket under users/{user_hash}/{session}/
- NDB: Google Datastore (session status, metadata)
```

#### 2.2 Session Management Integration
```python
# Update storage_service.py to work with sessions
class StorageService:
    def create_session(self, user_email: str = None) -> str:
        """Create new session with user context"""
        
    def get_session_path(self, session_hash: str) -> str:
        """Get full session path: users/{hash}/{session}"""
        
    def validate_session(self, session_hash: str) -> bool:
        """Check if session exists and belongs to current user"""
```

### Phase 3: API Integration (Priority 3)

#### 3.1 Update Main Application
**File**: `app/main.py`
- Import new storage service
- Pass user context (email from auth headers)
- Update upload endpoint to use new storage

#### 3.2 Update OCR Service  
**File**: `app/ocr_service.py`
- Use new storage methods for saving results
- Remove hardcoded path references
- Add user context to all storage operations

#### 3.3 File Serving Routes
```python
@app.get("/storage/{user_hash}/{filename}")  
async def serve_user_file(user_hash: str, filename: str):
    """Serve files from user storage"""
    # Validate user access
    # Return file from storage service
```

### Phase 4: Environment Configuration (Priority 4)

#### 4.1 Environment Variables
```bash
# Local Development
STORAGE_PATH=./storage
RUNNING_IN_CLOUD=false

# Cloud Production  
STORAGE_PATH=/tmp/storage  
RUNNING_IN_CLOUD=true
GCS_BUCKET_NAME=gnosis-ocr-storage
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

#### 4.2 Docker Configuration
```yaml
# docker-compose.yml
environment:
  - STORAGE_PATH=/app/storage
  - RUNNING_IN_CLOUD=false
volumes:
  - ./storage:/app/storage

# Cloud deployment
environment:
  - RUNNING_IN_CLOUD=true  
  - GCS_BUCKET_NAME=gnosis-ocr-storage
```

## 🔄 Migration Strategy

### Step 1: Parallel Implementation
- Keep existing `storage_service.py` working
- Implement new `storage_service_v2.py` alongside
- Test new service with debug mode

### Step 2: Gradual Switchover
- Update one endpoint at a time
- Use feature flags for switching
- Maintain backward compatibility

### Step 3: Full Migration
- Replace old storage service completely
- Remove old storage code
- Update all imports

## 🧪 Testing Plan

### Local Testing
1. **Basic Operations**: Save/retrieve files in user buckets
2. **Session Isolation**: Multiple users can't access each other's files  
3. **Path Generation**: Correct URLs for local file serving

### Cloud Testing (Staging)
1. **GCS Integration**: Files save to correct bucket paths
2. **Authentication**: Service account permissions working
3. **URL Generation**: Signed URLs or proxy serving working

### Integration Testing  
1. **End-to-End**: Upload PDF → Process → Retrieve results
2. **Multi-User**: Concurrent sessions with different users
3. **Error Handling**: Network failures, permission issues

## 📊 Success Metrics

### Functional Requirements
- ✅ **User Isolation**: Files properly partitioned by user hash
- ✅ **Environment Agnostic**: Works locally and in cloud
- ✅ **Session Management**: OCR sessions properly organized  
- ✅ **File Serving**: URLs work for all file types

### Performance Requirements
- ✅ **Local Performance**: No regression in file I/O speed
- ✅ **Cloud Performance**: Reasonable GCS upload/download times
- ✅ **Memory Usage**: No memory leaks from storage operations

### Reliability Requirements  
- ✅ **Error Handling**: Graceful fallbacks for storage failures
- ✅ **Data Integrity**: No file corruption during transfers
- ✅ **Concurrent Access**: Multiple users can upload simultaneously

## 🚀 Implementation Timeline

### Week 1: Core Storage Service
- Implement `StorageService` class with local/cloud detection
- Add user hash bucketing and path generation
- Basic file operations (save/get/delete/list)

### Week 2: OCR Integration
- Update OCR service to use new storage
- Migrate session management to new structure  
- Add file serving routes

### Week 3: Testing & Deployment
- Comprehensive testing locally and in cloud
- Deploy to staging environment
- Performance optimization and bug fixes

### Week 4: Production Migration
- Deploy to production with feature flags
- Monitor performance and error rates
- Complete migration from old storage system

## 🔧 Key Implementation Details

### User Authentication Context
```python
# Extract user from request headers/auth
user_email = get_user_from_request(request)
storage = StorageService(user_email=user_email)
```

### File URL Generation
```python
# Always return relative URLs for consistency
def get_file_url(self, filename: str) -> str:
    return f"/storage/{self._user_hash}/{filename}"
```

### Error Handling
```python
try:
    content = await storage.get_file(filename)
except FileNotFoundError:
    raise HTTPException(404, "File not found")
except PermissionError:  
    raise HTTPException(403, "Access denied")
```

## 🗄️ MODEL CACHE INTEGRATION

### Current Cache Setup Analysis
**Local Development:**
- HuggingFace cache: `C:\Users\kord\.cache\huggingface` (7.4GB)
- Docker mount: `${HF_CACHE_HOST_PATH}:/root/.cache/huggingface`
- Model: `nanonets/Nanonets-OCR-s` with checkpoint shards

### Enhanced Storage Structure with Cache
```
Local Development:
storage/
├── cache/                    # Model cache directory
│   └── huggingface/         # HuggingFace models
│       └── hub/
│           └── models--nanonets--Nanonets-OCR-s/
│               ├── snapshots/
│               ├── refs/
│               └── blobs/
├── users/                   # User-partitioned files  
│   └── {user_hash}/
│       └── {session}/
│           ├── upload.pdf
│           ├── page_001.png
│           └── results...
└── logs/
    └── gnosis-ocr.log

Cloud Production:
- Cache: GCS bucket "gnosis-ocr-models" (shared across instances)
- User Files: GCS bucket "gnosis-ocr-storage/users/{hash}/"
- Models: Persistent disk or bucket mount
```

### Phase 5: Model Cache Management (NEW)

#### 5.1 Cache Service Integration
```python
class StorageService:
    def __init__(self, user_email: Optional[str] = None):
        # Existing initialization...
        self._cache_path = self._get_cache_path()
        
    def _get_cache_path(self) -> str:
        """Get model cache path based on environment"""
        if is_running_in_cloud():
            # Cloud: Use mounted persistent disk or GCS FUSE
            return os.environ.get('MODEL_CACHE_PATH', '/cache/huggingface')
        else:
            # Local: Use storage/cache or existing HF cache
            hf_cache = os.environ.get('HF_CACHE_HOST_PATH', 
                                    os.path.expanduser('~/.cache/huggingface'))
            storage_cache = os.path.join(self._storage_path, 'cache', 'huggingface')
            
            # Prefer existing HF cache if it exists, otherwise use storage cache
            return hf_cache if os.path.exists(hf_cache) else storage_cache
    
    def get_cache_config(self) -> Dict[str, str]:
        """Get cache configuration for model loading"""
        return {
            'cache_dir': self._cache_path,
            'local_files_only': True,  # Force cache usage
            'trust_remote_code': True
        }
    
    async def verify_model_cache(self, model_name: str) -> bool:
        """Verify model exists in cache"""
        model_path = os.path.join(self._cache_path, 'hub', 
                                f'models--{model_name.replace("/", "--")}')
        return os.path.exists(model_path)
    
    async def download_model_to_cache(self, model_name: str):
        """Download model to cache (cloud deployment helper)"""
        # For cloud deployment preparation
        pass
```

#### 5.2 OCR Service Cache Integration
```python
# app/ocr_service.py
class OCRService:
    async def initialize(self):
        """Initialize with storage-managed cache"""
        # Get cache config from storage service
        cache_config = storage_service.get_cache_config()
        
        # Verify model exists in cache
        if not await storage_service.verify_model_cache(settings.model_name):
            logger.error("Model not found in cache!")
            raise RuntimeError("Model cache not available")
        
        # Load with cache config
        self.tokenizer = AutoTokenizer.from_pretrained(
            settings.model_name, 
            **cache_config
        )
        # ... rest of initialization
```

#### 5.3 Environment Configuration for Cache
```bash
# Local Development (docker-compose.yml)
services:
  app:
    environment:
      - HF_CACHE_HOST_PATH=/app/storage/cache/huggingface
      - MODEL_CACHE_PATH=/app/storage/cache/huggingface
    volumes:
      # Option 1: Use existing HF cache
      - ${HF_CACHE_HOST_PATH:-C:\Users\kord\.cache\huggingface}:/root/.cache/huggingface
      
      # Option 2: Use unified storage cache  
      - ./storage/cache/huggingface:/app/storage/cache/huggingface

# Cloud Production
environment:
  - RUNNING_IN_CLOUD=true
  - MODEL_CACHE_PATH=/cache/huggingface
  - GCS_BUCKET_NAME=gnosis-ocr-storage
  - MODEL_BUCKET_NAME=gnosis-ocr-models
```

### Cloud Cache Deployment Options

#### Option A: Persistent Disk (Recommended)
```yaml
# Cloud Run with persistent disk mount
apiVersion: serving.knative.dev/v1
kind: Service
spec:
  template:
    metadata:
      annotations:
        run.googleapis.com/execution-environment: gen2
        run.googleapis.com/volume-mounts: '[{"name":"cache-disk","path":"/cache"}]'
        run.googleapis.com/volumes: '[{"name":"cache-disk","gcs":{"bucket":"gnosis-ocr-models"}}]'
    spec:
      containers:
      - image: gcr.io/PROJECT/gnosis-ocr
        env:
        - name: MODEL_CACHE_PATH
          value: "/cache/huggingface"
        - name: RUNNING_IN_CLOUD
          value: "true"
```

#### Option B: GCS FUSE Mount
```bash
# Pre-deployment: Upload cache to GCS
gsutil -m cp -r ~/.cache/huggingface/* gs://gnosis-ocr-models/huggingface/

# Runtime: Mount as filesystem
gcsfuse gnosis-ocr-models /cache
```

#### Option C: Container Image with Cache
```dockerfile
# Dockerfile.cloud
FROM base-image
COPY --from=cache-builder /cache/huggingface /cache/huggingface
ENV MODEL_CACHE_PATH=/cache/huggingface
ENV HF_DATASETS_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1
```

### Cache Migration Strategy

#### Step 1: Local Cache Verification
```python
# Verify current cache works
cache_path = "C:/Users/kord/.cache/huggingface"
model_path = f"{cache_path}/hub/models--nanonets--Nanonets-OCR-s"
if os.path.exists(model_path):
    print("✅ Local cache ready for migration")
```

#### Step 2: Storage Cache Setup
```python
# Copy cache to storage structure
storage_cache = "./storage/cache/huggingface"
shutil.copytree(cache_path, storage_cache)
```

#### Step 3: Cloud Cache Preparation
```bash
# Upload cache to GCS bucket
gsutil mb gs://gnosis-ocr-models
gsutil -m cp -r ~/.cache/huggingface/* gs://gnosis-ocr-models/huggingface/

# Verify upload
gsutil ls -r gs://gnosis-ocr-models/huggingface/hub/models--nanonets--Nanonets-OCR-s/
```

### Benefits of Integrated Cache Management

1. **🏠 Local Development**: Uses existing cache, no changes needed
2. **☁️ Cloud Deployment**: Automatic cache mounting and verification  
3. **🚀 Fast Startup**: Models load from cache, not downloaded
4. **💾 Storage Efficiency**: Shared cache across container instances
5. **🔄 Version Control**: Cache tied to storage architecture
6. **🛠️ Easy Migration**: Unified approach for all environments

This integrated approach ensures that model caching "just works" in both local development and cloud production, using the same storage service patterns for consistency and reliability.

This architecture will provide gnosis-ocr with the same robust, scalable storage system that gnosis-wraith uses, PLUS intelligent model cache management for seamless deployment across local development and cloud production environments.