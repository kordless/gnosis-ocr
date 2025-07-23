# GEMINI Overview

Gnosis OCR is a FastAPI-based document processing service designed for GPU-accelerated optical character recognition. It ships with Docker tooling for local and Google Cloud Run deployment.

## Local Development
1. Copy `.evn.sample` to `.env` and adjust settings.
2. Build and start the service with Docker Compose:
   ```bash
   docker-compose up --build
   ```
3. Visit `http://localhost:7799` to use the web interface.

## Cloud Deployment
Use `deploy.sh` (or `deploy.ps1` on Windows) with the `cloudrun` target after preparing `.env.cloudrun`.

```bash
./deploy.sh --target cloudrun --tag <version>
```

The script builds the Docker image, pushes it to Google Container Registry and deploys to Cloud Run.

## Repository Layout
- **app/** – FastAPI application code and static assets
- **Dockerfile.unified** – single Dockerfile used for local and cloud images
- **docker-compose.yml** – local container orchestration
- **deploy.sh / deploy.ps1** – deployment helpers
- **requirements.txt** – Python dependencies

## Code Overview

### Core Modules
- `app/main.py` – FastAPI application setup, web UI, and storage endpoints.
- `app/ocr_service.py` – Loads the Hugging Face OCR model and performs inference.
- `app/storage_service.py` – Unified local/GCS storage layer for session files.
- `app/jobs.py` – Job manager and processor for page extraction and OCR tasks.
- `app/job_routes.py` – REST API routes for creating jobs and checking status.
- `app/uploader.py` – Handles standard and chunked uploads from the browser.
- `app/config.py` – Application settings using Pydantic.

### Processing Flow
1. A PDF is uploaded via `/storage/upload` (normal or chunked).
2. `JobManager` submits an `extract_pages` job that converts pages to PNG.
3. `JobProcessor` runs the job (using Cloud Tasks in the cloud or threads locally).
4. Once pages exist, an `ocr` job processes them in batches using `OCRService`.
5. Results are written back to storage and served through `/storage/<user>/<session>`.
6. Clients poll `/api/jobs/{session_id}/status` to monitor progress.

## License
This project is licensed under the Apache 2.0 License.

