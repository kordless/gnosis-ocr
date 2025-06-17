# Deployment Guide - Google Cloud Run

This guide covers deploying the Gnosis OCR service to Google Cloud Run with GPU support.

## Prerequisites

1. Google Cloud Project with billing enabled
2. Google Cloud SDK installed (`gcloud`)
3. Docker installed locally
4. Artifact Registry API enabled
5. Cloud Run API enabled

## Initial Setup

### 1. Configure Google Cloud

```bash
# Set your project ID
export PROJECT_ID="your-project-id"
export REGION="us-central1"  # Choose region with GPU support
export SERVICE_NAME="gnosis-ocr"

# Configure gcloud
gcloud config set project $PROJECT_ID
gcloud auth login
gcloud auth configure-docker ${REGION}-docker.pkg.dev
```

### 2. Enable Required APIs

```bash
gcloud services enable run.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable cloudbuild.googleapis.com
```

### 3. Create Artifact Registry Repository

```bash
gcloud artifacts repositories create gnosis-ocr \
  --repository-format=docker \
  --location=${REGION} \
  --description="Gnosis OCR Docker images"
```

## Build and Push Docker Image

### 1. Build the Image

```bash
# From the gnosis-ocr directory
docker build -t ${REGION}-docker.pkg.dev/${PROJECT_ID}/gnosis-ocr/app:latest .
```

### 2. Push to Artifact Registry

```bash
docker push ${REGION}-docker.pkg.dev/${PROJECT_ID}/gnosis-ocr/app:latest
```

## Deploy to Cloud Run

### 1. Create Cloud Run Service with GPU

```bash
gcloud run deploy ${SERVICE_NAME} \
  --image=${REGION}-docker.pkg.dev/${PROJECT_ID}/gnosis-ocr/app:latest \
  --platform=managed \
  --region=${REGION} \
  --memory=8Gi \
  --cpu=2 \
  --timeout=600 \
  --concurrency=1 \
  --gpu=1 \
  --gpu-type=nvidia-t4 \
  --no-cpu-throttling \
  --allow-unauthenticated \
  --set-env-vars="CUDA_VISIBLE_DEVICES=0"
```

### 2. Alternative: Using cloud-run.yaml

Create `cloud-run.yaml`:

```yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: gnosis-ocr
  labels:
    cloud.googleapis.com/location: us-central1
spec:
  template:
    metadata:
      annotations:
        run.googleapis.com/execution-environment: gen2
        run.googleapis.com/gpu: "1"
        run.googleapis.com/gpu-type: nvidia-t4
    spec:
      containerConcurrency: 1
      timeoutSeconds: 600
      serviceAccountName: gnosis-ocr-sa
      containers:
      - image: us-central1-docker.pkg.dev/PROJECT_ID/gnosis-ocr/app:latest
        resources:
          limits:
            cpu: "2"
            memory: 8Gi
        env:
        - name: CUDA_VISIBLE_DEVICES
          value: "0"
        - name: MAX_FILE_SIZE
          value: "52428800"
        - name: SESSION_TIMEOUT
          value: "3600"
```

Deploy with:
```bash
gcloud run services replace cloud-run.yaml --region=${REGION}
```

## Service Account and Permissions

### 1. Create Service Account

```bash
gcloud iam service-accounts create gnosis-ocr-sa \
  --display-name="Gnosis OCR Service Account"
```

### 2. Grant Permissions

```bash
# Basic Cloud Run permissions
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:gnosis-ocr-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# If using Cloud Storage for persistent storage
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:gnosis-ocr-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

## Configure Custom Domain (Optional)

### 1. Map Custom Domain

```bash
gcloud run domain-mappings create \
  --service=${SERVICE_NAME} \
  --domain=ocr.yourdomain.com \
  --region=${REGION}
```

### 2. Update DNS Records

Add the provided DNS records to your domain provider.

## Monitoring and Logging

### 1. View Logs

```bash
gcloud logging read "resource.type=cloud_run_revision \
  AND resource.labels.service_name=${SERVICE_NAME}" \
  --limit=50 \
  --format=json
```

### 2. Set Up Alerts

```bash
# CPU utilization alert
gcloud alpha monitoring policies create \
  --notification-channels=CHANNEL_ID \
  --display-name="High CPU Usage - Gnosis OCR" \
  --condition-display-name="CPU > 80%" \
  --condition-threshold-value=0.8 \
  --condition-threshold-duration=300s
