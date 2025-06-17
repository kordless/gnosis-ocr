# Gnosis OCR - Cloud-Ready OCR Service

A GPU-accelerated OCR service using the Nanonets-OCR-s model, deployable to Google Cloud Run or runnable locally with Docker Compose.

## Features

- 🚀 GPU-accelerated OCR using Nanonets-OCR-s model
- 🔒 Secure session-based document isolation
- 📄 PDF to Markdown conversion with LaTeX equations
- 🖼️ Extracted page images accessible via API
- 🏃 Cloud Run ready with GPU support
- 🐳 Local development with Docker Compose
- 📊 Progress tracking and status endpoints

## Project Structure

```
gnosis-ocr/
├── README.md                   # This file
├── PROJECT_STRUCTURE.md        # Detailed file structure
├── IMPLEMENTATION_GUIDE.md     # Step-by-step implementation
├── API_DOCUMENTATION.md        # API endpoint documentation
├── DEPLOYMENT_GUIDE.md         # Cloud Run deployment instructions
├── Dockerfile                  # Multi-stage Docker build
├── docker-compose.yml          # Local development setup
├── requirements.txt            # Python dependencies
├── .env.example               # Environment variables template
├── app/
│   ├── __init__.py
│   ├── main.py                # FastAPI application
│   ├── models.py              # Pydantic models
│   ├── ocr_service.py         # OCR processing logic
│   ├── storage_service.py     # File handling & sessions
│   └── config.py              # Configuration
├── static/
│   ├── index.html             # Upload UI
│   ├── style.css              # Styling
│   └── script.js              # Frontend logic
└── tests/
    ├── test_api.py            # API tests
    ├── test_ocr.py            # OCR service tests
    └── test_storage.py        # Storage tests
```

## Quick Start

### Local Development

1. Clone and setup:
```bash
cd gnosis/development/nanonets
git clone [repository] gnosis-ocr
cd gnosis-ocr
```

2. Copy environment variables:
```bash
cp .env.example .env
```

3. Run with Docker Compose:
```bash
docker-compose up --build
```

4. Access the service:
- Web UI: http://localhost:7799
- API: http://localhost:7799/docs

### Cloud Run Deployment

See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) for detailed instructions.

## API Overview

- `POST /upload` - Upload PDF document
- `GET /status/{hash}` - Check processing status
- `GET /results/{hash}` - Get OCR results
- `GET /images/{hash}/{page}` - Get page image
- `GET /download/{hash}` - Download all results

See [API_DOCUMENTATION.md](API_DOCUMENTATION.md) for complete documentation.

## Architecture

The service uses a session-based architecture where each upload creates a unique session hash. All files and results are isolated by session, preventing cross-access between different users' documents.

```
User Upload → Session Hash → Processing → Results
     ↓             ↓              ↓          ↓
  PDF File    UUID Generated  GPU OCR   Markdown
                               Model     + Images
```

## Development

### Prerequisites

- Docker & Docker Compose
- NVIDIA GPU (optional for local development)
- Google Cloud SDK (for deployment)

### Building

```bash
# Build the Docker image
docker build -t gnosis-ocr .

# Run tests
docker-compose run --rm app pytest
```

## License

[Your License Here]
