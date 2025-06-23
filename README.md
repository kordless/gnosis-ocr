# Gnosis OCR - Production-Ready Cloud OCR Service

A high-performance, GPU-accelerated OCR service using the Nanonets-OCR-s model with intelligent caching, chunked streaming uploads, and enterprise-grade scalability.

## 🚀 Key Features

### Core OCR Capabilities
- 🎯 **GPU-Accelerated Processing** - NVIDIA L4 GPU with CUDA acceleration
- 🧠 **Advanced AI Model** - Nanonets-OCR-s with LaTeX equation support
- 📄 **PDF to Markdown** - High-quality text extraction with formatting
- 🖼️ **Page Image Extraction** - Individual page images at 300 DPI
- 📊 **Real-time Progress** - WebSocket-based live processing updates

### Enterprise File Handling
- 📦 **Massive File Support** - Up to 500MB PDFs via chunked streaming
- ⚡ **Smart Upload Strategy** - Auto-selects chunked vs direct upload
- 🔄 **Resilient Processing** - Network-tolerant with retry logic
- 🛡️ **Session Isolation** - Secure user data partitioning

### Cloud-Native Architecture
- ☁️ **Google Cloud Run** - Serverless deployment with auto-scaling
- 💾 **GCS FUSE Integration** - Persistent model caching
- 🧠 **Intelligent Caching** - Downloads models once, uses cache forever
- 🔧 **Zero-Config Deployment** - Automated infrastructure setup

## 📊 Performance Specs

| Feature | Specification |
|---------|---------------|
| **Max File Size** | 500MB (chunked streaming) |
| **Chunk Size** | 1MB (optimal for Cloud Run) |
| **GPU Memory** | 16GB allocated, 5GB model limit |
| **Processing Speed** | ~30 seconds per page (GPU) |
| **Concurrent Users** | 10 (configurable) |
| **Cache Strategy** | Persistent GCS FUSE mount |

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    GNOSIS OCR SERVICE                       │
├─────────────────────────────────────────────────────────────┤
│  Frontend (Static)     │  Backend (FastAPI)                │
│  ├─ Chunked Upload     │  ├─ Session Management            │
│  ├─ WebSocket Progress │  ├─ OCR Processing                │
│  ├─ Real-time UI      │  ├─ Storage Service               │
│  └─ Error Handling    │  └─ Progress Broadcasting         │
├─────────────────────────────────────────────────────────────┤
│                    STORAGE LAYER                            │
│  ┌─ GCS Bucket (Models) ─┐  ┌─ GCS Bucket (User Data) ─┐    │
│  │ /cache/huggingface/   │  │ /users/{hash}/{session}/ │    │
│  │ └─ Nanonets-OCR-s     │  │ ├─ upload.pdf            │    │
│  │   ├─ pytorch_model.bin│  │ ├─ page_001.png          │    │
│  │   └─ config.json     │  │ └─ combined_output.md    │    │
│  └───────────────────────┘  └─────────────────────────────┘    │
├─────────────────────────────────────────────────────────────┤
│                 CLOUD RUN DEPLOYMENT                        │
│  ├─ NVIDIA L4 GPU + 16GB RAM                               │
│  ├─ GCS FUSE Mount (model cache)                           │
│  ├─ Auto-scaling (0-3 instances)                           │
│  └─ Load Balancer + CDN                                    │
└─────────────────────────────────────────────────────────────┘
```

## 🛠️ Project Structure

```
gnosis-ocr/
├── README.md                           # This file
├── DEPLOYMENT_GUIDE.md                 # Cloud Run deployment
├── API_DOCUMENTATION.md                # Complete API reference
├── HUGGINGFACE_ONLINE.md              # HF caching strategy
├── HUGGING_FACE_NOTES.md              # Technical analysis
├── Dockerfile.lean                     # Production build
├── docker-compose.v2.yml              # V2 development
├── scripts/
│   ├── build-deploy-v2.ps1            # Complete deployment
│   └── deploy-v2-clean.ps1            # Quick deploy
├── app/
│   ├── main_v2.py                     # FastAPI V2 app
│   ├── ocr_service_v2_fixed.py        # OCR processing
│   ├── storage_service_v2.py          # Cloud storage
│   ├── models.py                      # Data models
│   └── config.py                      # Configuration
├── static/
│   ├── index.html                     # Upload interface
│   ├── style.css                      # Modern UI
│   └── script.js                      # Chunked upload
└── tests/
    ├── test_api.py                    # API testing
    └── test_cache_fix.py              # Cache validation
```

## 🚀 Quick Start

### Local Development

1. **Clone and Setup**:
```bash
git clone [repository] gnosis-ocr
cd gnosis-ocr
cp .env.example .env
```

2. **Run with Docker Compose V2**:
```bash
docker-compose -f docker-compose.v2.yml up --build
```

3. **Access Service**:
- Web UI: http://localhost:7799
- API Docs: http://localhost:7799/docs
- Health Check: http://localhost:7799/health

### Cloud Deployment

**PowerShell (Recommended)**:
```powershell
.\scripts\build-deploy-v2.ps1
```

**Quick Deploy Only**:
```powershell
.\scripts\deploy-v2-clean.ps1
```

**Manual gcloud**:
```bash
gcloud run deploy gnosis-ocr \
  --image gcr.io/gnosis-459403/gnosis-ocr:latest \
  --platform managed \
  --region us-central1 \
  --gpu 1 --gpu-type nvidia-l4 \
  --memory 16Gi --cpu 4 \
  --add-volume name=model-cache,type=cloud-storage,bucket=gnosis-ocr-models \
  --add-volume-mount volume=model-cache,mount-path=/cache