```

## Cost Optimization

### 1. Set Maximum Instances

```bash
gcloud run services update ${SERVICE_NAME} \
  --max-instances=5 \
  --region=${REGION}
```

### 2. Configure Minimum Instances

```bash
# Scale to zero when not in use
gcloud run services update ${SERVICE_NAME} \
  --min-instances=0 \
  --region=${REGION}
```

## Environment Variables

Set production environment variables:

```bash
gcloud run services update ${SERVICE_NAME} \
  --set-env-vars="LOG_LEVEL=INFO" \
  --set-env-vars="MAX_FILE_SIZE=104857600" \
  --set-env-vars="SESSION_TIMEOUT=7200" \
  --set-env-vars="CLEANUP_INTERVAL=600" \
  --region=${REGION}
```

## Continuous Deployment

### 1. Cloud Build Configuration

Create `cloudbuild.yaml`:

```yaml
steps:
  # Build the container image
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', '${_REGION}-docker.pkg.dev/$PROJECT_ID/gnosis-ocr/app:$COMMIT_SHA', '.']
  
  # Push the container image
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', '${_REGION}-docker.pkg.dev/$PROJECT_ID/gnosis-ocr/app:$COMMIT_SHA']
  
  # Deploy to Cloud Run
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
    - 'run'
    - 'deploy'
    - 'gnosis-ocr'
    - '--image=${_REGION}-docker.pkg.dev/$PROJECT_ID/gnosis-ocr/app:$COMMIT_SHA'
    - '--region=${_REGION}'
    - '--platform=managed'

substitutions:
  _REGION: us-central1

options:
  machineType: 'E2_HIGHCPU_8'
```

### 2. Set Up Trigger

```bash
gcloud builds triggers create github \
  --repo-name=gnosis-ocr \
  --repo-owner=your-github-username \
  --branch-pattern="^main$" \
  --build-config=cloudbuild.yaml
```

## Testing the Deployment

### 1. Get Service URL

```bash
SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} \
  --region=${REGION} \
  --format='value(status.url)')

echo "Service URL: ${SERVICE_URL}"
```

### 2. Test Health Endpoint

```bash
curl ${SERVICE_URL}/health
```

### 3. Test Upload

```bash
curl -X POST ${SERVICE_URL}/upload \
  -F "file=@test.pdf"
```

## Troubleshooting

### GPU Not Available

Check GPU availability:
```bash
gcloud compute accelerator-types list --filter="zone:${REGION}-*"
```

### Out of Memory

Increase memory allocation:
```bash
gcloud run services update ${SERVICE_NAME} \
  --memory=16Gi \
  --region=${REGION}
```

### Cold Start Issues

Set minimum instances:
```bash
gcloud run services update ${SERVICE_NAME} \
  --min-instances=1 \
  --region=${REGION}
```

## Security Best Practices

1. **Enable Authentication**
   ```bash
   gcloud run services update ${SERVICE_NAME} \
     --no-allow-unauthenticated \
     --region=${REGION}
   ```

2. **Use Secret Manager for Sensitive Data**
   ```bash
   echo -n "your-secret-value" | gcloud secrets create api-key --data-file=-
   
   gcloud run services update ${SERVICE_NAME} \
     --set-secrets="API_KEY=api-key:latest" \
     --region=${REGION}
   ```

3. **Enable VPC Connector**
   ```bash
   gcloud run services update ${SERVICE_NAME} \
     --vpc-connector=projects/${PROJECT_ID}/locations/${REGION}/connectors/my-connector \
     --region=${REGION}
   ```

## Performance Optimization

1. **Use Cloud CDN for Static Assets**
2. **Enable HTTP/2**
3. **Configure appropriate concurrency limits**
4. **Use Cloud Storage for large files instead of /tmp**

## Monitoring Dashboard

Create a custom dashboard in Cloud Console:
1. Go to Monitoring > Dashboards
2. Create new dashboard
3. Add widgets for:
   - Request count
   - Request latency
   - GPU utilization
   - Error rate
   - Memory usage

## Cost Estimation

GPU-enabled Cloud Run pricing (approximate):
- vCPU: $0.00002400 per vCPU-second
- Memory: $0.00000250 per GiB-second
- GPU: $0.00055 per GPU-second (T4)
- Requests: $0.40 per million requests

Monthly estimate for moderate usage:
- 1000 documents/month
- Average 2 minutes processing time
- Total: ~$50-100/month
