# Complete V2 Build, Push & Deploy Script - Clean Syntax
# Combines build/push with the reliable deployment from deploy-v2-clean.ps1
param(
    [string]$ProjectId = "gnosis-459403",
    [string]$ServiceName = "gnosis-ocr",
    [string]$Region = "us-central1",
    [switch]$SkipBuild = $false,
    [switch]$SkipPush = $false,
    [switch]$SkipDeploy = $false
)

$Platform = "linux/amd64"
$ImageName = "gcr.io/$ProjectId/$ServiceName"
$LatestTag = "${ImageName}:latest"

# Colors for output
function Write-Status { param($Message) Write-Host "✅ $Message" -ForegroundColor Green }
function Write-Warning { param($Message) Write-Host "⚠️  $Message" -ForegroundColor Yellow }
function Write-Error { param($Message) Write-Host "❌ $Message" -ForegroundColor Red }
function Write-Info { param($Message) Write-Host "ℹ️  $Message" -ForegroundColor Cyan }
function Write-Header { param($Message) Write-Host "`n🚀 $Message" -ForegroundColor Blue }

Write-Header "Gnosis OCR V2 - Complete Build & Deploy"
Write-Host "=======================================" -ForegroundColor Blue

# Get git info for tagging
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
try {
    $GitSha = git rev-parse --short HEAD 2>$null
    if (-not $GitSha) { $GitSha = "unknown" }
} catch {
    $GitSha = "unknown"
}

$TimestampTag = "${ImageName}:${Timestamp}"
$ShaTag = "${ImageName}:${GitSha}"

Write-Info "Configuration:"
Write-Host "  Project ID: $ProjectId" -ForegroundColor Gray
Write-Host "  Service: $ServiceName" -ForegroundColor Gray  
Write-Host "  Region: $Region" -ForegroundColor Gray
Write-Host "  Image: $ImageName" -ForegroundColor Gray
Write-Host "  Git SHA: $GitSha" -ForegroundColor Gray
Write-Host "  Timestamp: $Timestamp" -ForegroundColor Gray

# Step 1: Build Docker image
if (-not $SkipBuild) {
    Write-Header "Step 1: Building V2 Docker Image"
    
    Write-Info "Using Dockerfile.lean (models loaded from GCS mount)"
    
    $buildArgs = @(
        "build",
        "--platform", $Platform,
        "-f", "Dockerfile.lean",
        "-t", $LatestTag,
        "-t", $TimestampTag, 
        "-t", $ShaTag,
        "."
    )
    
    Write-Host "Executing: docker $($buildArgs -join ' ')" -ForegroundColor Cyan
    & docker @buildArgs
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Docker build failed"
        exit 1
    }
    
    Write-Status "Docker build completed successfully"
    
    # Show image size
    $ImageSize = docker images $LatestTag --format "table {{.Size}}" | Select-Object -Skip 1
    Write-Info "Built image size: $ImageSize"
} else {
    Write-Warning "Skipping Docker build (--SkipBuild specified)"
}

# Step 2: Configure Docker for GCR
if (-not $SkipPush -and -not $SkipBuild) {
    Write-Header "Step 2: Configuring Docker Authentication"
    
    gcloud auth configure-docker --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to configure Docker authentication"
        exit 1
    }
    
    Write-Status "Docker authentication configured"
}

# Step 3: Push images to GCR  
if (-not $SkipPush) {
    Write-Header "Step 3: Pushing Images to Google Container Registry"
    
    Write-Info "Pushing latest tag..."
    docker push $LatestTag
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to push latest tag"
        exit 1
    }
    
    Write-Info "Pushing timestamp tag..."
    docker push $TimestampTag
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to push timestamp tag" 
        exit 1
    }
    
    Write-Info "Pushing git SHA tag..."
    docker push $ShaTag
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to push SHA tag"
        exit 1
    }
    
    Write-Status "All images pushed to GCR successfully"
} else {
    Write-Warning "Skipping image push (--SkipPush specified)"
}

# Step 4: Deploy to Cloud Run (using clean syntax from deploy-v2-clean.ps1)
if (-not $SkipDeploy) {
    Write-Header "Step 4: Deploying to Cloud Run with V2 Configuration"
    
    # Use PowerShell array instead of cursed backticks (from deploy-v2-clean.ps1)
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
        "--set-env-vars", "RUNNING_IN_CLOUD=true,STORAGE_PATH=/tmp/storage,GCS_BUCKET_NAME=gnosis-ocr-storage,MODEL_BUCKET_NAME=gnosis-ocr-models,MODEL_CACHE_PATH=/cache/huggingface,HF_HOME=/cache/huggingface,TRANSFORMERS_CACHE=/cache/huggingface,HUGGINGFACE_HUB_CACHE=/cache/huggingface,HF_HUB_DISABLE_SYMLINKS_WARNING=1",

        "--quiet"
    )
    
    Write-Host "Executing: gcloud $($deployArgs -join ' ')" -ForegroundColor Cyan
    & gcloud @deployArgs
    
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Deployment failed"
        exit 1
    }
    
    Write-Status "Deployment successful!"
} else {
    Write-Warning "Skipping Cloud Run deployment (--SkipDeploy specified)"
}

# Step 5: Get service information
if (-not $SkipDeploy) {
    Write-Header "Step 5: Getting Service Information"
    
    try {
        $ServiceUrl = gcloud run services describe $ServiceName --region=$Region --format="value(status.url)"
        
        Write-Host "`n🎉 Deployment Summary" -ForegroundColor Green
        Write-Host "=====================" -ForegroundColor Green
        Write-Host "  Service URL: " -NoNewline -ForegroundColor Gray
        Write-Host $ServiceUrl -ForegroundColor Cyan
        Write-Host "  Images deployed:" -ForegroundColor Gray
        Write-Host "    - $LatestTag" -ForegroundColor Gray
        Write-Host "    - $TimestampTag" -ForegroundColor Gray
        Write-Host "    - $ShaTag" -ForegroundColor Gray
        
        Write-Host "`n🔗 Quick Links:" -ForegroundColor Blue
        Write-Host "  Service URL: $ServiceUrl" -ForegroundColor Cyan
        Write-Host "  Health Check: $ServiceUrl/health" -ForegroundColor Cyan
        Write-Host "  Logger Fix: Fixed recursive logging issue ✅" -ForegroundColor Green
        
        Write-Host "`n✨ V2 Features:" -ForegroundColor Magenta
        Write-Host "  - NVIDIA L4 GPU acceleration" -ForegroundColor Gray
        Write-Host "  - 16GB memory allocation" -ForegroundColor Gray
        Write-Host "  - GCS model cache mount (/cache)" -ForegroundColor Gray
        Write-Host "  - Clean PowerShell deployment syntax" -ForegroundColor Gray
        Write-Host "  - Fixed logger (no recursive logging)" -ForegroundColor Gray
        
    } catch {
        Write-Warning "Could not retrieve service information: $_"
    }
}

Write-Host "`n🎊 V2 Build & Deploy completed successfully!" -ForegroundColor Green
