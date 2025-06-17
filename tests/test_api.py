"""API endpoint tests for Gnosis OCR Service"""
import pytest
import httpx
from fastapi.testclient import TestClient
import tempfile
import os
from unittest.mock import patch, MagicMock
from io import BytesIO

from app.main import app
from app.models import ProcessingStatus


client = TestClient(app)


def create_test_pdf():
    """Create a minimal test PDF file"""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.drawString(100, 750, "Test PDF Document")
    c.drawString(100, 700, "This is a test page for OCR")
    c.showPage()
    c.save()
    
    buffer.seek(0)
    return buffer.getvalue()


class TestHealthEndpoint:
    def test_health_check(self):
        """Test health check endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "gpu_available" in data
        assert "model_loaded" in data
        assert "storage_available" in data
        assert "active_sessions" in data


class TestUploadEndpoint:
    @patch('app.main.storage_service')
    @patch('app.main.process_document_task')
    def test_upload_success(self, mock_process_task, mock_storage):
        """Test successful PDF upload"""
        # Mock storage service
        mock_storage.create_session.return_value = "test-session-123"
        mock_storage.save_uploaded_file.return_value = {
            'file_path': '/tmp/test.pdf',
            'file_size': 1024
        }
        
        # Create test PDF
        pdf_content = create_test_pdf()
        
        response = client.post(
            "/upload",
            files={"file": ("test.pdf", pdf_content, "application/pdf")}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["session_hash"] == "test-session-123"
        assert data["filename"] == "test.pdf"
        assert data["file_size"] == len(pdf_content)
        assert "status_url" in data
        assert "results_url" in data
        
    def test_upload_no_file(self):
        """Test upload with no file"""
        response = client.post("/upload")
        assert response.status_code == 422
        
    def test_upload_invalid_file_type(self):
        """Test upload with invalid file type"""
        response = client.post(
            "/upload",
            files={"file": ("test.txt", b"test content", "text/plain")}
        )
        assert response.status_code == 400
        assert "Invalid file type" in response.json()["detail"]
        
    @patch('app.main.settings')
    def test_upload_file_too_large(self, mock_settings):
        """Test upload with file exceeding size limit"""
        mock_settings.max_file_size = 100  # 100 bytes limit
        mock_settings.allowed_extensions = {".pdf"}
        
        pdf_content = b"x" * 200  # 200 bytes
        
        response = client.post(
            "/upload",
            files={"file": ("test.pdf", pdf_content, "application/pdf")}
        )
        assert response.status_code == 400
        assert "File too large" in response.json()["detail"]


class TestStatusEndpoint:
    @patch('app.main.storage_service')
    def test_status_check_success(self, mock_storage):
        """Test successful status check"""
        mock_storage.get_session_status.return_value = {
            'status': ProcessingStatus.PROCESSING.value,
            'progress': 50.0,
            'current_page': 5,
            'total_pages': 10,
            'message': 'Processing page 5 of 10',
            'started_at': '2024-01-15T10:30:00'
        }
        
        response = client.get("/status/test-session-123")
        assert response.status_code == 200
        
        data = response.json()
        assert data["session_hash"] == "test-session-123"
        assert data["status"] == "processing"
        assert data["progress"] == 50.0
        assert data["current_page"] == 5
        assert data["total_pages"] == 10
        
    @patch('app.main.storage_service')
    def test_status_session_not_found(self, mock_storage):
        """Test status check for non-existent session"""
        mock_storage.get_session_status.return_value = None
        
        response = client.get("/status/invalid-session")
        assert response.status_code == 404
        assert "Session not found" in response.json()["detail"]


class TestResultsEndpoint:
    @patch('app.main.storage_service')
    def test_results_success(self, mock_storage):
        """Test successful results retrieval"""
        mock_storage.get_session_status.return_value = {
            'status': ProcessingStatus.COMPLETED.value,
            'filename': 'test.pdf',
            'total_pages': 2,
            'processing_time': 15.5,
            'created_at': '2024-01-15T10:30:00'
        }
        
        mock_storage.get_results.return_value = {
            'pages': [
                {'page_number': 1, 'text': 'Page 1 content'},
                {'page_number': 2, 'text': 'Page 2 content'}
            ],
            'metadata': {'model': 'nanonets/Nanonets-OCR-s'}
        }
        
        response = client.get("/results/test-session-123")
        assert response.status_code == 200
        
        data = response.json()
        assert data["session_hash"] == "test-session-123"
        assert data["filename"] == "test.pdf"
        assert data["total_pages"] == 2
        assert len(data["pages"]) == 2
        assert data["processing_time"] == 15.5
        
    @patch('app.main.storage_service')
    def test_results_not_ready(self, mock_storage):
        """Test results retrieval when processing not completed"""
        mock_storage.get_session_status.return_value = {
            'status': ProcessingStatus.PROCESSING.value
        }
        
        response = client.get("/results/test-session-123")
        assert response.status_code == 400
        assert "Processing not completed" in response.json()["detail"]


class TestImageEndpoint:
    @patch('app.main.storage_service')
    def test_get_page_image_success(self, mock_storage):
        """Test successful page image retrieval"""
        mock_storage.validate_session.return_value = True
        mock_storage.get_page_image.return_value = b"fake-image-data"
        
        response = client.get("/images/test-session-123/1")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        
    @patch('app.main.storage_service')
    def test_get_page_image_not_found(self, mock_storage):
        """Test page image not found"""
        mock_storage.validate_session.return_value = True
        mock_storage.get_page_image.return_value = None
        
        response = client.get("/images/test-session-123/99")
        assert response.status_code == 404


class TestDownloadEndpoint:
    @patch('app.main.storage_service')
    def test_download_success(self, mock_storage):
        """Test successful results download"""
        mock_storage.validate_session.return_value = True
        mock_storage.get_session_status.return_value = {
            'status': ProcessingStatus.COMPLETED.value
        }
        
        # Create a temporary file for the archive
        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
            tmp.write(b"fake-zip-content")
            tmp_path = tmp.name
            
        mock_storage.create_download_archive.return_value = tmp_path
        
        try:
            response = client.get("/download/test-session-123")
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/zip"
        finally:
            os.unlink(tmp_path)
            
    @patch('app.main.storage_service')
    def test_download_not_completed(self, mock_storage):
        """Test download when processing not completed"""
        mock_storage.validate_session.return_value = True
        mock_storage.get_session_status.return_value = {
            'status': ProcessingStatus.PROCESSING.value
        }
        
        response = client.get("/download/test-session-123")
        assert response.status_code == 400
        assert "Processing not completed" in response.json()["detail"]


if __name__ == "__main__":
    pytest.main([__file__])