```

## 📡 API Reference

### Core Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/upload` | Upload PDF (traditional or chunked) |
| `POST` | `/upload/start` | Initialize chunked upload session |
| `POST` | `/upload/chunk/{session}` | Upload file chunk |
| `GET` | `/status/{session}` | Get processing status |
| `GET` | `/results/{session}` | Get OCR results |
| `GET` | `/download/{session}` | Download all files |

### WebSocket
- `WS` `/ws/progress/{session}` - Real-time progress updates

### Utility Endpoints
- `GET` `/health` - Service health check
- `GET` `/cache/info` - Model cache information
- `POST` `/api/log` - Frontend logging

## 🔧 Configuration

### Environment Variables

```bash
# Core Configuration
RUNNING_IN_CLOUD=true
MODEL_NAME=nanonets/Nanonets-OCR-s
PORT=7799
CUDA_VISIBLE_DEVICES=0

# Storage Configuration
STORAGE_PATH=/tmp/storage
GCS_BUCKET_NAME=gnosis-ocr-storage
MODEL_BUCKET_NAME=gnosis-ocr-models

# Cache Configuration (V2)
MODEL_CACHE_PATH=/cache/huggingface
HF_HOME=/cache/huggingface
TRANSFORMERS_CACHE=/cache/huggingface
HUGGINGFACE_HUB_CACHE=/cache/huggingface

# File Limits
MAX_FILE_SIZE=524288000  # 500MB
```

## 🎯 Usage Examples

### Simple Upload (≤10MB)
```javascript
const formData = new FormData();
formData.append('file', pdfFile);

const response = await fetch('/upload', {
    method: 'POST',
    body: formData
});
```

### Chunked Upload (>10MB)
```javascript
// Automatic chunked upload for large files
const fileInput = document.getElementById('file');
const file = fileInput.files[0];

if (file.size > 10 * 1024 * 1024) {
    // Automatically uses chunked upload with WebSocket progress
    await uploadFileChunked(file);
}
```

### WebSocket Progress
```javascript
const ws = new WebSocket(`ws://localhost:7799/ws/progress/${sessionId}`);
ws.onmessage = (event) => {
    const progress = JSON.parse(event.data);
    console.log(`Progress: ${progress.progress_percent}%`);
};
```

## 🧪 Testing

### Local Testing
```bash
# Run all tests
docker-compose run --rm app pytest

# Test cache functionality
python test_cache_fix.py

# Test large file upload
curl -X POST -F "file=@large_document.pdf" http://localhost:7799/upload
```

### Cache Validation
```bash
# Check model cache
curl http://localhost:7799/cache/info

# Verify HuggingFace files
python check_model_files.py
```

## 🔍 Monitoring & Debugging

### Health Monitoring
```bash
# Service health
curl https://your-service-url/health

# Cache status
curl https://your-service-url/cache/info

# Session debug
curl https://your-service-url/api/debug/session/{session_hash}
```

### Log Analysis
```bash
# Cloud Run logs
gcloud run services logs tail gnosis-ocr --region=us-central1

# Frontend logs (sent to backend)
# Check browser console and /api/log endpoint
```

## 🚨 Known Limitations

- **GPU Memory**: 5GB limit for model loading
- **File Types**: PDF only (configurable in settings)
- **Cold Start**: ~60 seconds for first model load
- **Concurrency**: Limited by GPU memory (10 concurrent max)

## 🔧 Troubleshooting

### Common Issues

1. **Model Download Fails**
   - Check internet connectivity during first deploy
   - Verify GCS bucket permissions
   - See `HUGGINGFACE_ONLINE.md` for details

2. **Large File Upload Timeout**
   - Chunked upload automatically activates >10MB
   - Check network stability for chunk failures

3. **GPU Out of Memory**
   - Reduce concurrent processing
   - Check model cache is using GCS mount

4. **Cache Not Working**
   - Verify GCS FUSE mount at `/cache`
   - Check environment variables match paths

## 📈 Performance Optimization

### For High Volume
```yaml
# Cloud Run scaling
--max-instances 10
--concurrency 5
--memory 16Gi
--cpu 4
```

### For Large Files
```javascript
// Increase chunk size for faster networks
const CHUNK_SIZE = 2 * 1024 * 1024; // 2MB chunks
```

### For Cold Starts
```bash
# Keep minimum instances warm
--min-instances 1
```

## 🔐 Security

- Session-based isolation (no cross-user access)
- User data partitioned by email hash
- Secure file handling with validation
- No persistent local storage of user data

## 📚 Documentation

- [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) - Complete deployment instructions
- [API_DOCUMENTATION.md](API_DOCUMENTATION.md) - Detailed API reference
- [HUGGINGFACE_ONLINE.md](HUGGINGFACE_ONLINE.md) - Caching strategy
- [PROJECT_STRUCTURE.md](PROJECT_STRUCTURE.md) - Code organization

## 🔄 Release Status

**Current Version**: V2 Production Ready
- ✅ Chunked streaming upload (500MB support)
- ✅ WebSocket progress tracking
- ✅ Intelligent HuggingFace caching
- ✅ Cloud Run GPU deployment
- ✅ Error resilience and retry logic
- ✅ Production monitoring and debugging

## 📄 License

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

See [LICENSE](LICENSE) for the full license text.

