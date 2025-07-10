# 🐳 Docker Guide

## Prerequisites

### 1. Install Docker Desktop
- **Windows/Mac**: [Download Docker Desktop](https://www.docker.com/products/docker-desktop/)
- **Linux**: [Install Docker Engine](https://docs.docker.com/engine/install/)

### 2. Enable GPU Support

#### Windows (WSL2)
```powershell
# Install WSL2 with GPU support
wsl --install
# Enable GPU in Docker Desktop settings
```

#### Linux
```bash
# Install NVIDIA Container Toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update && sudo apt-get install -y nvidia-docker2
sudo systemctl restart docker
```

### 3. Verify GPU Access
```bash
docker run --rm --gpus all nvidia/cuda:12.2.2-base-ubuntu22.04 nvidia-smi
```

## 🚀 Quick Start

### Local Development
```bash
# Clone and start
git clone https://github.com/your-org/gnosis-ocr.git
cd gnosis-ocr

# Build and run with GPU
docker-compose up --build

# Or use scripts
./scripts/deploy.ps1 -Target local
```

### Production Build
```bash
# Build optimized image
docker build -f Dockerfile.cloudrun -t gnosis-ocr:prod .

# Run production container
docker run -d \
  --name gnosis-ocr-prod \
  --gpus all \
  -p 8080:8080 \
  -e RUNNING_IN_CLOUD=true \
  gnosis-ocr:prod
```

## 📁 Docker Files

| File | Purpose | Use Case |
|------|---------|----------|
| `Dockerfile` | Local development | GPU development with hot reload |
| `Dockerfile.cloudrun` | Production | Optimized for Cloud Run deployment |
| `docker-compose.yml` | Local stack | Complete development environment |

## 🔧 Configuration

### Environment Variables
```yaml
environment:
  - PORT=7799                    # Service port
  - CUDA_VISIBLE_DEVICES=0       # GPU device
  - MODEL_CACHE_PATH=/app/cache  # Model storage
  - MAX_FILE_SIZE=524288000      # 500MB limit
  - LOG_LEVEL=INFO               # Logging level
```

### Volume Mounts
```yaml
volumes:
  - ./model-cache:/app/cache     # Persistent model cache
  - ./app:/app/app              # Hot reload (dev only)
  - ocr_sessions_data:/tmp/ocr_sessions  # Session storage
```

## 🚨 Troubleshooting

### GPU Not Detected
```bash
# Check NVIDIA drivers
nvidia-smi

# Verify Docker GPU access
docker run --rm --gpus all nvidia/cuda:12.2.2-base-ubuntu22.04 nvidia-smi

# Check Docker Desktop GPU settings (Windows/Mac)
```

### Out of Memory
```bash
# Monitor GPU memory
docker exec gnosis-ocr-local nvidia-smi

# Reduce batch size in environment
-e BATCH_SIZE=1
```

### Model Download Issues
```bash
# Clear model cache
docker volume rm gnosis-ocr_model-cache

# Manual download
docker exec gnosis-ocr-local python -c "
from transformers import AutoModelForVision2Seq, AutoProcessor
model = AutoModelForVision2Seq.from_pretrained('nanonets/Nanonets-OCR-s')
"
```

### Container Won't Start
```bash
# Check logs
docker logs gnosis-ocr-local

# Debug shell
docker exec -it gnosis-ocr-local /bin/bash

# Health check
curl http://localhost:7799/health
```

## 🔍 Monitoring

### Container Logs
```bash
# Follow logs
docker logs -f gnosis-ocr-local

# Last 100 lines
docker logs --tail 100 gnosis-ocr-local
```

### Resource Usage
```bash
# Container stats
docker stats gnosis-ocr-local

# GPU usage
docker exec gnosis-ocr-local nvidia-smi

# Disk usage
docker system df
```

## 🧹 Cleanup

### Remove Containers
```bash
# Stop and remove
docker stop gnosis-ocr-local
docker rm gnosis-ocr-local

# Remove all OCR containers
docker ps -a | grep gnosis-ocr | awk '{print $1}' | xargs docker rm -f
```

### Clean Images
```bash
# Remove unused images
docker image prune

# Remove specific image
docker rmi gnosis-ocr:latest

# Clean everything
docker system prune -a
```

## 🏗️ Custom Builds

### Minimal CPU Build
```dockerfile
FROM python:3.11-slim
# Install CPU-only dependencies
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
```

### Multi-Stage Build
```dockerfile
# Stage 1: Dependencies
FROM nvidia/cuda:12.2.2-runtime-ubuntu22.04 as base
RUN apt-get update && apt-get install -y python3

# Stage 2: Application
FROM base as app
COPY requirements.txt .
RUN pip install -r requirements.txt
```

## 📊 Performance Tuning

### Memory Optimization
```yaml
# docker-compose.yml
services:
  app:
    shm_size: 2gb  # Increase shared memory
    ulimits:
      memlock: -1  # Unlimited memory lock
      stack: 67108864  # Stack size
```

### GPU Optimization
```bash
# Set GPU memory growth
-e TF_FORCE_GPU_ALLOW_GROWTH=true

# Limit GPU memory
-e CUDA_VISIBLE_DEVICES=0
-e NVIDIA_VISIBLE_DEVICES=0
```

Need help? Check our [main documentation](../README.md) or open an [issue](https://github.com/your-org/gnosis-ocr/issues).
