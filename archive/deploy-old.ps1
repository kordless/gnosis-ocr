# Gnosis OCR Deployment Script
# Builds and deploys the OCR service with proper configuration

param(
    [string]$Target = "local",  # local, cloudrun
    [string]$Tag = "latest",
    [switch]$Rebuild = $false,

    [switch]$WhatIf = $false,
    [switch]$Verbose = $false,
    [switch]$UseDockerRun = $false,  # Use docker run instead of docker-compose for local deployment
    [switch]$Help = $false
)

# Show help if no parameters provided or Help switch is used
if ($PSBoundParameters.Count -eq 0 -or $Help) {
    Write-Host "=== Gnosis OCR Deployment Script ===" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "USAGE:" -ForegroundColor White
    Write-Host "  .\deploy.ps1 [OPTIONS]" -ForegroundColor Gray
    Write-Host ""
    Write-Host "OPTIONS:" -ForegroundColor White
    Write-Host "  -Target <target>        Deployment target (local, cloudrun)" -ForegroundColor Gray
    Write-Host "                         Default: local" -ForegroundColor DarkGray
    Write-Host "  -Tag <tag>             Image tag to build/deploy" -ForegroundColor Gray
    Write-Host "                         Default: latest" -ForegroundColor DarkGray
    Write-Host "  -Rebuild               Force rebuild from scratch (--no-cache)" -ForegroundColor Gray

    Write-Host "  -WhatIf                Show what would be done without executing" -ForegroundColor Gray
    Write-Host "  -Verbose               Enable verbose output" -ForegroundColor Gray
    Write-Host "  -UseDockerRun          Use docker run instead of docker-compose for local" -ForegroundColor Gray
    Write-Host "  -Help                  Show this help message" -ForegroundColor Gray
    Write-Host ""
    Write-Host "EXAMPLES:" -ForegroundColor White
    Write-Host "  .\deploy.ps1 -Target local -UseDockerRun     # Deploy locally with docker run" -ForegroundColor Gray
    Write-Host "  .\deploy.ps1 -Target cloudrun -Rebuild      # Deploy to Cloud Run with rebuild" -ForegroundColor Gray

    Write-Host ""
    Write-Host "TARGETS:" -ForegroundColor White
    Write-Host "  local      - Build and run locally (docker-compose or docker run)" -ForegroundColor Gray
    Write-Host "  cloudrun   - Build, push, and deploy to Cloud Run with GPU" -ForegroundColor Gray
    Write-Host ""
    Write-Host "REQUIREMENTS:" -ForegroundColor White
    Write-Host "  - Docker installed and running" -ForegroundColor Gray
    Write-Host "  - For cloud targets: gcloud CLI configured" -ForegroundColor Gray
    Write-Host "  - For Cloud Run: .env.cloudrun file with PROJECT_ID" -ForegroundColor Gray
    Write-Host ""
    exit 0
}

$ErrorActionPreference = "Stop"

# Determine project root - check if we're in scripts directory
$currentDir = $PSScriptRoot
if ((Split-Path -Leaf $currentDir) -eq "scripts") {
    $projectRoot = Split-Path -Parent $currentDir
} else {
    $projectRoot = $currentDir
}


Write-Host "=== Gnosis OCR Deployment ===" -ForegroundColor Cyan
Write-Host "Target: $Target" -ForegroundColor White
Write-Host "Tag: $Tag" -ForegroundColor White
if ($Target -eq "local") {
    Write-Host "Deployment Method: $(if ($UseDockerRun) { 'Docker Run' } else { 'Docker Compose' })" -ForegroundColor White
}
Write-Host "Project Root: $projectRoot" -ForegroundColor Gray


# Validate target
$validTargets = @("local", "cloudrun")
if ($Target -notin $validTargets) {
    Write-Error "Invalid target '$Target'. Must be one of: $($validTargets -join ', ')"
}

