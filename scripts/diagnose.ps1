# Gnosis OCR Cloud Run Diagnostics
# Quick checks for common deployment issues

param(
    [string]$ServiceName = "gnosis-ocr",
    [string]$Region = "us-central1"
)

function Write-Status { param($Message) Write-Host "✅ $Message" -ForegroundColor Green }
function Write-Warning { param($Message) Write-Host "⚠️  $Message" -ForegroundColor Yellow }
function Write-Error { param($Message) Write-Host "❌ $Message" -ForegroundColor Red }
function Write-Info { param($Message) Write-Host "ℹ️  $Message" -ForegroundColor Cyan }
function Write-Header { param($Message) Write-Host "`n🚀 $Message" -ForegroundColor Blue }

Write-Header "Cloud Run Diagnostics for Gnosis OCR"

Write-Header "Step 1: Check service status..."
try {
    $serviceInfo = gcloud run services describe $ServiceName --region=$Region --format=json | ConvertFrom-Json
    
    Write-Info "Service Details:"
    Write-Host "  Status: $($serviceInfo.status.conditions[0].status)" -ForegroundColor Gray
    Write-Host "  Reason: $($serviceInfo.status.conditions[0].reason)" -ForegroundColor Gray
    Write-Host "  Message: $($serviceInfo.status.conditions[0].message)" -ForegroundColor Gray
    Write-Host "  URL: $($serviceInfo.status.url)" -ForegroundColor Gray
    
    # Check revisions
    $latestRevision = $serviceInfo.status.latestReadyRevisionName
    Write-Info "Latest revision: $latestRevision"
    
} catch {
    Write-Error "Could not get service info: $_"
}

Write-Header "Step 2: Check recent logs..."
try {
    Write-Info "Recent logs (last 50 lines):"
    gcloud logs tail "run.googleapis.com/stderr" --filter="resource.labels.service_name=$ServiceName AND resource.labels.location=$Region" --limit=50
} catch {
    Write-Error "Could not get logs: $_"
}

Write-Header "Step 3: Check volume mounts..."
try {
    Write-Info "Checking if volumes are properly configured..."
    $volumeInfo = gcloud run services describe $ServiceName --region=$Region --format="value(spec.template.spec.volumes[].name)"
    if ($volumeInfo) {
        Write-Status "Volumes configured: $volumeInfo"
    } else {
        Write-Warning "No volumes found - GCS mount may not be working"
    }
    
    $mountInfo = gcloud run services describe $ServiceName --region=$Region --format="value(spec.template.spec.containers[].volumeMounts[].mountPath)"
    if ($mountInfo) {
        Write-Status "Mount paths: $mountInfo"
    } else {
        Write-Warning "No volume mounts found"
    }
} catch {
    Write-Warning "Could not check volume configuration"
}

Write-Header "Step 4: Check environment variables..."
try {
    Write-Info "Environment variables:"
    $envVars = gcloud run services describe $ServiceName --region=$Region --format="value(spec.template.spec.containers[].env[].name,spec.template.spec.containers[].env[].value)"
    $envVars | ForEach-Object {
        if ($_ -match "CACHE|MODEL|STORAGE") {
            Write-Host "  $_" -ForegroundColor Cyan
        }
    }
} catch {
    Write-Warning "Could not check environment variables"
}

Write-Header "Step 5: Test endpoints..."
try {
    $serviceUrl = gcloud run services describe $ServiceName --region=$Region --format="value(status.url)"
    
    if ($serviceUrl) {
        Write-Info "Testing health endpoint: $serviceUrl/health"
        try {
            $healthResponse = Invoke-RestMethod -Uri "$serviceUrl/health" -TimeoutSec 10
            Write-Status "Health check successful!"
            Write-Host "  Status: $($healthResponse.status)" -ForegroundColor Green
            Write-Host "  GPU Available: $($healthResponse.gpu_available)" -ForegroundColor Green
            Write-Host "  Model Loaded: $($healthResponse.model_loaded)" -ForegroundColor Green
        } catch {
            Write-Error "Health check failed: $_"
            Write-Info "This is likely why the service is failing"
        }
        
        Write-Info "Testing cache info endpoint: $serviceUrl/cache/info"
        try {
            $cacheResponse = Invoke-RestMethod -Uri "$serviceUrl/cache/info" -TimeoutSec 10
            Write-Status "Cache info successful!"
            Write-Host "  Cache Path: $($cacheResponse.cache_info.path)" -ForegroundColor Green
            Write-Host "  Cache Exists: $($cacheResponse.cache_info.exists)" -ForegroundColor Green
            Write-Host "  Cache Size: $($cacheResponse.cache_info.size_gb) GB" -ForegroundColor Green
        } catch {
            Write-Error "Cache info failed: $_"
            Write-Info "Cache mount may not be working properly"
        }
    }
} catch {
    Write-Warning "Could not test endpoints"
}

Write-Header "Diagnostics completed"

Write-Host "`n🔧 Common fixes:" -ForegroundColor Blue
Write-Host "  1. Check logs for specific error messages" -ForegroundColor Gray
Write-Host "  2. Verify /cache mount has model files" -ForegroundColor Gray
Write-Host "  3. Check if bucket permissions are correct" -ForegroundColor Gray
Write-Host "  4. Try deploying with more memory (16Gi)" -ForegroundColor Gray
Write-Host "  5. Check if main_v2.py imports are working" -ForegroundColor Gray

Write-Host "`n📋 Next steps:" -ForegroundColor Magenta
Write-Host "  - Fix any issues found above" -ForegroundColor Gray
Write-Host "  - Redeploy: .\scripts\deploy.ps1 -UseV2 -SkipBuild -SkipPush" -ForegroundColor Gray
Write-Host "  - Monitor logs: gcloud run services logs tail $ServiceName --region=$Region --follow" -ForegroundColor Gray
