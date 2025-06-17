# Project Structure

This document details the complete file structure and contents needed for the Gnosis OCR service.

## Core Application Files

### `/app/__init__.py`
```python
"""Gnosis OCR Service - GPU-accelerated document OCR"""
__version__ = "1.0.0"
```

### `/app/main.py`
Main FastAPI application with endpoints for:
- Document upload
- Status checking
- Results retrieval
- Image access
- Health checks

Key features:
- Session-based isolation using UUID
- Background processing with progress tracking
- Automatic cleanup of old sessions
- CORS support for web clients

### `/app/models.py`
Pydantic models for request/response validation:
- `UploadResponse` - Response after file upload
- `SessionStatus` - Current processing status
- `ProcessingStatus` - Enum for status states
- `OCRResult` - Final OCR results
- `ErrorResponse` - Error details

### `/app/ocr_service.py`
Core OCR processing logic:
- Model initialization with GPU support
- PDF to image conversion
- Page-by-page OCR processing
- Progress tracking
- Memory optimization

### `/app/storage_service.py`
File and session management:
- Session directory creation
- File upload handling
- Session validation
- Automatic cleanup scheduler
- Status persistence

### `/app/config.py`
Configuration management:
- Environment variables
- File size limits
- Session timeouts
- GPU settings
- Model parameters

## Frontend Files

### `/static/index.html`
Single-page upload interface with:
- Drag-and-drop file upload
- Real-time progress tracking
- Results display with syntax highlighting
- Download options

### `/static/style.css`
Modern, responsive styling:
- Dark/light theme support
- Loading animations
- Progress bars
- Mobile-friendly design

### `/static/script.js`
Frontend JavaScript:
- File upload handling
- WebSocket/polling for progress
- Result rendering
- Error handling

## Docker Configuration

### `/Dockerfile`
Multi-stage build:
1. Model download stage
2. Runtime stage with CUDA support
3. Non-root user setup
4. Optimized for Cloud Run

### `/docker-compose.yml`
```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8080:8080"
    environment:
      - CUDA_VISIBLE_DEVICES=0
    volumes:
      - ./data:/tmp/ocr_sessions
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

## Configuration Files

### `/requirements.txt`
Core dependencies:
- FastAPI & Uvicorn
- Transformers & PyTorch
- PDF processing libraries
- Image processing tools
- Monitoring & logging

### `/.env.example`
```env
# Server Configuration
PORT=8080
HOST=0.0.0.0

# OCR Settings
MAX_FILE_SIZE=52428800  # 50MB
SESSION_TIMEOUT=3600    # 1 hour
MAX_PAGES=500

# GPU Configuration
CUDA_VISIBLE_DEVICES=0
TORCH_CUDA_ARCH_LIST=7.0;7.5;8.0;8.6

# Model Settings
MODEL_NAME=nanonets/Nanonets-OCR-s
MAX_NEW_TOKENS=8192

# Storage
STORAGE_PATH=/tmp/ocr_sessions
CLEANUP_INTERVAL=300  # 5 minutes

# Logging
LOG_LEVEL=INFO
```

## Test Files

### `/tests/test_api.py`
API endpoint tests:
- Upload validation
- Status checking
- Result retrieval
- Error handling
- Session isolation

### `/tests/test_ocr.py`
OCR service tests:
- Model loading
- PDF processing
- GPU utilization
- Memory management

### `/tests/test_storage.py`
Storage service tests:
- Session creation
- File handling
- Cleanup verification
- Concurrency safety

## Deployment Files

### `/cloudbuild.yaml`
Cloud Build configuration for automated deployment

### `/.gcloudignore`
Files to exclude from Cloud Run deployment

### `/cloud-run-deploy.sh`
Deployment script with GPU configuration

## Directory Structure During Runtime

```
/tmp/ocr_sessions/
├── {session-hash-1}/
│   ├── input/
│   │   └── document.pdf
│   ├── images/
│   │   ├── page_001.png
│   │   ├── page_002.png
│   │   └── ...
│   ├── output/
│   │   ├── page_001.md
│   │   ├── page_002.md
│   │   ├── combined_output.md
│   │   └── metadata.json
│   └── status.json
└── {session-hash-2}/
    └── ...
```

## Key Design Decisions

1. **Session Isolation**: Each upload gets a UUID preventing cross-access
2. **Ephemeral Storage**: Use /tmp for Cloud Run compatibility
3. **Background Processing**: Non-blocking uploads with progress tracking
4. **GPU Optimization**: Batch processing when possible
5. **Auto-cleanup**: Prevent storage overflow with timed cleanup
6. **Health Checks**: Cloud Run readiness/liveness probes
