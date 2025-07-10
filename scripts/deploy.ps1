# Gnosis OCR Deployment Script
# Builds and deploys the OCR service with proper configuration

param(
    [string]$Target = "local",  # local, staging, cloud, cloudrun
    [string]$Tag = "latest",
    [switch]$Rebuild = $false,
    [switch]$BaseOnly = $false,  # Build base image only
    [switch]$WhatIf = $false,
    [switch]$Verbose = $false,
    [switch]$UseDockerRun = $false  # Use docker run instead of docker-compose for local deployment
)



$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "=== Gnosis OCR Deployment ===" -ForegroundColor Cyan
Write-Host "Target: $Target" -ForegroundColor White
Write-Host "Tag: $Tag" -ForegroundColor White
if ($Target -eq "local") {
    Write-Host "Deployment Method: $(if ($UseDockerRun) { 'Docker Run' } else { 'Docker Compose' })" -ForegroundColor White
}
Write-Host "Project Root: $projectRoot" -ForegroundColor Gray


# Validate target
$validTargets = @("local", "staging", "cloud", "cloudrun")
if ($Target -notin $validTargets) {
    Write-Error "Invalid target '$Target'. Must be one of: $($validTargets -join ', ')"
}

# Load environment configuration if deploying to cloud
$envConfig = @{}
if ($Target -in @("staging", "cloud", "cloudrun")) {
    $envFile = Join-Path $projectRoot ".env.cloudrun"
    if (Test-Path $envFile) {
        Write-Host "Loading environment from .env.cloudrun..." -ForegroundColor Gray
        Get-Content $envFile | Where-Object { $_ -match '^\s*[^#].*=' } | ForEach-Object {
            $key, $value = $_ -split '=', 2
            $envConfig[$key.Trim()] = $value.Trim()
        }
        $projectId = $envConfig["PROJECT_ID"]
    } else {
        Write-Warning ".env.cloudrun not found. Copy .env.cloudrun.example and update PROJECT_ID"
        $projectId = $null
    }
}


# Handle base image build mode
if ($BaseOnly) {
    Write-Host "`n=== BASE IMAGE BUILD MODE ===" -ForegroundColor Magenta
    Write-Host "Building base image with models and dependencies" -ForegroundColor White
    Write-Host "This will take 30+ minutes and download ~25GB of data!" -ForegroundColor Yellow
    
    $dockerfile = "Dockerfile.base"
    $imageName = "gnosis-ocr-base"
    $Tag = "v1"  # Base images should use stable version tags
    
    # For base builds, we always target cloud registry
    $projectId = $env:GCP_PROJECT_ID
    if (-not $projectId) {
        try {
            $projectId = gcloud config get-value project 2>$null
        } catch {
            Write-Error "Could not determine GCP project ID for base image build"
        }
    }
    
    if (-not $projectId) {
        Write-Error "GCP project ID required for base image builds. Set GCP_PROJECT_ID or run 'gcloud config set project PROJECT_ID'"
    }
    
    $fullImageName = "gcr.io/$projectId/${imageName}:${Tag}"
} else {
    # Normal build mode - set dockerfile and image name based on target
    switch ($Target) {
        "local" {
            $dockerfile = "Dockerfile"
            $imageName = "gnosis-ocr"
            $composeFile = "docker-compose.yml"
        }
        "staging" {
            $dockerfile = "Dockerfile.cloudrun"
            $imageName = "gnosis-ocr"
            $composeFile = $null
        }
        "cloud" {
            $dockerfile = "Dockerfile"  # Use main Dockerfile that pulls from base
            $imageName = "gnosis-ocr"
            $composeFile = $null
        }
        "cloudrun" {
            $dockerfile = "Dockerfile.cloudrun"
            $imageName = "gnosis-ocr"
            $composeFile = $null
        }
        "lean" {
            $dockerfile = "Dockerfile"  # Use main Dockerfile since .lean was deleted
            $imageName = "gnosis-ocr-lean"
            $composeFile = $null
        }
    }

    $fullImageName = "${imageName}:${Tag}"
}

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