# Load environment configuration if deploying to cloud
$envConfig = @{}
if ($Target -in @("cloudrun")) {
    $envFile = Join-Path $projectRoot ".env.cloudrun"
    if (Test-Path $envFile) {
        Write-Host "Loading environment from .env.cloudrun..." -ForegroundColor Gray
        Get-Content $envFile | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
            $key, $value = $_ -split '=', 2
            # Remove inline comments (everything after # that's not in quotes)
            if ($value -match '^([^#]*)(\s*#.*)?$') {
                $value = $matches[1]
            }
            # Remove surrounding quotes if present
            $value = $value.Trim()
            if ($value.StartsWith('"') -and $value.EndsWith('"')) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            $envConfig[$key.Trim()] = $value
        }
        $projectId = $envConfig["PROJECT_ID"]
    } else {
        Write-Warning ".env.cloudrun not found. Copy .env.sample to .env.cloudrun and update PROJECT_ID"
        $projectId = $null
    }
}


# Set dockerfile and image name based on target
switch ($Target) {
    "local" {
        $dockerfile = "Dockerfile"
        $imageName = "gnosis-ocr-s"
        $composeFile = "docker-compose.yml"
    }
    "cloudrun" {
        # Check if Dockerfile.cloudrun exists, otherwise use standard Dockerfile
        $cloudrunDockerfile = Join-Path $projectRoot "Dockerfile.cloudrun"
        if (Test-Path $cloudrunDockerfile) {
            $dockerfile = "Dockerfile.cloudrun"
        } else {
            $dockerfile = "Dockerfile"
            Write-Host "Note: Using standard Dockerfile for Cloud Run (Dockerfile.cloudrun not found)" -ForegroundColor Yellow
        }
        $imageName = "gnosis-ocr-s"
        $composeFile = $null
    }
}


$fullImageName = "${imageName}:${Tag}"


Write-Host "`n=== Build Configuration ===" -ForegroundColor Yellow
Write-Host "Dockerfile: $dockerfile" -ForegroundColor White
Write-Host "Image Name: $fullImageName" -ForegroundColor White
Write-Host "Compose File: $($composeFile ?? 'None')" -ForegroundColor White

# Check if dockerfile exists
$dockerfilePath = Join-Path $projectRoot $dockerfile
if (-not (Test-Path $dockerfilePath)) {
    Write-Error "Dockerfile not found: $dockerfilePath"
}

# Build the image
Write-Host "`n=== Building Docker Image ===" -ForegroundColor Green

# Create logs directory if it doesn't exist
$logsDir = Join-Path $projectRoot "build-logs"
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}

# Generate timestamp for log file
$timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$logFile = Join-Path $logsDir "build_${Target}_${timestamp}.log"

Write-Host "Build log will be written to: $logFile" -ForegroundColor Gray

$buildArgs = @(
    "build"
    "-f", $dockerfile
    "-t", $fullImageName
    "."
)

if ($Rebuild) {
    $buildArgs += "--no-cache"
    Write-Host "Rebuilding from scratch (--no-cache)" -ForegroundColor Yellow
}

# Always use plain progress for better logging
$buildArgs += "--progress=plain"

Write-Host "Running: docker $($buildArgs -join ' ')" -ForegroundColor Gray

