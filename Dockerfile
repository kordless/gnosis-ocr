# Lightweight Dockerfile for Gnosis OCR Service - Models mounted from GCS
FROM nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04

# Install Python and essential system dependencies only
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3.11-distutils \
    python3-pip \
    git \
    libgl1-mesa-glx \
    libglib2.0-0 \
    poppler-utils \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*


# Set Python 3.11 as default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 && \
    wget https://bootstrap.pypa.io/get-pip.py && \
    python get-pip.py && \
    rm get-pip.py

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt

# Install core ML dependencies WITHOUT flash attention - use latest transformers for qwen2_5_vl support
RUN pip install --no-cache-dir torch==2.1.2 torchvision==0.16.2 'numpy<2.0' && \
    pip install --no-cache-dir git+https://github.com/huggingface/transformers.git qwen-vl-utils



# Create non-root user
RUN useradd -m -s /bin/bash appuser

# Create cache directory structure (models will be mounted here)
RUN mkdir -p /app/cache && chown -R appuser:appuser /app/cache

# Copy application code (includes static and templates)
COPY --chown=appuser:appuser app/ ./app/

# Create base directory for OCR sessions (storage will be mounted here)
RUN mkdir -p /app/storage && \
    chmod -R 777 /app/storage && \
    chown -R appuser:appuser /app/storage


# Switch to non-root user for security
USER appuser

# Environment variables - models come from mounted volume
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=7799 \
    HOST=0.0.0.0 \
    HF_HOME="/app/cache" \
    MODEL_CACHE_PATH="/app/cache" \
    TRANSFORMERS_CACHE="/app/cache" \
    HF_DATASETS_CACHE="/app/cache" \
    MODEL_NAME="nanonets/Nanonets-OCR-s" \
    STORAGE_PATH="/app/storage"


# Expose port
EXPOSE 7799

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Run the application directly with uvicorn
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7799"]
