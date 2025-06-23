# Gnosis OCR - Build, Push & Deploy Script (PowerShell)
# This script builds the Docker image, pushes to GCR, and deploys to Cloud Run

param(
    [string]$ProjectId = "gnosis-459403",
    [string]$ServiceName = "gnosis-ocr",
    [string]$Region = "us-central1",
    [switch]$SkipBuild = $false,
    [switch]$SkipPush = $false,
    [switch]$SkipDeploy = $false,
    [switch]$UseV2 = $false
)

# Configuration
$Platform = "linux/amd64"
$ImageName = "gcr.io/$ProjectId/$ServiceName"

# Colors for output (PowerShell)
function Write-Status { param($Message) Write-Host "✅ $Message" -ForegroundColor Green }
function Write-Warning { param($Message) Write-Host "⚠️  $Message" -ForegroundColor Yellow }
function Write-Error { param($Message) Write-Host "❌ $Message" -ForegroundColor Red }
function Write-Info { param($Message) Write-Host "ℹ️  $Message" -ForegroundColor Cyan }
function Write-Header { param($Message) Write-Host "`n🚀 $Message" -ForegroundColor Blue }

Write-Header "Gnosis OCR Deployment Script"
Write-Host "================================" -ForegroundColor Blue

# Check prerequisites
Write-Info "Checking prerequisites..."

# Check if gcloud is installed
try {
    $gcloudVersion = gcloud version --format="value(Google Cloud SDK)" 2>$null
    Write-Status "Google Cloud SDK found: $gcloudVersion"
} catch {
    Write-Error "gcloud CLI not found. Please install Google Cloud SDK."
    exit 1
}

# Check if docker is running
try {
    docker info 2>$null | Out-Null
    Write-Status "Docker is running"
} catch {
    Write-Error "Docker is not running. Please start Docker."
    exit 1
}

# Check for NVIDIA Docker support (OCR service needs GPU)
try {
    $dockerInfo = docker info 2>$null
    if ($dockerInfo -like "*nvidia*") {
        Write-Status "NVIDIA Docker runtime detected"
    } else {
        Write-Warning "NVIDIA Docker runtime not detected - GPU support may not work in container"
    }
} catch {
    Write-Warning "Could not check Docker runtime information"
}

# Get current timestamp and git info for tagging
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
try {
    $GitSha = git rev-parse --short HEAD 2>$null
    if (-not $GitSha) { $GitSha = "unknown" }
} catch {
    $GitSha = "unknown"
}

# Image tags
$LatestTag = "${ImageName}:latest"
$TimestampTag = "${ImageName}:${Timestamp}"
$ShaTag = "${ImageName}:${GitSha}"

Write-Info "Configuration:"
Write-Host "  Project ID: $ProjectId" -ForegroundColor Gray
Write-Host "  Service: $ServiceName" -ForegroundColor Gray
Write-Host "  Region: $Region" -ForegroundColor Gray
Write-Host "  Image: $ImageName" -ForegroundColor Gray
Write-Host "  Git SHA: $GitSha" -ForegroundColor Gray
Write-Host "  Timestamp: $Timestamp" -ForegroundColor Gray
if ($UseV2) {
    Write-Host "  Architecture: V2 (New Storage)" -ForegroundColor Magenta
} else {
    Write-Host "  Architecture: V1 (Legacy)" -ForegroundColor Gray
}

# Pre-deployment checks
Write-Header "Pre-deployment checks..."

# Check if cache exists locally
$CachePath = "$env:USERPROFILE\.cache\huggingface"
if (Test-Path $CachePath) {
    $CacheSize = (Get-ChildItem $CachePath -Recurse | Measure-Object -Property Length -Sum).Sum / 1GB
    Write-Status "HuggingFace cache found: $([math]::Round($CacheSize, 2)) GB"
} else {
    Write-Warning "HuggingFace cache not found at $CachePath - model download will be required during build"
}

# Check storage directory
$StoragePath = ".\storage"
if (Test-Path $StoragePath) {
    Write-Status "Storage directory exists"
} else {
    Write-Info "Creating storage directory structure..."
    New-Item -ItemType Directory -Path "$StoragePath\users" -Force | Out-Null
    New-Item -ItemType Directory -Path "$StoragePath\logs" -Force | Out-Null
    New-Item -ItemType Directory -Path "$StoragePath\cache" -Force | Out-Null
    Write-Status "Storage directory created"
}

