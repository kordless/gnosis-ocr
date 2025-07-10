#!/bin/bash
# deploy-cloudrun.sh - Deploy gnosis-ocr to Google Cloud Run with GPU

set -e

# Load environment variables from .env.cloudrun
if [ -f ".env.cloudrun" ]; then
    echo "📋 Loading environment from .env.cloudrun..."
    export $(grep -v '^#' .env.cloudrun | xargs)
else
    echo "❌ .env.cloudrun file not found! Please create it with your PROJECT_ID."
    echo "💡 Copy .env.cloudrun.example and update PROJECT_ID"
    exit 1
fi

# Configuration from environment
PROJECT_ID="${PROJECT_ID:-your-gcp-project-id}"
SERVICE_NAME="gnosis-ocr"
REGION="europe-west1"
IMAGE_NAME="gcr.io/$PROJECT_ID/$SERVICE_NAME"

if [ "$PROJECT_ID" = "your-gcp-project-id" ]; then
    echo "❌ Please update PROJECT_ID in .env.cloudrun file"
    exit 1
fi


echo "🚀 Deploying gnosis-ocr to Cloud Run with GPU..."

# Build and push container
echo "📦 Building and pushing container image..."
gcloud builds submit --tag $IMAGE_NAME .

# Deploy to Cloud Run with GPU and GCS volume mount
echo "🌐 Deploying to Cloud Run with NVIDIA L4 GPU..."
gcloud run deploy $SERVICE_NAME \
  --image=$IMAGE_NAME \
  --region=$REGION \
  --platform=managed \
  --allow-unauthenticated \
  --memory=16Gi \
  --cpu=4 \
  --gpu=1 \
  --gpu-type=nvidia-l4 \
  --timeout=3600 \
  --concurrency=1 \
  --min-instances=1 \
  --max-instances=10 \
  --execution-environment=gen2 \
  --add-volume="name=model-cache,type=cloud-storage,bucket=gnosis-ocr-models" \
  --add-volume-mount="volume=model-cache,mount-path=/app/cache" \
  --set-env-vars="
RUNNING_IN_CLOUD=true,
GCS_BUCKET_NAME=gnosis-ocr-storage,
MODEL_BUCKET_NAME=gnosis-ocr-models,
MODEL_NAME=nanonets/Nanonets-OCR-s,
MODEL_CACHE_PATH=/app/cache,
HF_HOME=/app/cache,
TRANSFORMERS_CACHE=/app/cache,
HF_DATASETS_CACHE=/app/cache,
DEVICE=cuda,
CUDA_VISIBLE_DEVICES=0,
MAX_FILE_SIZE=104857600,
MAX_PAGES=100,
SESSION_TIMEOUT=1800,
CLEANUP_INTERVAL=180,
LOG_LEVEL=INFO
" \
  --service-account="gnosis-ocr-sa@$PROJECT_ID.iam.gserviceaccount.com"

echo "✅ Deployment complete!"
echo "🔗 Service URL: $(gcloud run services describe $SERVICE_NAME --region=$REGION --format='value(status.url)')"
echo "⚡ GPU: NVIDIA L4 with 16Gi memory and mounted model cache"
