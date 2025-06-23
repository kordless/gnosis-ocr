# Gnosis OCR Cloud Deployment Configuration

## 🚀 Deployment Script Usage

### Basic Deployment (V1 Architecture)
```powershell
.\scripts\deploy.ps1
```

### V2 Architecture Deployment (Recommended)
```powershell
.\scripts\deploy.ps1 -UseV2
```

### Skip Specific Steps
```powershell
# Skip build (if image already exists)
.\scripts\deploy.ps1 -SkipBuild

# Skip push (test deployment changes only)
.\scripts\deploy.ps1 -SkipPush

# Build and push only (no deployment)
.\scripts\deploy.ps1 -SkipDeploy
```

### Custom Project/Service
```powershell
.\scripts\deploy.ps1 -ProjectId "your-project" -ServiceName "custom-ocr" -Region "us-east1"
```

## 🗄️ Storage Setup for Cloud Deployment

### Step 1: Create GCS Buckets
```bash
# Create storage bucket for user files
gsutil mb gs://gnosis-ocr-storage

# Create model cache bucket
gsutil mb gs://gnosis-ocr-models

# Set appropriate permissions
gsutil iam ch serviceAccount:your-service-account@project.iam.gserviceaccount.com:objectAdmin gs://gnosis-ocr-storage
gsutil iam ch serviceAccount:your-service-account@project.iam.gserviceaccount.com:objectViewer gs://gnosis-ocr-models
```

### Step 2: Upload Model Cache (One-time setup)
```bash
# Upload your local HuggingFace cache to GCS
gsutil -m cp -r C:\Users\kord\.cache\huggingface\* gs://gnosis-ocr-models/huggingface/

# Verify upload
gsutil ls -r gs://gnosis-ocr-models/huggingface/hub/models--nanonets--Nanonets-OCR-s/
```

### Step 3: Configure Cloud Run Service
The deployment script automatically sets these environment variables:

**V2 Architecture Variables:**
- `RUNNING_IN_CLOUD=true`
- `STORAGE_PATH=/tmp/storage`
- `GCS_BUCKET_NAME=gnosis-ocr-storage`
- `MODEL_BUCKET_NAME=gnosis-ocr-models`
- `MODEL_CACHE_PATH=/cache/huggingface`

## 💾 Model Cache Deployment Options

### Option A: GCS FUSE Mount (Recommended)
```yaml
# Cloud Run with GCS FUSE
annotations:
  run.googleapis.com/volume-mounts: '[{"name":"cache","path":"/cache"}]'
  run.googleapis.com/volumes: '[{"name":"cache","gcs":{"bucket":"gnosis-ocr-models"}}]'
```

### Option B: Persistent Disk
```yaml
# Attach persistent SSD with pre-loaded models
annotations:
  run.googleapis.com/volume-mounts: '[{"name":"cache-disk","path":"/cache"}]'
  run.googleapis.com/volumes: '[{"name":"cache-disk","persistentVolumeClaim":{"claimName":"model-cache"}}]'
```

### Option C: Container with Built-in Cache
```dockerfile
# Build cache into container image (increases image size)
COPY cache/huggingface /cache/huggingface
```

## 🔧 Cloud Run Configuration

### Resource Allocation
- **Memory:** 8Gi (OCR models are large)
- **CPU:** 4 cores (intensive processing)
- **Timeout:** 900s (OCR processing can be slow)
- **Concurrency:** 10 (GPU workloads)
- **Max Instances:** 5 (GPU resource limits)

### Environment Variables
```bash
# Core OCR settings
MODEL_NAME=nanonets/Nanonets-OCR-s
PORT=7799
CUDA_VISIBLE_DEVICES=0

# V2 Storage Architecture
RUNNING_IN_CLOUD=true
STORAGE_PATH=/tmp/storage
GCS_BUCKET_NAME=gnosis-ocr-storage
MODEL_BUCKET_NAME=gnosis-ocr-models
MODEL_CACHE_PATH=/cache/huggingface

# Offline mode (use cached models only)
HF_DATASETS_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

## 🧪 Testing Deployment

### Health Check
```bash
curl https://your-service-url/health
```

Expected response:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "gpu_available": true,
  "model_loaded": true,
  "storage_available": true,
  "cache_info": {
    "path": "/cache/huggingface",
    "exists": true,
    "size_gb": 7.4,
    "model_count": 1
  }
}
```

### Cache Information
```bash
curl https://your-service-url/cache/info
```

### Upload Test
```bash
curl -X POST https://your-service-url/upload \
  -H "X-User-Email: test@example.com" \
  -F "file=@test.pdf"
```

## 🔍 Monitoring and Logs

### Stream Logs
```bash
gcloud run services logs tail gnosis-ocr --region=us-central1 --follow
```

### Monitor Performance
```bash
# CPU and Memory usage
gcloud monitoring metrics list --filter="resource.type=cloud_run_revision"

# Request metrics
gcloud run services describe gnosis-ocr --region=us-central1 --format="value(status.traffic[0].latestRevision)"
```

## 🚨 Troubleshooting

### Common Issues

1. **Model not found in cache**
   - Verify cache bucket exists and contains models
   - Check service account permissions
   - Ensure `MODEL_CACHE_PATH` is correct

2. **Out of memory errors**
   - Increase memory allocation to 16Gi
   - Check GPU memory usage
   - Verify model cache is properly mounted

3. **Storage access denied**
   - Verify GCS bucket permissions
   - Check service account has Storage Object Admin role
   - Ensure `GCS_BUCKET_NAME` environment variable is set

4. **GPU not available**
   - Cloud Run doesn't support GPU by default
   - Consider using Google Kubernetes Engine (GKE) for GPU workloads
   - Or deploy on Compute Engine with GPU

### Debug Commands
```bash
# Check container logs
gcloud run services logs tail gnosis-ocr --region=us-central1

# Describe service configuration
gcloud run services describe gnosis-ocr --region=us-central1

# Check bucket contents
gsutil ls -r gs://gnosis-ocr-storage/
gsutil ls -r gs://gnosis-ocr-models/
```

## 📈 Production Considerations

### Scaling
- Set minimum instances to 1 for faster cold starts
- Configure autoscaling based on request volume
- Monitor GPU utilization and adjust accordingly

### Security
- Use IAM service accounts with minimal permissions
- Enable VPC connector for private network access
- Configure Cloud Armor for DDoS protection

### Cost Optimization
- Use preemptible instances where possible
- Implement request batching for efficiency
- Monitor storage costs and implement lifecycle policies

### Backup and Recovery
- Regular backups of user data in GCS
- Version control for model cache
- Disaster recovery procedures documented
