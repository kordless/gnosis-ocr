# Implementation Guide

This guide provides step-by-step instructions for implementing the Gnosis OCR service using Claude Code.

## Phase 1: Core Setup

### Step 1: Create Project Structure

```bash
# In gnosis/development/nanonets/
mkdir -p gnosis-ocr/{app,static,tests}
cd gnosis-ocr
```

### Step 2: Create Configuration Files

Start with `app/config.py`:
```python
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    
    # OCR
    model_name: str = "nanonets/Nanonets-OCR-s"
    max_new_tokens: int = 8192
    device_map: str = "auto"
    
    # Storage
    storage_path: str = "/tmp/ocr_sessions"
    max_file_size: int = 52428800  # 50MB
    session_timeout: int = 3600  # 1 hour
    cleanup_interval: int = 300  # 5 minutes
    
    # GPU
    cuda_visible_devices: str = "0"
    
    class Config:
        env_file = ".env"

settings = Settings()
```

### Step 3: Create Pydantic Models

Create `app/models.py`:
```python
from pydantic import BaseModel
from datetime import datetime
from enum import Enum
from typing import Optional, List

class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class UploadResponse(BaseModel):
    session_hash: str
    filename: str
    status: ProcessingStatus
    upload_time: datetime

class SessionStatus(BaseModel):
    session_hash: str
    status: ProcessingStatus
    progress: Optional[float] = None
    current_page: Optional[int] = None
    total_pages: Optional[int] = None
    error: Optional[str] = None
    processing_time: Optional[float] = None

class OCRResult(BaseModel):
    session_hash: str
    content: str
    page_count: int
    processing_time: float
    pages: List[str]
```

## Phase 2: Storage Service

Create `app/storage_service.py`:
```python
import os
import json
import shutil
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict
import aiofiles
from fastapi import UploadFile

from .config import settings
from .models import ProcessingStatus, SessionStatus

class StorageService:
    def __init__(self):
        self.base_path = Path(settings.storage_path)
        self.base_path.mkdir(exist_ok=True)
    
    async def create_session(self, session_hash: str) -> Path:
        """Create session directory structure"""
        session_path = self.base_path / session_hash
        
        # Create subdirectories
        (session_path / "input").mkdir(parents=True)
        (session_path / "images").mkdir(parents=True)
        (session_path / "output").mkdir(parents=True)
        
        # Initialize status
        status = {
            "session_hash": session_hash,
            "status": ProcessingStatus.PENDING,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat()
        }
        
        async with aiofiles.open(session_path / "status.json", "w") as f:
            await f.write(json.dumps(status))
        
        return session_path
    
    async def save_upload(self, session_hash: str, file: UploadFile) -> Path:
        """Save uploaded file"""
        session_path = self.get_session_path(session_hash)
        file_path = session_path / "input" / "document.pdf"
        
        async with aiofiles.open(file_path, "wb") as f:
            content = await file.read()
            await f.write(content)
        
        return file_path
```

## Phase 3: OCR Service

Create `app/ocr_service.py`:
```python
import torch
from pathlib import Path
from typing import Dict, List
import fitz  # PyMuPDF
from PIL import Image
import io
from transformers import AutoTokenizer, AutoProcessor, AutoModelForImageTextToText

from .config import settings

class OCRService:
    def __init__(self):
        self.model = None
        self.processor = None
        self.tokenizer = None
        self.model_loaded = False
    
    def load_model(self):
        """Load the OCR model"""
        if self.model_loaded:
            return
        
        model_kwargs = {
            "torch_dtype": torch.float16 if torch.cuda.is_available() else torch.float32,
            "device_map": settings.device_map
        }
        
        self.model = AutoModelForImageTextToText.from_pretrained(
            settings.model_name,
            **model_kwargs
        )
        self.model.eval()
        
        self.tokenizer = AutoTokenizer.from_pretrained(settings.model_name)
        self.processor = AutoProcessor.from_pretrained(settings.model_name)
        
        self.model_loaded = True
    
    def pdf_to_images(self, pdf_path: Path, output_dir: Path) -> List[Path]:
        """Convert PDF pages to images"""
        pdf_document = fitz.open(str(pdf_path))
        image_paths = []
        
        for page_num in range(len(pdf_document)):
            page = pdf_document[page_num]
            mat = fitz.Matrix(300/72, 300/72)  # 300 DPI
            pix = page.get_pixmap(matrix=mat)
            
            img_data = pix.pil_tobytes(format="PNG")
            img = Image.open(io.BytesIO(img_data))
            
            img_path = output_dir / f"page_{page_num + 1:03d}.png"
            img.save(img_path)
            image_paths.append(img_path)
        
        pdf_document.close()
        return image_paths
```

