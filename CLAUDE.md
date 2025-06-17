# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Key Commands

### Local Development
```bash
# Build and run with GPU support
docker-compose up --build

# Run without GPU (CPU only)
docker-compose up --build -e DEVICE=cpu

# Run the service
docker-compose up app

# View logs
docker-compose logs -f app

# Access the service
# Web UI: http://localhost:7799
# API Docs: http://localhost:7799/docs
```

### Testing
```bash
# Run all tests
docker-compose run --rm app pytest

# Run specific test file
docker-compose run --rm app pytest tests/test_api.py

# Run with coverage
docker-compose run --rm app pytest --cov=app --cov-report=html

# Run tests with verbose output
docker-compose run --rm app pytest -v
```

### Cloud Run Deployment
```bash
# Build for Cloud Run
docker build -t us-central1-docker.pkg.dev/$PROJECT_ID/gnosis-ocr/app:latest .

# Deploy with GPU
gcloud run deploy gnosis-ocr \
  --image=us-central1-docker.pkg.dev/$PROJECT_ID/gnosis-ocr/app:latest \
  --platform=managed \
  --region=us-central1 \
  --memory=8Gi \
  --cpu=2 \
  --timeout=600 \
  --concurrency=1 \
  --gpu=1 \
  --gpu-type=nvidia-t4 \
  --set-env-vars="CUDA_VISIBLE_DEVICES=0"
```

## Architecture Overview

### Service Design
The Gnosis OCR service is a GPU-accelerated document processing system built around session-based isolation. Each document upload creates a unique session UUID that serves as both an access token and directory namespace, preventing cross-contamination between users' documents.

### Core Components

1. **OCR Service** (`app/ocr_service.py`): Manages the Nanonets-OCR-s model, handling GPU memory efficiently by loading the model once at startup and processing pages in batches when possible.

2. **Storage Service** (`app/storage_service.py`): Implements ephemeral file storage with automatic cleanup. Each session gets its own directory structure under `/tmp/ocr_sessions/{session-hash}/` with subdirectories for input PDFs, extracted images, and output markdown.

3. **Background Processing**: Document processing happens asynchronously after upload. The main FastAPI thread returns immediately with a session hash, while background tasks handle the compute-intensive OCR operations.

4. **Progress Tracking**: Status is persisted to `status.json` files within each session directory, enabling progress queries without database dependencies.

### GPU Optimization Strategy
- Model weights are downloaded during Docker build to avoid runtime delays
- The model stays loaded in GPU memory between requests
- Memory is cleared after each document to prevent OOM errors
- Batch processing is used when multiple pages fit in memory

### Session Lifecycle
1. Upload creates session directory and returns hash
2. Background task converts PDF to images (300 DPI)
3. Each page is processed through the OCR model
4. Results are saved as markdown with LaTeX equation support
5. Cleanup scheduler removes sessions after timeout

### Directory Structure at Runtime
```
/tmp/ocr_sessions/
├── {session-hash}/
│   ├── input/document.pdf
│   ├── images/page_001.png, page_002.png, ...
│   ├── output/
│   │   ├── page_001.md, page_002.md, ...
│   │   ├── combined_output.md
│   │   └── metadata.json
│   └── status.json
```

### Key Design Decisions
- **No Database Required**: Uses filesystem for all state management
- **Cloud Run Compatible**: Designed for ephemeral /tmp storage
- **GPU-First**: Optimized for NVIDIA T4 GPUs on Cloud Run
- **Session Isolation**: UUID-based access prevents data leakage
- **Auto-Scaling**: Stateless design allows horizontal scaling

## Development Notes

### Environment Variables
The service reads from `.env` file in development. Key variables:
- `PORT`: Service port (default: 7799)
- `DEVICE`: cuda or cpu
- `MAX_FILE_SIZE`: Upload limit in bytes
- `SESSION_TIMEOUT`: Cleanup delay in seconds
- `MODEL_NAME`: Hugging Face model identifier

### Adding New Endpoints
1. Define Pydantic models in `app/models.py`
2. Implement business logic in appropriate service
3. Add FastAPI route in `app/main.py`
4. Write tests in `tests/`

### Docker Cache Management

**IMPORTANT**: The model download stage caches 6GB+ of model weights. To preserve this cache:

```bash
# When updating only application code
docker-compose build app --build-arg BUILDKIT_INLINE_CACHE=1

# If you must rebuild everything
docker build --target model-downloader -t gnosis-ocr-model-cache .
# Then use it as cache source
docker build --cache-from gnosis-ocr-model-cache -t gnosis-ocr .
```

**Cache-preserving changes**:
- Changes to app/, static/, or requirements.txt won't bust model cache
- Changes to the model download stage WILL require re-downloading 6GB
- Use multi-stage builds to isolate model downloads from app changes

### Debugging GPU Issues
```bash
# Check GPU availability
docker-compose run --rm app python -c "import torch; print(torch.cuda.is_available())"

# Monitor GPU memory
nvidia-smi -l 1

# Test model loading
docker-compose run --rm app python -c "from app.ocr_service import OCRService; ocr = OCRService(); ocr.load_model()"
```

### Common Issues
- **OOM Errors**: Reduce batch size or increase GPU memory allocation
- **Slow Startup**: Model weights not cached in Docker image
- **Connection Refused**: Check PORT environment variable matches exposure
- **Session Not Found**: Session expired and was cleaned up