# Gnosis OCR - Model Cache Recovery Script
# This script handles failed uploads and verifies cache integrity

param(
    [string]$ProjectId = "gnosis-459403",
    [string]$ModelBucket = "gnosis-ocr-models",
    [string]$LocalCachePath = "$env:USERPROFILE\.cache\huggingface",
    [switch]$ResumeFailed = $false,
    [switch]$VerifyIntegrity = $false,
    [switch]$ShowDiff = $false,
    [switch]$All = $false
)

# Colors for output
function Write-Status { param($Message) Write-Host "✅ $Message" -ForegroundColor Green }
function Write-Warning { param($Message) Write-Host "⚠️  $Message" -ForegroundColor Yellow }
function Write-Error { param($Message) Write-Host "❌ $Message" -ForegroundColor Red }
function Write-Info { param($Message) Write-Host "ℹ️  $Message" -ForegroundColor Cyan }
function Write-Header { param($Message) Write-Host "`n🚀 $Message" -ForegroundColor Blue }

Write-Header "Gnosis OCR Model Cache Recovery"
Write-Host "===================================" -ForegroundColor Blue

if ($All) {
    $ResumeFailed = $true
    $VerifyIntegrity = $true
    $ShowDiff = $true
}

# Step 1: Resume failed upload
if ($ResumeFailed) {
    Write-Header "Step 1: Resuming failed upload..."
    
    try {
        Write-Info "Using rsync-like behavior to only upload missing/changed files..."
        
        # Use gsutil rsync to resume upload (only uploads missing files)
        gsutil -m rsync -r -d "$LocalCachePath" gs://$ModelBucket/huggingface/
        
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Some files may have failed to upload, but continuing..."
        } else {
            Write-Status "Upload resume completed successfully"
        }
        
    } catch {
        Write-Error "Failed to resume upload: $_"
    }
}

# Step 2: Show differences between local and remote
if ($ShowDiff) {
    Write-Header "Step 2: Comparing local and remote cache..."
    
    try {
        Write-Info "Checking for missing files in bucket..."
        
        # Get local file list
        Write-Info "Scanning local cache directory..."
        $localFiles = @()
        if (Test-Path $LocalCachePath) {
            Get-ChildItem $LocalCachePath -Recurse -File | ForEach-Object {
                $relativePath = $_.FullName.Replace($LocalCachePath, "").Replace("\", "/").TrimStart("/")
                $localFiles += $relativePath
            }
        }
        
        Write-Info "Found $($localFiles.Count) local files"
        
        # Get remote file list
        Write-Info "Scanning remote bucket..."
        $remoteOutput = gsutil ls -r gs://$ModelBucket/huggingface/** 2>$null
        $remoteFiles = @()
        if ($LASTEXITCODE -eq 0) {
            $remoteFiles = $remoteOutput | ForEach-Object {
                if ($_ -match "gs://$ModelBucket/huggingface/(.+)$") {
                    $matches[1]
                }
            } | Where-Object { $_ -and $_ -notmatch "/$" }  # Exclude directories
        }
        
        Write-Info "Found $($remoteFiles.Count) remote files"
        
        # Find missing files
        $missingFiles = $localFiles | Where-Object { $_ -notin $remoteFiles }
        
        if ($missingFiles.Count -gt 0) {
            Write-Warning "Found $($missingFiles.Count) missing files in bucket:"
            $missingFiles | Select-Object -First 5 | ForEach-Object {
                Write-Host "  - $_" -ForegroundColor Yellow
            }
            if ($missingFiles.Count -gt 5) {
                Write-Host "  ... and $($missingFiles.Count - 5) more" -ForegroundColor Yellow
            }
        } else {
            Write-Status "All local files are present in bucket"
        }
        
    } catch {
        Write-Warning "Could not compare files: $_"
    }
}

# Step 3: Verify critical model files
if ($VerifyIntegrity) {
    Write-Header "Step 3: Verifying critical model files..."
    
    $criticalFiles = @(
        "hub/models--nanonets--Nanonets-OCR-s/refs/main",
        "hub/models--nanonets--Nanonets-OCR-s/snapshots"
    )
    
    foreach ($file in $criticalFiles) {
        Write-Info "Checking: $file"
        $result = gsutil ls gs://$ModelBucket/huggingface/$file* 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Status "$file - Found"
        } else {
            Write-Error "$file - Missing!"
            
            # Try to upload this specific file/directory
            $localPath = Join-Path $LocalCachePath $file
            if (Test-Path $localPath) {
                Write-Info "Attempting to upload missing file: $file"
                gsutil -m cp -r "$localPath" gs://$ModelBucket/huggingface/$file
                if ($LASTEXITCODE -eq 0) {
                    Write-Status "Successfully uploaded: $file"
                } else {
                    Write-Error "Failed to upload: $file"
                }
            }
        }
    }
    
    # Check for model config and tokenizer files
    Write-Info "Checking for essential model files..."
    $essentialPatterns = @(
        "*/config.json",
        "*/tokenizer.json", 
        "*/tokenizer_config.json",
        "*/preprocessor_config.json",
        "*/pytorch_model*.bin",
        "*/model*.safetensors"
    )
    
    foreach ($pattern in $essentialPatterns) {
        $result = gsutil ls gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s/**/$pattern 2>$null
        if ($LASTEXITCODE -eq 0) {
            $fileCount = ($result | Measure-Object).Count
            Write-Status "$pattern - Found $fileCount files"
        } else {
            Write-Warning "$pattern - Not found"
        }
    }
}

# Step 4: Test model loading capability
Write-Header "Step 4: Testing model accessibility..."

try {
    # Check if we can access the model files from the bucket
    $modelPath = "gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s"
    $result = gsutil ls $modelPath 2>$null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Status "Model directory accessible in bucket"
        
        # Get total size
        $sizeResult = gsutil du -s gs://$ModelBucket/huggingface/ 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Info "Total bucket size: $sizeResult"
        }
        
    } else {
        Write-Error "Cannot access model directory in bucket"
    }
    
} catch {
    Write-Warning "Could not test model accessibility: $_"
}

# Summary and recommendations
Write-Header "Recovery Summary"

Write-Host "`n🔍 Quick Diagnostics:" -ForegroundColor Blue
Write-Host "  Check bucket contents: gsutil ls -r gs://$ModelBucket/huggingface/hub/" -ForegroundColor Cyan
Write-Host "  Check bucket size: gsutil du -s gs://$ModelBucket/" -ForegroundColor Cyan
Write-Host "  Test file access: gsutil ls gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s/" -ForegroundColor Cyan

Write-Host "`n🛠️ If issues persist:" -ForegroundColor Magenta
Write-Host "  1. Try individual file upload: gsutil cp [local-file] gs://$ModelBucket/huggingface/[path]" -ForegroundColor Gray
Write-Host "  2. Use parallel uploads: gsutil -m cp -r [directory] gs://$ModelBucket/huggingface/" -ForegroundColor Gray
Write-Host "  3. Check network stability and retry" -ForegroundColor Gray

Write-Host "`n✨ Next Steps:" -ForegroundColor Green
Write-Host "  1. If cache looks good, proceed with deployment: .\scripts\deploy.ps1 -UseV2" -ForegroundColor Gray
Write-Host "  2. Test the deployed service health endpoint" -ForegroundColor Gray
Write-Host "  3. Monitor logs during first model loading" -ForegroundColor Gray

Write-Host "`n🎊 Cache recovery completed!" -ForegroundColor Green