if (-not $WhatIf) {
    Push-Location $projectRoot
    try {
        # Start log file with build info
        @"
Gnosis OCR Build Log
====================
Date: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Target: $Target
Tag: $Tag
Dockerfile: $dockerfile
Image: $fullImageName
Command: docker $($buildArgs -join ' ')
====================

"@ | Out-File -FilePath $logFile -Encoding UTF8

        # Run docker build and save output to both console and file
        # Start transcript to capture everything
        Start-Transcript -Path $logFile -Append
        
        # Run docker build normally (output shows in console)
        & docker @buildArgs
        $exitCode = $LASTEXITCODE
        
        # Stop transcript
        Stop-Transcript
        
        if ($exitCode -ne 0) {
            $errorMsg = "Docker build failed with exit code $exitCode"
            Add-Content -Path $logFile -Value "`n`nERROR: $errorMsg"
            Write-Error $errorMsg
        } else {
            Add-Content -Path $logFile -Value "`n`nBUILD COMPLETED SUCCESSFULLY"
            Write-Host "✓ Build completed successfully" -ForegroundColor Green
            Write-Host "✓ Build log saved to: $logFile" -ForegroundColor Green
        }
    }
    finally {
        Pop-Location
    }
} else {
    Write-Host "[WOULD RUN] docker $($buildArgs -join ' ')" -ForegroundColor Magenta
    Write-Host "[WOULD WRITE LOG TO] $logFile" -ForegroundColor Magenta
}


# Deploy based on target
Write-Host "`n=== Deployment ===" -ForegroundColor Green

