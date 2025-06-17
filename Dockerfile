# Multi-stage build for Gnosis OCR Service
# Stage 1: Download model weights
FROM python:3.11-slim as model-downloader

WORKDIR /model

# Install git and other dependencies
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Install latest transformers from source for qwen2_5_vl support
RUN pip install --no-cache-dir torch==2.1.2 torchvision==0.16.2 'numpy<2.0' && \
    pip install --no-cache-dir git+https://github.com/huggingface/transformers.git qwen-vl-utils

# Download model weights
RUN python -c "import os; \
    os.environ['HF_HUB_DISABLE_SYMLINKS'] = '1'; \
    os.environ['TRANSFORMERS_CACHE'] = '/root/.cache/huggingface'; \
    from transformers import AutoModel, AutoProcessor; \
    print('Downloading Nanonets-OCR-s model...'); \
    model = AutoModel.from_pretrained('nanonets/Nanonets-OCR-s', trust_remote_code=True); \
    processor = AutoProcessor.from_pretrained('nanonets/Nanonets-OCR-s', trust_remote_code=True); \
    print('Model downloaded successfully')"

# Stage 2: Runtime image with CUDA support
FROM nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04

# Install Python and system dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3.11-distutils \
    python3-pip \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libgdal-dev \
    poppler-utils \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.11 as default and install pip properly
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 && \
    wget https://bootstrap.pypa.io/get-pip.py && \
    python get-pip.py && \
    rm get-pip.py

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

# Create non-root user first
RUN useradd -m -s /bin/bash appuser

# Copy model weights from downloader stage to appuser's cache
COPY --from=model-downloader --chown=appuser:appuser /root/.cache/huggingface /home/appuser/.cache/huggingface

# Copy application code
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser static/ ./static/

# Ensure proper permissions
RUN chown -R appuser:appuser /app && \
    chmod -R 755 /app

# Create directories for OCR sessions
RUN mkdir -p /tmp/ocr_sessions && \
    chown -R appuser:appuser /tmp/ocr_sessions

# Switch to non-root user
USER appuser

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7799 \
    HOST=0.0.0.0 \
    CUDA_VISIBLE_DEVICES=0 \
    TORCH_CUDA_ARCH_LIST="7.0;7.5;8.0;8.6" \
    MODEL_NAME="nanonets/Nanonets-OCR-s" \
    STORAGE_PATH="/tmp/ocr_sessions"

# Expose port
EXPOSE 7799

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Run the application
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7799"]