# Step 1: Build Docker image
if (-not $SkipBuild) {
    Write-Header "Step 1: Building Docker image..."
    
    try {
        Write-Info "Building OCR service image (this may take 10-15 minutes due to model download)..."
        
        # Use lean dockerfile for V2 (no models in image - uses GCS mount)
        $DockerfilePath = if ($UseV2) { "Dockerfile.lean" } else { "Dockerfile" }
        
        if ($UseV2 -and -not (Test-Path $DockerfilePath)) {
            Write-Warning "V2 Dockerfile not found, using standard Dockerfile"
            $DockerfilePath = "Dockerfile"
        }
        
        if ($UseV2) {
            Write-Info "Using lean Dockerfile - models will be mounted from GCS (no 5.5GB model layer)"
        }
        
        docker build --platform $Platform `
            -f $DockerfilePath `
            -t $LatestTag `
            -t $TimestampTag `
            -t $ShaTag `
            .
        
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Docker build failed"
            exit 1
        }
        
        Write-Status "Docker build completed successfully"
        
        # Show image size
        $ImageSize = docker images $LatestTag --format "table {{.Size}}" | Select-Object -Skip 1
        Write-Info "Built image size: $ImageSize"
        
    } catch {
        Write-Error "Failed to build Docker image: $_"
        exit 1
    }
} else {
    Write-Warning "Skipping Docker build (--SkipBuild specified)"
}

# Step 2: Configure Docker for GCR
if (-not $SkipPush -and -not $SkipBuild) {
    Write-Header "Step 2: Configuring Docker authentication..."
    
    try {
        gcloud auth configure-docker --quiet
        Write-Status "Docker authentication configured"
    } catch {
        Write-Error "Failed to configure Docker authentication: $_"
        exit 1
    }
}

# Step 3: Push images to GCR
if (-not $SkipPush) {
    Write-Header "Step 3: Pushing images to Google Container Registry..."
    
    try {
        Write-Info "Pushing latest tag..."
        docker push $LatestTag
        if ($LASTEXITCODE -ne 0) { throw "Failed to push latest tag" }
        
        Write-Info "Pushing timestamp tag..."
        docker push $TimestampTag
        if ($LASTEXITCODE -ne 0) { throw "Failed to push timestamp tag" }
        
        Write-Info "Pushing git SHA tag..."
        docker push $ShaTag
        if ($LASTEXITCODE -ne 0) { throw "Failed to push SHA tag" }
        
        Write-Status "All images pushed to GCR successfully"
    } catch {
        Write-Error "Failed to push images: $_"
        exit 1
    }
} else {
    Write-Warning "Skipping image push (--SkipPush specified)"
}

# Step 4: Deploy to Cloud Run
if (-not $SkipDeploy) {
    Write-Header "Step 4: Deploying to Cloud Run..."
    
    try {
        Write-Info "Deploying OCR service with GPU acceleration..."
        
        # Deployment will be handled with direct gcloud calls below
        Write-Info "Preparing deployment configuration..."
        
        # Execute deployment with proper argument handling
        Write-Info "Executing deployment command..."
        
        if ($UseV2) {
            # V2 deployment with GCS FUSE mount
            gcloud run deploy $ServiceName `
                --image $LatestTag `
                --platform managed `
                --region $Region `
                --allow-unauthenticated `
                --port 7799 `
                --memory 16Gi `
                --cpu 4 `
                --timeout 900 `
                --concurrency 10 `
                --max-instances 3 `

                --execution-environment gen2 `
                --gpu 1 `
                --gpu-type nvidia-l4 `
                --add-volume "name=model-cache,type=cloud-storage,bucket=gnosis-ocr-models" `
                --add-volume-mount "volume=model-cache,mount-path=/cache" `
                --set-env-vars "RUNNING_IN_CLOUD=true,STORAGE_PATH=/tmp/storage,GCS_BUCKET_NAME=gnosis-ocr-storage,MODEL_BUCKET_NAME=gnosis-ocr-models,MODEL_CACHE_PATH=/cache/huggingface" `
                --quiet
        } else {

            # V1 deployment without mounting
            gcloud run deploy $ServiceName `
                --image $LatestTag `
                --platform managed `
                --region $Region `
                --allow-unauthenticated `
                --port 7799 `
                --memory 16Gi `
                --cpu 4 `
                --timeout 900 `
                --concurrency 10 `
                --max-instances 3 `

                --gpu 1 `
                --gpu-type nvidia-l4 `
                --set-env-vars "STORAGE_PATH=/tmp/ocr_sessions,MODEL_NAME=nanonets/Nanonets-OCR-s" `
                --quiet

        }
        
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Cloud Run deployment failed"
            exit 1
        }
        
        Write-Status "Deployment to Cloud Run completed successfully"
    } catch {
        Write-Error "Failed to deploy to Cloud Run: $_"
        exit 1
    }
} else {
    Write-Warning "Skipping Cloud Run deployment (--SkipDeploy specified)"
}