switch ($Target) {
    "local" {
        if ($UseDockerRun) {
            Write-Host "Deploying locally with Docker Run..." -ForegroundColor White
            
            # Stop and remove existing container if it exists
            Write-Host "Checking for existing container..." -ForegroundColor Gray
            $existingContainer = docker ps -aq -f name=gnosis-ocr-local
            if ($existingContainer) {
                Write-Host "Stopping existing container..." -ForegroundColor Yellow
                docker stop gnosis-ocr-local 2>$null
                docker rm gnosis-ocr-local 2>$null
            }
            
            Write-Host "Running container with GPU support..." -ForegroundColor White
            $runArgs = @(
                "run", "-d"
                "--name", "gnosis-ocr-local"
                "-p", "7799:7799"
                "--gpus", "all"
                "-e", "CUDA_VISIBLE_DEVICES=0"
                "-e", "LOG_LEVEL=INFO"
                "--restart", "unless-stopped"
                $fullImageName
            )
            
            Write-Host "Running: docker $($runArgs -join ' ')" -ForegroundColor Gray
            
            if (-not $WhatIf) {
                & docker @runArgs
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "✓ Container started successfully" -ForegroundColor Green
                    Write-Host "✓ Service available at: http://localhost:7799" -ForegroundColor Cyan
                    Write-Host ""
                    Write-Host "Useful commands:" -ForegroundColor Yellow
                    Write-Host "  Check logs:    docker logs -f gnosis-ocr-local" -ForegroundColor Gray
                    Write-Host "  Check GPU:     docker exec gnosis-ocr-local nvidia-smi" -ForegroundColor Gray
                    Write-Host "  Enter shell:   docker exec -it gnosis-ocr-local /bin/bash" -ForegroundColor Gray
                    Write-Host "  Stop service:  docker stop gnosis-ocr-local" -ForegroundColor Gray
                    Write-Host ""
                    Write-Host "Waiting for service to start..." -ForegroundColor White
                    Start-Sleep -Seconds 5
                    
                    # Check if service is healthy
                    try {
                        $response = Invoke-WebRequest -Uri "http://localhost:7799/health" -UseBasicParsing -TimeoutSec 5
                        if ($response.StatusCode -eq 200) {
                            Write-Host "✓ Health check passed!" -ForegroundColor Green
                        }
                    } catch {
                        Write-Host "⚠ Health check failed - service may still be starting" -ForegroundColor Yellow
                        Write-Host "  Check logs: docker logs gnosis-ocr-local" -ForegroundColor Gray
                    }
                } else {
                    Write-Error "Failed to start container"
                }
            } else {
                Write-Host "[WOULD RUN] docker $($runArgs -join ' ')" -ForegroundColor Magenta
            }
        } else {
            Write-Host "Deploying locally with Docker Compose..." -ForegroundColor White
            
            # Check if docker-compose.yml exists
            $composeFilePath = Join-Path $projectRoot "docker-compose.yml"
            if (-not (Test-Path $composeFilePath)) {
                Write-Error "docker-compose.yml not found at: $composeFilePath"
            }
            
            # Stop existing services
            Write-Host "Stopping existing services..." -ForegroundColor Gray
            if (-not $WhatIf) {
                Push-Location $projectRoot
                try {
                    & docker-compose down
                    Write-Host "✓ Services stopped" -ForegroundColor Green
                } catch {
                    Write-Host "No existing services to stop" -ForegroundColor Gray
                }
            } else {
                Write-Host "[WOULD RUN] docker-compose down" -ForegroundColor Magenta
            }
            
            # Update image tag in docker-compose.yml if needed
            if ($Tag -ne "latest") {
                Write-Host "Updating docker-compose.yml to use tag: $Tag" -ForegroundColor White
                $composeContent = Get-Content $composeFilePath -Raw
                $composeContent = $composeContent -replace "image: gnosis-ocr:latest", "image: gnosis-ocr:$Tag"
                if (-not $WhatIf) {
                    Set-Content -Path $composeFilePath -Value $composeContent -NoNewline
                    Write-Host "✓ Updated docker-compose.yml" -ForegroundColor Green
                } else {
                    Write-Host "[WOULD UPDATE] docker-compose.yml with tag: $Tag" -ForegroundColor Magenta
                }
            }
            
            # Start services with docker-compose
            Write-Host "Starting services with Docker Compose..." -ForegroundColor White
            Write-Host "Using compose file: $composeFilePath" -ForegroundColor Gray
            
            if (-not $WhatIf) {
                Push-Location $projectRoot
                try {
                    & docker-compose up -d
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "✓ Services started successfully" -ForegroundColor Green
                        Write-Host "✓ Service available at: http://localhost:7799" -ForegroundColor Cyan
                        Write-Host ""
                        Write-Host "Useful commands:" -ForegroundColor Yellow
                        Write-Host "  Check logs:    docker-compose logs -f" -ForegroundColor Gray
                        Write-Host "  Check status:  docker-compose ps" -ForegroundColor Gray
                        Write-Host "  Check GPU:     docker-compose exec app nvidia-smi" -ForegroundColor Gray
                        Write-Host "  Enter shell:   docker-compose exec app /bin/bash" -ForegroundColor Gray
                        Write-Host "  Stop services: docker-compose down" -ForegroundColor Gray
                        Write-Host "  Restart:       docker-compose restart" -ForegroundColor Gray
                        Write-Host ""
                        Write-Host "Waiting for service to start..." -ForegroundColor White
                        Start-Sleep -Seconds 5
                        
                        # Check if service is healthy
                        try {
                            $response = Invoke-WebRequest -Uri "http://localhost:7799/health" -UseBasicParsing -TimeoutSec 5
                            if ($response.StatusCode -eq 200) {
                                Write-Host "✓ Health check passed!" -ForegroundColor Green
                            }
                        } catch {
                            Write-Host "⚠ Health check failed - service may still be starting" -ForegroundColor Yellow
                            Write-Host "  Check logs: docker-compose logs -f app" -ForegroundColor Gray
                        }
                    } else {
                        Write-Error "Failed to start services with docker-compose"
                    }
                } finally {
                    Pop-Location
                }
            } else {
                Write-Host "[WOULD RUN] docker-compose up -d" -ForegroundColor Magenta
            }
        }
    }
    
    "cloudrun" {
        Write-Host "Google Cloud Run deployment with GPU" -ForegroundColor White
        
        if ($projectId) {
            $gcrImage = "gcr.io/$projectId/${imageName}:${Tag}"
            
            Write-Host "Project ID: $projectId" -ForegroundColor Gray
            Write-Host "Cloud Run Image: $gcrImage" -ForegroundColor Gray
            
            if (-not $WhatIf) {
                # Tag and push image
                Write-Host "`nTagging image for Cloud Run..." -ForegroundColor White
                & docker tag $fullImageName $gcrImage
                
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "✓ Image tagged successfully" -ForegroundColor Green
                    
                    # Configure docker auth
                    Write-Host "`nConfiguring Docker authentication for GCR..." -ForegroundColor White
                    & gcloud auth configure-docker --quiet
                    
                    # Push to GCR
                    Write-Host "`nPushing image to GCR..." -ForegroundColor Yellow
                    & docker push $gcrImage
                    
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "✓ Image pushed successfully!" -ForegroundColor Green
                        
                        # Deploy to Cloud Run with GPU and GCS mount
                        Write-Host "`n=== DEPLOYING TO CLOUD RUN ===" -ForegroundColor Cyan

                        Write-Host "Deploying with NVIDIA L4 GPU and GCS bucket mount..." -ForegroundColor White
                        
                        # Build environment variables string
                        $envVars = ($envConfig.GetEnumerator() | Where-Object { $_.Key -ne "PROJECT_ID" } | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ","
                        
                        $deployArgs = @(
                            "run", "deploy", "gnosis-ocr"
                            "--image", $gcrImage
                            "--region", "us-central1"
                            "--platform", "managed"
                            "--allow-unauthenticated"
                            "--memory", "32Gi"
                            "--cpu", "8"
                            "--gpu", "1"
                            "--gpu-type", "nvidia-l4"
                            "--concurrency", "1"
                            "--min-instances", "1"
                            "--max-instances", "2"
                            "--session-affinity"
                            "--execution-environment", "gen2"
                            "--no-cpu-throttling"
                            "--port", "8080"
                            "--cpu-boost"
                            "--add-volume", "name=model-cache,type=cloud-storage,bucket=gnosis-ocr-models"
                            "--add-volume-mount", "volume=model-cache,mount-path=/app/cache"
                            "--set-env-vars", $envVars
                            "--service-account", "949870462453-compute@developer.gserviceaccount.com"
                        )
                        
                        Write-Host "Running: gcloud $($deployArgs -join ' ')" -ForegroundColor Gray
                        & gcloud @deployArgs
                        
                        if ($LASTEXITCODE -eq 0) {
                            Write-Host "`n✓ CLOUD RUN DEPLOYMENT SUCCESSFUL!" -ForegroundColor Green
                            
                            # Get service URL
                            $serviceUrl = & gcloud run services describe gnosis-ocr --region=europe-west1 --format="value(status.url)" 2>$null
                            if ($serviceUrl) {
                                Write-Host "`n🔗 Service URL: $serviceUrl" -ForegroundColor Cyan
                                Write-Host "⚡ GPU: NVIDIA L4 with 16Gi memory" -ForegroundColor Yellow
                                Write-Host "🪣 Model cache: Mounted from gs://gnosis-ocr-models" -ForegroundColor Yellow
                                Write-Host "`nUseful commands:" -ForegroundColor White
                                Write-Host "  View logs:    gcloud logs tail --service=gnosis-ocr" -ForegroundColor Gray
                                Write-Host "  Service info: gcloud run services describe gnosis-ocr --region=europe-west1" -ForegroundColor Gray
                            }
                        } else {
                            Write-Error "Cloud Run deployment failed"
                        }
                    } else {
                        Write-Error "Failed to push image to GCR"
                    }
                } else {
                    Write-Error "Failed to tag image for Cloud Run"
                }
            } else {
                Write-Host "[WOULD RUN] Cloud Run deployment with GPU" -ForegroundColor Magenta
            }
        } else {
            Write-Warning "PROJECT_ID not found in .env.cloudrun. Cloud Run deployment requires project ID."
        }
    }
}

Write-Host "`n=== Deployment Complete ===" -ForegroundColor Green

if ($WhatIf) {
    Write-Host "*** DRY RUN COMPLETE - No changes made ***" -ForegroundColor Red
}
