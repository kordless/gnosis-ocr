# Cloud Run Model Mounting Options for Gnosis OCR

## Option 1: GCS FUSE Mount (Recommended)
# This mounts the GCS bucket as a filesystem

# Update deploy.ps1 to include GCS FUSE mount
$DeployCmd = @(
    "gcloud", "run", "deploy", $ServiceName,
    "--image", $LatestTag,
    "--platform", "managed", 
    "--region", $Region,
    "--allow-unauthenticated",
    "--port", "7799",
    "--memory", "8Gi",
    "--cpu", "4", 
    "--timeout", "900",
    "--concurrency", "10",
    "--max-instances", "5",
    # GCS FUSE mount configuration
    "--execution-environment", "gen2",
    "--volume", "name=model-cache,type=cloud-storage,bucket=gnosis-ocr-models",
    "--volume-mount", "name=model-cache,mount-path=/cache",
    "--quiet"
)

## Option 2: Persistent Disk (Better Performance)
# Requires pre-creating a disk with models

# 1. Create persistent disk
gcloud compute disks create gnosis-ocr-cache `
    --size=20GB `
    --zone=us-central1-a `
    --type=pd-ssd

# 2. Mount in Cloud Run (gen2 only)
$DeployCmd += "--volume", "name=cache-disk,type=persistent-disk,disk-name=gnosis-ocr-cache"
$DeployCmd += "--volume-mount", "name=cache-disk,mount-path=/cache"

## Option 3: Container Image with Models (Largest Image)
# Build models into the container image

# Dockerfile.with-models
FROM nvidia/cuda:12.2.2-cudnn8-runtime-ubuntu22.04
# ... base setup ...

# Copy model cache into image
COPY cache/huggingface /cache/huggingface
ENV MODEL_CACHE_PATH=/cache/huggingface

## Option 4: Download at Runtime (Slowest)
# Download models on first startup - not recommended for production

ENV MODEL_CACHE_PATH=/tmp/models
# Models download to /tmp on first request

## Current Issue: No Mount Configured!
# The current deployment script sets MODEL_CACHE_PATH=/cache/huggingface
# but doesn't actually mount anything to /cache
# This means the container will try to download models at runtime