# Handle base image push to GCR
if ($BaseOnly) {
    Write-Host "`n=== Base Image Push to GCR ===" -ForegroundColor Green
    Write-Host "Pushing base image to Google Container Registry..." -ForegroundColor White
    Write-Host "Image: $fullImageName" -ForegroundColor Gray
    
    if (-not $WhatIf) {
        # Ensure docker is authenticated with GCR
        Write-Host "Configuring Docker authentication for GCR..." -ForegroundColor Gray
        & gcloud auth configure-docker --quiet
        
        # Push the image
        Write-Host "Pushing image (this may take several minutes)..." -ForegroundColor Yellow
        & docker push $fullImageName
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ Base image pushed successfully!" -ForegroundColor Green
            Write-Host "`n=== NEXT STEPS ===" -ForegroundColor Cyan
            Write-Host "1. Update main Dockerfile to use this base image:" -ForegroundColor White
            Write-Host "   FROM $fullImageName" -ForegroundColor Gray
            Write-Host "`n2. Build your application image quickly:" -ForegroundColor White
            Write-Host "   .\scripts\deploy.ps1 -Target cloud" -ForegroundColor Gray
            Write-Host "`n3. Deploy to Cloud Run:" -ForegroundColor White
            Write-Host "   (deployment commands will be shown after app build)" -ForegroundColor Gray
        } else {
            Write-Error "Failed to push base image to GCR"
        }
    } else {
        Write-Host "[WOULD RUN] gcloud auth configure-docker --quiet" -ForegroundColor Magenta
        Write-Host "[WOULD RUN] docker push $fullImageName" -ForegroundColor Magenta
    }
    
    # Exit after base image build/push
    Write-Host "`n=== Base Image Build Complete ===" -ForegroundColor Green
    exit 0
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


    
    "staging" {
        Write-Host "Staging deployment" -ForegroundColor White
        
        if ($projectId) {
            $gcrImage = "gcr.io/$projectId/${imageName}:staging-${Tag}"
            
            Write-Host "Project ID: $projectId" -ForegroundColor Gray
            Write-Host "Staging Image: $gcrImage" -ForegroundColor Gray
            
            if (-not $WhatIf) {
                # Tag and push image
                Write-Host "`nTagging image for staging..." -ForegroundColor White

                & docker tag $fullImageName $gcrImage
                
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "✓ Image tagged successfully" -ForegroundColor Green
                    
                    # Configure docker auth
                    Write-Host "`nConfiguring Docker authentication for GCR..." -ForegroundColor White
                    & gcloud auth configure-docker --quiet
                    
                    # Push to GCR
                    Write-Host "`nPushing staging image to GCR..." -ForegroundColor Yellow
                    & docker push $gcrImage
                    
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "✓ Staging image pushed successfully!" -ForegroundColor Green
                        Write-Host "`nStaging image available at: $gcrImage" -ForegroundColor Cyan
                    } else {
                        Write-Error "Failed to push staging image to GCR"
                    }
                } else {
                    Write-Error "Failed to tag image for staging"
                }
            }
        } else {
            Write-Warning "PROJECT_ID not found in .env.cloudrun. Staging deployment requires project ID."
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
                        
                        $deployArgs = @(
                            "run", "deploy", "gnosis-ocr"
                            "--image", $gcrImage
                            "--region", "us-central1"

                            "--platform", "managed"
                            "--allow-unauthenticated"
                            "--memory", "16Gi"
                            "--cpu", "4"
                            "--gpu", "1"
                            "--gpu-type", "nvidia-l4"
                            "--timeout", "3600"
                            "--concurrency", "1"
                            "--min-instances", "0"
                            "--max-instances", "3"




                            "--execution-environment", "gen2"
                            "--no-cpu-throttling"
                            "--port", "8080"
                            "--cpu-boost"



                            "--add-volume", "name=model-cache,type=cloud-storage,bucket=gnosis-ocr-models"
                            "--add-volume-mount", "volume=model-cache,mount-path=/app/cache"
                            "--set-env-vars", "RUNNING_IN_CLOUD=true,GCS_BUCKET_NAME=gnosis-ocr-storage,MODEL_BUCKET_NAME=gnosis-ocr-models,MODEL_CACHE_PATH=/app/cache,HF_HOME=/app/cache,TRANSFORMERS_CACHE=/app/cache,DEVICE=cuda,CUDA_VISIBLE_DEVICES=0,MAX_FILE_SIZE=104857600,SESSION_TIMEOUT=1800,LOG_LEVEL=INFO"


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
    
    "cloud" {
        Write-Host "Google Cloud Build deployment" -ForegroundColor White

        
        # Get project ID from gcloud config or environment
        $projectId = $env:GCP_PROJECT_ID
        if (-not $projectId) {
            try {
                $projectId = gcloud config get-value project 2>$null
            } catch {
                Write-Host "Could not determine GCP project ID" -ForegroundColor Yellow
            }
        }
        
        if ($projectId) {
            $gcrImage = "gcr.io/$projectId/${imageName}:${Tag}"

            
            Write-Host "Project ID: $projectId" -ForegroundColor Gray
            
            if (-not $WhatIf) {
                # Tag and push image automatically
                Write-Host "`nTagging image for GCR..." -ForegroundColor White
                & docker tag $fullImageName $gcrImage
                
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "✓ Image tagged successfully" -ForegroundColor Green
                    
                    # Configure docker auth
                    Write-Host "`nConfiguring Docker authentication for GCR..." -ForegroundColor White
                    & gcloud auth configure-docker --quiet
                    
                    # Push to GCR
                    Write-Host "`nPushing image to GCR (this may take a few minutes)..." -ForegroundColor Yellow
                    & docker push $gcrImage
                    
                    if ($LASTEXITCODE -eq 0) {
                        Write-Host "✓ Image pushed successfully to GCR!" -ForegroundColor Green
                        
                        # Show deployment commands
                        Write-Host "`n=== READY TO DEPLOY ===" -ForegroundColor Cyan
                        Write-Host "Image is now available at: $gcrImage" -ForegroundColor White
                        Write-Host ""
                        Write-Host "Deploy to Cloud Run with GPU (recommended):" -ForegroundColor Yellow
                        Write-Host "gcloud run deploy gnosis-ocr \" -ForegroundColor Gray
                        Write-Host "  --image $gcrImage \" -ForegroundColor Gray
                        Write-Host "  --platform managed \" -ForegroundColor Gray
                        Write-Host "  --region us-central1 \" -ForegroundColor Gray
                        Write-Host "  --memory 8Gi \" -ForegroundColor Gray
                        Write-Host "  --cpu 2 \" -ForegroundColor Gray
                        Write-Host "  --gpu 1 \" -ForegroundColor Gray
                        Write-Host "  --gpu-type nvidia-l4 \" -ForegroundColor Gray
                        Write-Host "  --no-cpu-throttling \" -ForegroundColor Gray
                        Write-Host "  --timeout 3600 \" -ForegroundColor Gray
                        Write-Host "  --max-instances 10 \" -ForegroundColor Gray
                        Write-Host "  --allow-unauthenticated \" -ForegroundColor Gray
                        Write-Host "  --port 7799" -ForegroundColor Gray
                        Write-Host ""
                        Write-Host "Or deploy without GPU (CPU only):" -ForegroundColor Yellow
                        Write-Host "gcloud run deploy gnosis-ocr \" -ForegroundColor Gray
                        Write-Host "  --image $gcrImage \" -ForegroundColor Gray
                        Write-Host "  --platform managed \" -ForegroundColor Gray
                        Write-Host "  --region us-central1 \" -ForegroundColor Gray
                        Write-Host "  --memory 8Gi \" -ForegroundColor Gray
                        Write-Host "  --cpu 2 \" -ForegroundColor Gray
                        Write-Host "  --timeout 3600 \" -ForegroundColor Gray
                        Write-Host "  --max-instances 10 \" -ForegroundColor Gray
                        Write-Host "  --allow-unauthenticated \" -ForegroundColor Gray
                        Write-Host "  --port 7799" -ForegroundColor Gray
                    } else {
                        Write-Error "Failed to push image to GCR"
                    }
                } else {
                    Write-Error "Failed to tag image for GCR"
                }
            } else {
                Write-Host "[WOULD RUN] docker tag $fullImageName $gcrImage" -ForegroundColor Magenta
                Write-Host "[WOULD RUN] gcloud auth configure-docker --quiet" -ForegroundColor Magenta
                Write-Host "[WOULD RUN] docker push $gcrImage" -ForegroundColor Magenta
                Write-Host ""
                Write-Host "[WOULD SHOW] Cloud Run deployment commands" -ForegroundColor Magenta
            }
        } else {
            Write-Host "Set GCP_PROJECT_ID environment variable or run 'gcloud config set project YOUR_PROJECT_ID'" -ForegroundColor Yellow
            Write-Host ""
            Write-Host "Generic deployment steps:" -ForegroundColor White
            Write-Host "  1. docker tag $fullImageName gcr.io/YOUR_PROJECT_ID/${imageName}:${Tag}" -ForegroundColor Gray
            Write-Host "  2. gcloud auth configure-docker" -ForegroundColor Gray
            Write-Host "  3. docker push gcr.io/YOUR_PROJECT_ID/${imageName}:${Tag}" -ForegroundColor Gray

            Write-Host "  4. Deploy using gcloud run deploy (see commands above)" -ForegroundColor Gray
        }
    }

    
    "lean" {
        Write-Host "Lean deployment - image built without models" -ForegroundColor White
        Write-Host "Requires model mounting at runtime" -ForegroundColor Yellow
    }
}

Write-Host "`n=== Deployment Complete ===" -ForegroundColor Green

if ($WhatIf) {
    Write-Host "*** DRY RUN COMPLETE - No changes made ***" -ForegroundColor Red
}
