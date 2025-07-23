# Gnosis OCR Deployment Script
# Builds and deploys the OCR service for local (Docker Compose) or Cloud Run.

param(
    [string]$Target = "local",  # local, cloudrun
    [string]$Tag = "latest",
    [switch]$Rebuild = $false,
    [switch]$Help = $false
)

if ($PSBoundParameters.Count -eq 0 -or $Help) {
    Write-Host "Gnosis OCR Deployment Script" -ForegroundColor Cyan
    Write-Host "USAGE: .\deploy.ps1 [-Target <local|cloudrun>] [-Tag <tag>] [-Rebuild]" -ForegroundColor White
    exit 0
}

$ErrorActionPreference = "Stop"

# --- Project Configuration ---
$projectRoot = $PSScriptRoot
$imageName = "gnosis-ocr"
$fullImageName = "${imageName}:${Tag}"
$dockerfile = "Dockerfile.unified"
$composeFile = "docker-compose.yml"

Write-Host "=== Gnosis OCR Deployment ===" -ForegroundColor Cyan
Write-Host "Target: $Target, Image: $fullImageName" -ForegroundColor White

# --- Validate Configuration ---
$dockerfilePath = Join-Path $projectRoot $dockerfile
if (-not (Test-Path $dockerfilePath)) { Write-Error "Dockerfile not found: $dockerfilePath" }

# --- Load Cloud Run Environment ---
$envConfig = @{}
if ($Target -eq "cloudrun") {
    $envFile = Join-Path $projectRoot ".env.cloudrun"
    if (Test-Path $envFile) {
        Get-Content $envFile | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
            $key, $value = $_ -split '=', 2
            $envConfig[$key.Trim()] = $value.Trim()
        }
    } else {
        Write-Error ".env.cloudrun not found. Please create it from .env.example."
    }
}

# --- Build Docker Image ---
Write-Host "`n=== Building Docker Image ===" -ForegroundColor Green
$buildArgs = @("build", "-f", $dockerfile, "-t", $fullImageName, ".")
if ($Rebuild) { $buildArgs += "--no-cache" }

Write-Host "Running: docker $($buildArgs -join ' ')" -ForegroundColor Gray
& docker @buildArgs
if ($LASTEXITCODE -ne 0) { Write-Error "Docker build failed." }
Write-Host "✓ Build completed successfully" -ForegroundColor Green

# --- Deployment ---
Write-Host "`n=== Deploying to $Target ===" -ForegroundColor Green

switch ($Target) {
    "local" {
        Write-Host "Deploying locally with Docker Compose..." -ForegroundColor White
        Push-Location $projectRoot
        try {
            & docker-compose down
            & docker-compose up -d --build
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✓ Service started successfully. Available at http://localhost:7799" -ForegroundColor Cyan
            } else {
                Write-Error "Failed to start services with docker-compose."
            }
        } finally {
            Pop-Location
        }
    }
    "cloudrun" {
        Write-Host "Deploying to Google Cloud Run..." -ForegroundColor White
        $projectId = $envConfig["PROJECT_ID"]
        $serviceAccount = $envConfig["GCP_SERVICE_ACCOUNT"]
        $modelBucket = $envConfig["MODEL_BUCKET_NAME"]

        if (-not $projectId -or -not $serviceAccount -or -not $modelBucket) {
            Write-Error "PROJECT_ID, GCP_SERVICE_ACCOUNT, or MODEL_BUCKET_NAME missing in .env.cloudrun"
        }

        $gcrImage = "gcr.io/$projectId/${imageName}:${Tag}"

        # Tag and Push Image
        Write-Host "Tagging image as $gcrImage" -ForegroundColor Gray
        & docker tag $fullImageName $gcrImage
        & gcloud auth configure-docker --quiet
        Write-Host "Pushing image to GCR..." -ForegroundColor Gray
        & docker push $gcrImage
        if ($LASTEXITCODE -ne 0) { Write-Error "Failed to push image to GCR." }
        Write-Host "✓ Image pushed successfully." -ForegroundColor Green

        # Deploy to Cloud Run
        Write-Host "Deploying service 'gnosis-ocr' to Cloud Run..." -ForegroundColor White
        $envVars = ($envConfig.GetEnumerator() | Where-Object { $_.Key -ne "PROJECT_ID" } | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ","

        $deployArgs = @(
            "run", "deploy", "gnosis-ocr",
            "--image", $gcrImage,
            "--region", "us-central1",
            "--platform", "managed",
            "--allow-unauthenticated",
            "--min-instances", "0",
            "--max-instances", "3",
            "--concurrency", "8",
            "--service-account", $serviceAccount,
            "--add-volume", "name=model-cache,type=cloud-storage,bucket=$modelBucket",
            "--add-volume-mount", "volume=model-cache,mount-path=/app/cache",
            "--set-env-vars", $envVars,
            "--port", "8080",
            "--execution-environment", "gen2"
        )

        & gcloud @deployArgs
        if ($LASTEXITCODE -eq 0) {
            $serviceUrl = & gcloud run services describe gnosis-ocr --region=us-central1 --format="value(status.url)"
            Write-Host "✓ CLOUD RUN DEPLOYMENT SUCCESSFUL!" -ForegroundColor Green
            Write-Host "🔗 Service URL: $serviceUrl" -ForegroundColor Cyan
        } else {
            Write-Error "Cloud Run deployment failed."
        }
    }
}

Write-Host "`n=== Deployment Complete ===" -ForegroundColor Green