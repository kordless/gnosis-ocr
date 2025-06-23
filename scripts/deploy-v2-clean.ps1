# Quick V2 deployment script - avoiding the cursed backticks!
param(
    [string]$ProjectId = "gnosis-459403",
    [string]$ServiceName = "gnosis-ocr",
    [string]$Region = "us-central1"
)

$ImageName = "gcr.io/$ProjectId/$ServiceName"
$LatestTag = "${ImageName}:latest"

Write-Host "🚀 Deploying V2 with clean syntax..." -ForegroundColor Green

# Use PowerShell array instead of cursed backticks
$deployArgs = @(
    "run", "deploy", $ServiceName,
    "--image", $LatestTag,
    "--platform", "managed", 
    "--region", $Region,
    "--allow-unauthenticated",
    "--port", "7799",
    "--memory", "16Gi",
    "--cpu", "4", 
    "--timeout", "900",
    "--concurrency", "10",
    "--max-instances", "3",
    "--execution-environment", "gen2",
    "--gpu", "1",
    "--gpu-type", "nvidia-l4",
    "--add-volume", "name=model-cache,type=cloud-storage,bucket=gnosis-ocr-models",
    "--add-volume-mount", "volume=model-cache,mount-path=/cache", 
    "--set-env-vars", "RUNNING_IN_CLOUD=true,STORAGE_PATH=/tmp/storage,GCS_BUCKET_NAME=gnosis-ocr-storage,MODEL_BUCKET_NAME=gnosis-ocr-models,MODEL_CACHE_PATH=/cache/huggingface",
    "--quiet"
)

Write-Host "Executing: gcloud $($deployArgs -join ' ')" -ForegroundColor Cyan
& gcloud @deployArgs


if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ Deployment successful!" -ForegroundColor Green
} else {
    Write-Host "❌ Deployment failed!" -ForegroundColor Red
    exit 1
}