## Phase 4: FastAPI Application

Create `app/main.py`:
```python
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uuid

from .models import UploadResponse, SessionStatus, ProcessingStatus
from .ocr_service import OCRService
from .storage_service import StorageService
from .config import settings

app = FastAPI(title="Gnosis OCR Service")

# Initialize services
storage_service = StorageService()
ocr_service = OCRService()

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.on_event("startup")
async def startup_event():
    """Load model on startup"""
    ocr_service.load_model()

@app.get("/")
async def root():
    """Redirect to upload UI"""
    return FileResponse("static/index.html")

@app.post("/upload", response_model=UploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    """Upload endpoint implementation"""
    # Validate file type
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    
    # Create session
    session_hash = str(uuid.uuid4())
    await storage_service.create_session(session_hash)
    
    # Save file
    await storage_service.save_upload(session_hash, file)
    
    # Start background processing
    background_tasks.add_task(process_document, session_hash)
    
    return UploadResponse(
        session_hash=session_hash,
        filename=file.filename,
        status=ProcessingStatus.PROCESSING,
        upload_time=datetime.utcnow()
    )
```

## Phase 5: Docker Configuration

Create `Dockerfile`:
```dockerfile
# Multi-stage build for Gnosis OCR
FROM python:3.9-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Download model during build
RUN pip install huggingface-hub
RUN python -c "from huggingface_hub import snapshot_download; \
    snapshot_download('nanonets/Nanonets-OCR-s', cache_dir='/model')"

# Runtime stage
FROM nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04

# Install Python and dependencies
RUN apt-get update && apt-get install -y \
    python3.9 python3-pip \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy model from builder
COPY --from=builder /model /root/.cache/huggingface

# Install Python packages
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/
COPY static/ ./static/

# Create non-root user
RUN useradd -m -u 1000 ocruser && \
    chown -R ocruser:ocruser /app && \
    mkdir -p /tmp/ocr_sessions && \
    chown -R ocruser:ocruser /tmp/ocr_sessions

USER ocruser

EXPOSE 8080

CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

## Phase 6: Frontend Interface

Create `static/index.html`:
```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gnosis OCR Service</title>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <div class="container">
        <h1>Gnosis OCR Service</h1>
        <div id="upload-area" class="upload-area">
            <p>Drag & Drop PDF here or click to browse</p>
            <input type="file" id="file-input" accept=".pdf" hidden>
        </div>
        <div id="progress" class="progress hidden">
            <div class="progress-bar"></div>
            <p class="progress-text">Processing...</p>
        </div>
        <div id="results" class="results hidden">
            <h2>OCR Results</h2>
            <pre id="ocr-content"></pre>
            <button id="download-btn">Download Results</button>
        </div>
    </div>
    <script src="/static/script.js"></script>
</body>
</html>
```

## Testing

Create `tests/test_api.py`:
```python
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_upload_pdf():
    with open("test_document.pdf", "rb") as f:
        response = client.post(
            "/upload",
            files={"file": ("test.pdf", f, "application/pdf")}
        )
    assert response.status_code == 200
    assert "session_hash" in response.json()
```

## Next Steps

1. **Implement remaining endpoints** in main.py
2. **Complete the OCR processing** in ocr_service.py
3. **Add progress tracking** to storage service
4. **Create frontend JavaScript** for upload and progress
5. **Write docker-compose.yml** for local development
6. **Test with sample PDFs**
7. **Deploy to Cloud Run**

Use Claude Code to implement each file based on the patterns shown above.
