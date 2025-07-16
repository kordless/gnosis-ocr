# Deploy Cloud Run with environment variables for Cloud OCR
# PowerShell script to update gnosis-ocr Cloud Run service

Write-Host "Updating gnosis-ocr Cloud Run service with Cloud Tasks environment variables..." -ForegroundColor Green

# Essential Cloud Tasks variables only (Cloud Run sets PORT automatically)
gcloud run services update gnosis-ocr `
  --region=us-central1 `
  --set-env-vars="RUNNING_IN_CLOUD=true,CLOUD_TASKS_PROJECT=gnosis-459403,CLOUD_TASKS_LOCATION=us-central1,CLOUD_TASKS_QUEUE=ocr-processing,WORKER_SERVICE_URL=https://gnosis-ocr-949870462453.us-central1.run.app,OCR_BATCH_SIZE=10"

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Cloud Run service updated successfully!" -ForegroundColor Green
    Write-Host "🚀 Cloud OCR with Cloud Tasks should now be operational" -ForegroundColor Cyan
} else {
    Write-Host "❌ Failed to update Cloud Run service" -ForegroundColor Red
    Write-Host "Try the minimal command instead:" -ForegroundColor Yellow
    Write-Host 'gcloud run services update gnosis-ocr --region=us-central1 --set-env-vars="RUNNING_IN_CLOUD=true,CLOUD_TASKS_PROJECT=gnosis-459403,CLOUD_TASKS_LOCATION=us-central1,CLOUD_TASKS_QUEUE=ocr-processing,WORKER_SERVICE_URL=https://gnosis-ocr-949870462453.us-central1.run.app,OCR_BATCH_SIZE=10"' -ForegroundColor Yellow
}