# Debug Cache Upload Issue
# Let's see exactly what's in the bucket and fix the path issue

param(
    [string]$ModelBucket = "gnosis-ocr-models"
)

function Write-Status { param($Message) Write-Host "✅ $Message" -ForegroundColor Green }
function Write-Warning { param($Message) Write-Host "⚠️  $Message" -ForegroundColor Yellow }
function Write-Error { param($Message) Write-Host "❌ $Message" -ForegroundColor Red }
function Write-Info { param($Message) Write-Host "ℹ️  $Message" -ForegroundColor Cyan }
function Write-Header { param($Message) Write-Host "`n🚀 $Message" -ForegroundColor Blue }

Write-Header "Debug Cache Upload Paths"

# Let's see exactly what's in the bucket
Write-Info "Listing ALL bucket contents:"
gsutil ls -r gs://$ModelBucket/ | ForEach-Object {
    Write-Host "  $_" -ForegroundColor Gray
}

Write-Header "Checking specific paths..."

# Check the refs/main content to get the correct snapshot ID
Write-Info "Getting snapshot ID from refs/main..."
$snapshotId = gsutil cat gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s/refs/main 2>$null
Write-Info "Snapshot ID: $snapshotId"

# Check if files exist under different paths
$testPaths = @(
    "gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s/snapshots/$snapshotId/config.json",
    "gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s/config.json",
    "gs://$ModelBucket/huggingface/models--nanonets--Nanonets-OCR-s/snapshots/$snapshotId/config.json",
    "gs://$ModelBucket/config.json"
)

Write-Info "Testing different paths for config.json:"
foreach ($path in $testPaths) {
    $result = gsutil ls $path 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Status "✓ FOUND: $path"
    } else {
        Write-Host "  ✗ Not found: $path" -ForegroundColor Gray
    }
}

Write-Header "Let's fix the upload with correct paths..."

# Get the local snapshot directory
$LocalCachePath = "$env:USERPROFILE\.cache\huggingface"
$ModelDir = Get-ChildItem "$LocalCachePath\hub\models--nanonets--Nanonets-OCR-s\snapshots" -Directory | Select-Object -First 1
$SnapshotPath = $ModelDir.FullName
$SnapshotName = $ModelDir.Name

Write-Info "Local snapshot: $SnapshotName"
Write-Info "Local path: $SnapshotPath"

# Upload using the exact structure
Write-Info "Uploading with correct structure..."

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

$successCount = 0
foreach ($file in $CriticalFiles) {
    $localFile = Join-Path $SnapshotPath $file
    if (Test-Path $localFile) {
        Write-Info "Uploading: $file"
        
        # Try the exact path structure
        $remotePath = "gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s/snapshots/$SnapshotName/$file"
        gsutil cp "$localFile" "$remotePath"
        
        if ($LASTEXITCODE -eq 0) {
            Write-Status "✓ $file uploaded"
            $successCount++
            
            # Verify it's actually there
            $verifyResult = gsutil ls "$remotePath" 2>$null
            if ($LASTEXITCODE -eq 0) {
                Write-Status "✓ $file verified in bucket"
            } else {
                Write-Warning "✗ $file upload succeeded but verification failed"
            }
        } else {
            Write-Error "✗ $file upload failed"
        }
    } else {
        Write-Warning "✗ $file not found locally at: $localFile"
    }
}

Write-Header "Final verification..."

Write-Info "Checking bucket structure:"
gsutil ls -r gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s/snapshots/$SnapshotName/ | Head -20

Write-Info "Testing config.json access:"
$configPath = "gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s/snapshots/$SnapshotName/config.json"
$configTest = gsutil cat "$configPath" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Status "✓ config.json is accessible and readable"
    Write-Info "Config preview:"
    $configTest | Select-Object -First 5 | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
} else {
    Write-Error "✗ config.json still not accessible"
}

Write-Host "`n📊 Summary:" -ForegroundColor Blue
Write-Host "  Files uploaded: $successCount/9" -ForegroundColor Gray
Write-Host "  Bucket path: gs://$ModelBucket/huggingface/hub/models--nanonets--Nanonets-OCR-s/snapshots/$SnapshotName/" -ForegroundColor Gray

if ($successCount -eq 9) {
    Write-Host "`n🎉 SUCCESS: All files should now be accessible!" -ForegroundColor Green
    Write-Host "✨ Ready to deploy: .\scripts\deploy.ps1 -UseV2" -ForegroundColor Cyan
} else {
    Write-Host "`n⚠️  Some files may still be missing. Check the bucket listing above." -ForegroundColor Yellow
}
