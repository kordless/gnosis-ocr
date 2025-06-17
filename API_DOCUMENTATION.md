# API Documentation

## Base URL

- Local: `http://localhost:8080`
- Cloud Run: `https://your-service-name-xxxxx-uc.a.run.app`

## Authentication

Currently, the API uses session-based isolation without authentication. Each upload creates a unique session hash that acts as an access token for that document.

## Endpoints

### 1. Upload Document

Upload a PDF document for OCR processing.

**Endpoint:** `POST /upload`

**Request:**
- Method: `POST`
- Content-Type: `multipart/form-data`
- Body: PDF file

```bash
curl -X POST http://localhost:8080/upload \
  -F "file=@document.pdf"
```

**Response:**
```json
{
  "session_hash": "550e8400-e29b-41d4-a716-446655440000",
  "filename": "document.pdf",
  "status": "processing",
  "upload_time": "2024-01-20T10:30:00Z"
}
```

**Status Codes:**
- `200 OK` - Upload successful
- `400 Bad Request` - Invalid file type or size
- `500 Internal Server Error` - Server error

### 2. Check Processing Status

Get the current processing status of a document.

**Endpoint:** `GET /status/{session_hash}`

**Request:**
```bash
curl http://localhost:8080/status/550e8400-e29b-41d4-a716-446655440000
```

**Response:**
```json
{
  "session_hash": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "progress": 0.45,
  "current_page": 23,
  "total_pages": 50,
  "error": null,
  "processing_time": null
}
```

**Status Values:**
- `pending` - Upload received, not started
- `processing` - OCR in progress
- `completed` - Processing finished successfully
- `failed` - Processing failed with error

### 3. Get OCR Results

Retrieve the OCR results for a completed document.

**Endpoint:** `GET /results/{session_hash}`

**Request:**
```bash
curl http://localhost:8080/results/550e8400-e29b-41d4-a716-446655440000
```

**Response:**
```json
{
  "session_hash": "550e8400-e29b-41d4-a716-446655440000",
  "content": "# Document Title\n\nExtracted text content...",
  "page_count": 50,
  "processing_time": 125.4,
  "pages": [
    "Page 1 content...",
    "Page 2 content..."
  ]
}
```

**Status Codes:**
- `200 OK` - Results available
- `400 Bad Request` - Processing not completed
- `404 Not Found` - Session not found

### 4. Get Page Image

Retrieve a specific page as an image.

**Endpoint:** `GET /images/{session_hash}/{page}`

**Parameters:**
- `session_hash` - The session identifier
- `page` - Page number (1-indexed)

**Request:**
```bash
curl http://localhost:8080/images/550e8400-e29b-41d4-a716-446655440000/1 \
  --output page_1.png
```

**Response:**
- Content-Type: `image/png`
- Binary PNG image data

### 5. Download All Results

Download all results as a ZIP file.

**Endpoint:** `GET /download/{session_hash}`

**Request:**
```bash
curl http://localhost:8080/download/550e8400-e29b-41d4-a716-446655440000 \
  --output results.zip
```

**Response:**
- Content-Type: `application/zip`
- ZIP file containing:
  - `combined_output.md` - All pages combined
  - `pages/` - Individual page markdown files
  - `images/` - Extracted page images
  - `metadata.json` - Processing metadata

### 6. Health Check

Check if the service is running and model is loaded.

**Endpoint:** `GET /health`

**Request:**
```bash
curl http://localhost:8080/health
```

**Response:**
```json
{
  "status": "healthy",
  "model_loaded": true,
  "timestamp": "2024-01-20T10:30:00Z"
}
```

### 7. Delete Session

Manually delete a session and its data.

**Endpoint:** `DELETE /session/{session_hash}`

**Request:**
```bash
curl -X DELETE http://localhost:8080/session/550e8400-e29b-41d4-a716-446655440000
```

**Response:**
```json
{
  "message": "Session deleted successfully"
}
```

## WebSocket Support (Optional)

For real-time progress updates:

**Endpoint:** `WS /ws/{session_hash}`

**Messages:**
```json
// Progress update
{
  "type": "progress",
  "current_page": 10,
  "total_pages": 50,
  "progress": 0.2
}

// Completion
{
  "type": "completed",
  "processing_time": 125.4
}

// Error
{
  "type": "error",
  "error": "Processing failed: Out of memory"
}
```

## Error Responses

All endpoints may return these error formats:

```json
{
  "detail": "Error message",
  "status_code": 400,
  "type": "validation_error"
}
```

Common errors:
- `400` - Invalid request (wrong file type, missing parameters)
- `404` - Session not found
- `413` - File too large
- `500` - Internal server error
- `503` - Service unavailable (model not loaded)

## Rate Limiting

- Default: 10 requests per minute per IP
- Upload endpoint: 5 uploads per minute per IP

## File Constraints

- Maximum file size: 50MB
- Supported formats: PDF only
- Maximum pages: 500
- Session timeout: 1 hour

## Example Usage Flow

```python
import requests
import time

# 1. Upload document
with open("document.pdf", "rb") as f:
    response = requests.post(
        "http://localhost:8080/upload",
        files={"file": f}
    )
    upload_data = response.json()
    session_hash = upload_data["session_hash"]

# 2. Check status
while True:
    status_response = requests.get(
        f"http://localhost:8080/status/{session_hash}"
    )
    status_data = status_response.json()
    
    print(f"Status: {status_data['status']}")
    print(f"Progress: {status_data.get('progress', 0) * 100:.1f}%")
    
    if status_data["status"] == "completed":
        break
    elif status_data["status"] == "failed":
        print(f"Error: {status_data['error']}")
        break
    
    time.sleep(2)

# 3. Get results
if status_data["status"] == "completed":
    results_response = requests.get(
        f"http://localhost:8080/results/{session_hash}"
    )
    results = results_response.json()
    print(f"OCR completed in {results['processing_time']}s")
    print(f"Content preview: {results['content'][:200]}...")
    
    # 4. Download all results
    download_response = requests.get(
        f"http://localhost:8080/download/{session_hash}"
    )
    with open("results.zip", "wb") as f:
        f.write(download_response.content)
```

## CURL Examples

```bash
# Upload PDF
SESSION=$(curl -s -X POST http://localhost:8080/upload \
  -F "file=@document.pdf" | jq -r '.session_hash')

# Check status
curl -s http://localhost:8080/status/$SESSION | jq

# Get results (when completed)
curl -s http://localhost:8080/results/$SESSION | jq

# Get first page image
curl -s http://localhost:8080/images/$SESSION/1 --output page_1.png

# Download all results
curl -s http://localhost:8080/download/$SESSION --output results.zip
```
