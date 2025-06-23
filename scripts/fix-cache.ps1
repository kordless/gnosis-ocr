# Gnosis OCR - Targeted Cache Fix Script
# This script handles the specific Windows file access issue and uploads critical files

param(
    [string]$ProjectId = "gnosis-459403",
    [string]$ModelBucket = "gnosis-ocr-models",
    [string]$LocalCachePath = "$env:USERPROFILE\.cache\huggingface"
)

# Colors for output
function Write-Status { param($Message) Write-Host "✅ $Message" -ForegroundColor Green }
function Write-Warning { param($Message) Write-Host "⚠️  $Message" -ForegroundColor Yellow }
function Write-Error { param($Message) Write-Host "❌ $Message" -ForegroundColor Red }
function Write-Info { param($Message) Write-Host "ℹ️  $Message" -ForegroundColor Cyan }
function Write-Header { param($Message) Write-Host "`n🚀 $Message" -ForegroundColor Blue }

Write-Header "Gnosis OCR Targeted Cache Fix"
Write-Host "=================================" -ForegroundColor Blue

# The critical files we need for the model to work
$CriticalFiles = @(
    "config.json",
    "tokenizer.json", 
    "tokenizer_config.json",
    "preprocessor_config.json",
    "generation_config.json",
    "added_tokens.json",
    "merges.txt",
    "chat_template.jinja",
    "vocab.json"
)

# Find the model snapshot directory
$ModelDir = Get-ChildItem "$LocalCachePath\hub\models--nanonets--Nanonets-OCR-s\snapshots" -Directory | Select-Object -First 1
if (-not $ModelDir) {
    Write-Error "Cannot find model snapshot directory"
    exit 1
}

$SnapshotPath = $ModelDir.FullName
$SnapshotName = $ModelDir.Name
Write-Info "Found model snapshot: $SnapshotName"

Write-Header "Step 1: Fixing Windows file access issues..."

try {
    # Take ownership of the cache directory to fix access issues
    Write-Info "Taking ownership of cache directory..."
    takeown /f "$LocalCachePath" /r /d y 2>$null | Out-Null
    
    # Reset permissions
    Write-Info "Resetting file permissions..."
    icacls "$LocalCachePath" /reset /t /q 2>$null | Out-Null
    icacls "$LocalCachePath" /grant "$env:USERNAME:(OI)(CI)F" /t /q 2>$null | Out-Null
    
    Write-Status "File permissions fixed"
    
} catch {
    Write-Warning "Could not fix permissions automatically: $_"
    Write-Info "Continuing with upload attempt..."
}

Write-Header "Step 2: Uploading critical model files individually..."

$SuccessCount = 0
$FailCount = 0

foreach ($file in $CriticalFiles) {
    $localFile = Join-Path $SnapshotPath $file
    $remotePath = "gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s/snapshots/$SnapshotName/$file"
    
    if (Test-Path $localFile) {
        Write-Info "Uploading: $file"
        try {
            gsutil cp "$localFile" "$remotePath" 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Status "✓ $file"
                $SuccessCount++
            } else {
                Write-Error "✗ $file - Upload failed"
                $FailCount++
            }
        } catch {
            Write-Error "✗ $file - Exception: $_"
            $FailCount++
        }
    } else {
        Write-Warning "✗ $file - Not found locally"
        $FailCount++
    }
}

Write-Header "Step 3: Uploading remaining snapshot files..."

try {
    # Upload the entire snapshot directory with error handling
    Write-Info "Uploading snapshot directory (this may take a few minutes)..."
    
    # Use robocopy-like behavior: upload what we can, continue on errors
    $env:GSUTIL_PARALLEL_THREAD_COUNT = "10"
    gsutil -m cp -r "$SnapshotPath" "gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s/snapshots/" 2>$null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Status "Snapshot directory uploaded successfully"
    } else {
        Write-Warning "Some files in snapshot may have failed, but continuing..."
    }
    
} catch {
    Write-Warning "Snapshot upload had issues: $_"
}

Write-Header "Step 4: Verify essential files are now present..."

$VerificationResults = @()
foreach ($file in $CriticalFiles) {
    $remotePath = "gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s/snapshots/$SnapshotName/$file"
    $result = gsutil ls "$remotePath" 2>$null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Status "✓ $file - Present in bucket"
        $VerificationResults += @{ File = $file; Status = "OK" }
    } else {
        Write-Error "✗ $file - Missing from bucket"
        $VerificationResults += @{ File = $file; Status = "MISSING" }
    }
}

Write-Header "Step 5: Test model accessibility..."

try {
    # Check refs/main file
    $refsResult = gsutil cat "gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s/refs/main" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Status "refs/main accessible: $refsResult"
    } else {
        Write-Error "refs/main not accessible"
    }
    
    # Count total files in bucket
    $fileCount = (gsutil ls -r "gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s/**" 2>$null | Measure-Object).Count
    Write-Info "Total files in bucket: $fileCount"
    
    # Get bucket size
    $bucketSize = gsutil du -s "gs://$ModelBucket/huggingface/" 2>$null
    Write-Info "Bucket size: $bucketSize"
    
} catch {
    Write-Warning "Could not verify model accessibility: $_"
}

# Summary
Write-Header "Fix Summary"

$OkCount = ($VerificationResults | Where-Object { $_.Status -eq "OK" }).Count
$MissingCount = ($VerificationResults | Where-Object { $_.Status -eq "MISSING" }).Count

Write-Host "Critical Files Status:" -ForegroundColor Gray
Write-Host "  ✅ Present: $OkCount/$($CriticalFiles.Count)" -ForegroundColor Green
Write-Host "  ❌ Missing: $MissingCount/$($CriticalFiles.Count)" -ForegroundColor Red

if ($MissingCount -eq 0) {
    Write-Host "`n🎉 SUCCESS: All critical files are now in the bucket!" -ForegroundColor Green
    Write-Host "✨ Ready to deploy: .\scripts\deploy.ps1 -UseV2" -ForegroundColor Cyan
} elseif ($MissingCount -le 2) {
    Write-Host "`n⚠️  MOSTLY GOOD: Only $MissingCount files missing" -ForegroundColor Yellow
    Write-Host "✨ Try deploying anyway: .\scripts\deploy.ps1 -UseV2" -ForegroundColor Cyan
    Write-Host "   Model loading will show if anything critical is missing" -ForegroundColor Gray
} else {
    Write-Host "`n❌ ISSUES: $MissingCount critical files missing" -ForegroundColor Red
    Write-Host "🔧 Try manual upload of missing files or re-run this script" -ForegroundColor Yellow
}

Write-Host "`n🔍 Debug Commands:" -ForegroundColor Blue
Write-Host "  Check bucket: gsutil ls -r gs://$ModelBucket/huggingface/hub/" -ForegroundColor Cyan
Write-Host "  Test config: gsutil cat gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s/snapshots/$SnapshotName/config.json" -ForegroundColor Cyan

Write-Host "`n🎊 Targeted fix completed!" -ForegroundColor Green
