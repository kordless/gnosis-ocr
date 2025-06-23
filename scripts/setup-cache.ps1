# Gnosis OCR - Model Cache Setup Script
# This script helps set up the model cache for cloud deployment

param(
    [string]$ProjectId = "gnosis-459403",
    [string]$ModelBucket = "gnosis-ocr-models",
    [string]$LocalCachePath = "$env:USERPROFILE\.cache\huggingface",
    [switch]$CreateBucket = $false,
    [switch]$UploadCache = $false,
    [switch]$VerifyCache = $false,
    [switch]$All = $false
)

# Colors for output
function Write-Status { param($Message) Write-Host "✅ $Message" -ForegroundColor Green }
function Write-Warning { param($Message) Write-Host "⚠️  $Message" -ForegroundColor Yellow }
function Write-Error { param($Message) Write-Host "❌ $Message" -ForegroundColor Red }
function Write-Info { param($Message) Write-Host "ℹ️  $Message" -ForegroundColor Cyan }
function Write-Header { param($Message) Write-Host "`n🚀 $Message" -ForegroundColor Blue }

Write-Header "Gnosis OCR Model Cache Setup"
Write-Host "=================================" -ForegroundColor Blue

if ($All) {
    $CreateBucket = $true
    $UploadCache = $true
    $VerifyCache = $true
}

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

# Check if gsutil is available
try {
    gsutil version | Out-Null
    Write-Status "gsutil is available"
} catch {
    Write-Error "gsutil not found. Please install Google Cloud SDK with gsutil."
    exit 1
}

# Check local cache
if (Test-Path $LocalCachePath) {
    $CacheSize = (Get-ChildItem $LocalCachePath -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1GB
    Write-Status "Local HuggingFace cache found: $([math]::Round($CacheSize, 2)) GB"
    
    # Check for specific model
    $ModelPath = Join-Path $LocalCachePath "hub\models--nanonets--Nanonets-OCR-s"
    if (Test-Path $ModelPath) {
        Write-Status "Nanonets-OCR-s model found in cache"
    } else {
        Write-Warning "Nanonets-OCR-s model not found in cache - you may need to run the service locally first"
    }
} else {
    Write-Error "Local HuggingFace cache not found at: $LocalCachePath"
    Write-Info "Please run the OCR service locally first to download the model cache"
    exit 1
}

# Step 1: Create GCS bucket for models
if ($CreateBucket) {
    Write-Header "Step 1: Creating GCS bucket for model cache..."
    
    try {
        # Check if bucket already exists
        $bucketExists = gsutil ls gs://$ModelBucket 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Status "Bucket gs://$ModelBucket already exists"
        } else {
            Write-Info "Creating bucket gs://$ModelBucket..."
            gsutil mb gs://$ModelBucket
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to create bucket"
            }
            Write-Status "Bucket gs://$ModelBucket created successfully"
        }
        
        # Set appropriate permissions (public read for model cache)
        Write-Info "Setting bucket permissions..."
        gsutil iam ch allUsers:objectViewer gs://$ModelBucket
        Write-Status "Bucket permissions configured"
        
    } catch {
        Write-Error "Failed to create or configure bucket: $_"
        exit 1
    }
}

# Step 2: Upload model cache to GCS
if ($UploadCache) {
    Write-Header "Step 2: Uploading model cache to GCS..."
    
    try {
        Write-Info "This may take several minutes depending on your internet connection..."
        Write-Info "Uploading $([math]::Round($CacheSize, 2)) GB of model data..."
        
        # Upload the entire huggingface cache
        gsutil -m cp -r "$LocalCachePath\*" gs://$ModelBucket/huggingface/
        
        if ($LASTEXITCODE -ne 0) {
            throw "Upload failed"
        }
        
        Write-Status "Model cache uploaded successfully"
        
    } catch {
        Write-Error "Failed to upload model cache: $_"
        exit 1
    }
}

# Step 3: Verify uploaded cache
if ($VerifyCache) {
    Write-Header "Step 3: Verifying uploaded model cache..."
    
    try {
        Write-Info "Checking bucket contents..."
        
        # List bucket contents
        $bucketContents = gsutil ls -r gs://$ModelBucket/huggingface/ 2>$null
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to list bucket contents"
        }
        
        # Check for specific model files
        $modelFiles = gsutil ls gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s/ 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Status "Nanonets-OCR-s model found in bucket"
            
            # Count files
            $fileCount = ($modelFiles | Measure-Object).Count
            Write-Info "Model files in bucket: $fileCount"
        } else {
            Write-Warning "Nanonets-OCR-s model not found in bucket"
        }
        
        # Get bucket size
        $bucketSize = gsutil du -s gs://$ModelBucket/huggingface/ 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Status "Bucket verification completed"
            Write-Info "Bucket size: $bucketSize"
        }
        
    } catch {
        Write-Error "Failed to verify bucket contents: $_"
        exit 1
    }
}

# Display summary
Write-Header "Setup Summary"
Write-Host "Configuration:" -ForegroundColor Gray
Write-Host "  Project ID: $ProjectId" -ForegroundColor Gray
Write-Host "  Model Bucket: gs://$ModelBucket" -ForegroundColor Gray
Write-Host "  Local Cache: $LocalCachePath" -ForegroundColor Gray
Write-Host "  Cache Size: $([math]::Round($CacheSize, 2)) GB" -ForegroundColor Gray

Write-Host "`n🔗 Useful Commands:" -ForegroundColor Blue
Write-Host "  List bucket: gsutil ls -r gs://$ModelBucket/" -ForegroundColor Cyan
Write-Host "  Bucket size: gsutil du -s gs://$ModelBucket/" -ForegroundColor Cyan
Write-Host "  Delete bucket: gsutil rm -r gs://$ModelBucket/" -ForegroundColor Cyan

Write-Host "`n✨ Next Steps:" -ForegroundColor Magenta
Write-Host "  1. Update deployment script to use this model bucket" -ForegroundColor Gray
Write-Host "  2. Deploy OCR service with: .\scripts\deploy.ps1 -UseV2" -ForegroundColor Gray
Write-Host "  3. Test cache mounting in Cloud Run" -ForegroundColor Gray

Write-Host "`n🎊 Model cache setup completed!" -ForegroundColor Green
