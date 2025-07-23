#!/bin/bash

# Gnosis OCR Deployment Script
# Builds and deploys the OCR service for local (Docker Compose) or Cloud Run.

set -e # Exit immediately if a command exits with a non-zero status.

TARGET="local"
TAG="latest"
REBUILD=false

# --- Parse Command Line Arguments ---
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -t|--target) TARGET="$2"; shift ;;
        --tag) TAG="$2"; shift ;;
        --rebuild) REBUILD=true ;;
        -h|--help)
            echo "USAGE: ./deploy.sh [-t|--target <local|cloudrun>] [--tag <tag>] [--rebuild]"
            exit 0
            ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

# --- Project Configuration ---
IMAGE_NAME="gnosis-ocr"
FULL_IMAGE_NAME="${IMAGE_NAME}:${TAG}"
DOCKERFILE="Dockerfile.unified"

echo "=== Gnosis OCR Deployment ==="
echo "Target: ${TARGET}, Image: ${FULL_IMAGE_NAME}"

# --- Build Docker Image ---
echo -e "\n=== Building Docker Image ==="
BUILD_ARGS="build -f ${DOCKERFILE} -t ${FULL_IMAGE_NAME} ."
if [ "$REBUILD" = true ]; then
    BUILD_ARGS+=" --no-cache"
fi

echo "Running: docker ${BUILD_ARGS}"
eval "docker ${BUILD_ARGS}"
echo "✓ Build completed successfully"

# --- Deployment ---
echo -e "\n=== Deploying to ${TARGET} ==="

if [ "$TARGET" == "local" ]; then
    echo "Deploying locally with Docker Compose..."
    docker-compose down
    docker-compose up -d --build
    echo "✓ Service started successfully. Available at http://localhost:7799"

elif [ "$TARGET" == "cloudrun" ]; then
    echo "Deploying to Google Cloud Run..."

    # Load environment variables from .env.cloudrun
    if [ ! -f .env.cloudrun ]; then
        echo "Error: .env.cloudrun not found." >&2
        exit 1
    fi
    set -a
    source .env.cloudrun
    set +a

    if [ -z "$PROJECT_ID" ] || [ -z "$GCP_SERVICE_ACCOUNT" ] || [ -z "$MODEL_BUCKET_NAME" ]; then
        echo "Error: PROJECT_ID, GCP_SERVICE_ACCOUNT, or MODEL_BUCKET_NAME missing in .env.cloudrun" >&2
        exit 1
    fi

    GCR_IMAGE="gcr.io/${PROJECT_ID}/${IMAGE_NAME}:${TAG}"

    # Tag, Authenticate, and Push
    echo "Tagging image for GCR..."
    docker tag ${FULL_IMAGE_NAME} ${GCR_IMAGE}
    gcloud auth configure-docker -q
    echo "Pushing image to GCR..."
    docker push ${GCR_IMAGE}
    echo "✓ Image pushed successfully."

    # Prepare environment variables for gcloud command
    ENV_VARS=$(grep -v '^#' .env.cloudrun | grep -v 'PROJECT_ID' | tr '\n' ',' | sed 's/,$//')

    # Deploy to Cloud Run
    echo "Deploying service 'gnosis-ocr' to Cloud Run..."
    gcloud run deploy gnosis-ocr \
      --image "${GCR_IMAGE}" \
      --region "us-central1" \
      --platform "managed" \
      --allow-unauthenticated \
      --min-instances "0" \
      --max-instances "3" \
      --concurrency "8" \
      --service-account "${GCP_SERVICE_ACCOUNT}" \
      --add-volume "name=model-cache,type=cloud-storage,bucket=${MODEL_BUCKET_NAME}" \
      --add-volume-mount "volume=model-cache,mount-path=/app/cache" \
      --set-env-vars "${ENV_VARS}" \
      --port "8080" \
      --execution-environment "gen2"

    SERVICE_URL=$(gcloud run services describe gnosis-ocr --region=us-central1 --format="value(status.url)")
    echo "✓ CLOUD RUN DEPLOYMENT SUCCESSFUL!"
    echo "🔗 Service URL: ${SERVICE_URL}"

else
    echo "Error: Invalid target '${TARGET}'. Use 'local' or 'cloudrun'." >&2
    exit 1
fi

echo -e "\n=== Deployment Complete ==="