# Step 5: Get service information
if (-not $SkipDeploy) {
    Write-Header "Step 5: Getting service information..."
    
    try {
        $ServiceUrl = gcloud run services describe $ServiceName --region=$Region --format="value(status.url)"
        Write-Status "Service information retrieved"
        
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
        Write-Host "  Cloud Console: https://console.cloud.google.com/run/detail/$Region/$ServiceName" -ForegroundColor Cyan
        Write-Host "  Container Images: https://console.cloud.google.com/gcr/images/$ProjectId" -ForegroundColor Cyan
        
        Write-Host "`n✨ Next Steps:" -ForegroundColor Magenta
        Write-Host "  1. Test the health endpoint: $ServiceUrl/health" -ForegroundColor Gray
        Write-Host "  2. Upload a test PDF for OCR processing" -ForegroundColor Gray
        Write-Host "  3. Check logs: gcloud run services logs tail $ServiceName --region=$Region" -ForegroundColor Gray
        Write-Host "  4. Monitor GPU usage and performance in Cloud Console" -ForegroundColor Gray
        
        if ($UseV2) {
            Write-Host "`n🗄️ Storage Architecture (V2):" -ForegroundColor Cyan
            Write-Host "  - User isolation: Hash-based partitioning" -ForegroundColor Gray
            Write-Host "  - File storage: Google Cloud Storage" -ForegroundColor Gray
            Write-Host "  - Model cache: Persistent disk mount" -ForegroundColor Gray
            Write-Host "  - Cache info: $ServiceUrl/cache/info" -ForegroundColor Gray
        }
        
        # Optional: Test health endpoint
        $testHealth = Read-Host "`nTest health endpoint? (y/N)"
        if ($testHealth -eq 'y' -or $testHealth -eq 'Y') {
            Write-Info "Testing health endpoint..."
            try {
                $healthResponse = Invoke-RestMethod -Uri "$ServiceUrl/health" -TimeoutSec 30
                Write-Status "Health check passed!"
                Write-Host "  Status: $($healthResponse.status)" -ForegroundColor Gray
                Write-Host "  GPU Available: $($healthResponse.gpu_available)" -ForegroundColor Gray
                Write-Host "  Model Loaded: $($healthResponse.model_loaded)" -ForegroundColor Gray
            } catch {
                Write-Warning "Health check failed: $_"
            }
        }
        
        # Optional: Open service URL in browser
        $openBrowser = Read-Host "`nOpen service URL in browser? (y/N)"
        if ($openBrowser -eq 'y' -or $openBrowser -eq 'Y') {
            Start-Process $ServiceUrl
        }
        
        # Optional: Stream logs
        $streamLogs = Read-Host "`nStream live logs? (y/N)"
        if ($streamLogs -eq 'y' -or $streamLogs -eq 'Y') {
            Write-Info "Starting log stream (Ctrl+C to stop)..."
            gcloud run services logs tail $ServiceName --region=$Region --follow
        }
        
    } catch {
        Write-Warning "Could not retrieve service information: $_"
    }
}

Write-Host "`n🎊 OCR deployment script completed!" -ForegroundColor Green

# Return to original directory if we changed it
Pop-Location -ErrorAction SilentlyContinue
