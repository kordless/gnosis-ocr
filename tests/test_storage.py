"""Storage service tests for Gnosis OCR Service"""
import pytest
import os
import json
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import aiofiles

from app.storage_service import StorageService
from app.models import ProcessingStatus
from app.config import settings


class TestStorageService:
    @pytest.fixture
    def temp_storage_path(self):
        """Create temporary storage directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
        
    @pytest.fixture
    def storage_service(self, temp_storage_path):
        """Create storage service with temp directory"""
        with patch('app.storage_service.settings.storage_path', temp_storage_path):
            service = StorageService()
            return service
            
    def test_init(self, storage_service, temp_storage_path):
        """Test storage service initialization"""
        assert os.path.exists(temp_storage_path)
        assert storage_service.scheduler is not None
        assert isinstance(storage_service.sessions, dict)
        
    async def test_start_stop(self, storage_service):
        """Test service start and stop"""
        await storage_service.start()
        assert storage_service.scheduler.running
        
        await storage_service.stop()
        assert not storage_service.scheduler.running
        
    def test_create_session(self, storage_service, temp_storage_path):
        """Test session creation"""
        session_hash = storage_service.create_session()
        
        assert session_hash is not None
        assert len(session_hash) == 36  # UUID format
        
        # Check directories created
        session_path = os.path.join(temp_storage_path, session_hash)
        assert os.path.exists(session_path)
        assert os.path.exists(os.path.join(session_path, 'input'))
        assert os.path.exists(os.path.join(session_path, 'images'))
        assert os.path.exists(os.path.join(session_path, 'output'))
        
        # Check status file
        status_file = os.path.join(session_path, 'status.json')
        assert os.path.exists(status_file)
        
        with open(status_file, 'r') as f:
            status = json.load(f)
            assert status['session_hash'] == session_hash
            assert status['status'] == ProcessingStatus.PENDING.value
            assert status['progress'] == 0.0
            
    async def test_save_uploaded_file(self, storage_service):
        """Test file upload saving"""
        session_hash = storage_service.create_session()
        content = b"Test PDF content"
        filename = "test.pdf"
        
        result = await storage_service.save_uploaded_file(session_hash, filename, content)
        
        assert result['file_size'] == len(content)
        assert os.path.exists(result['file_path'])
        
        # Verify file content
        with open(result['file_path'], 'rb') as f:
            saved_content = f.read()
            assert saved_content == content
            
    async def test_save_uploaded_file_invalid_session(self, storage_service):
        """Test file upload with invalid session"""
        with pytest.raises(ValueError, match="Invalid session"):
            await storage_service.save_uploaded_file("invalid-session", "test.pdf", b"content")
            
    def test_validate_session(self, storage_service, temp_storage_path):
        """Test session validation"""
        session_hash = storage_service.create_session()
        
        assert storage_service.validate_session(session_hash) is True
        assert storage_service.validate_session("invalid-session") is False
        
    def test_get_session_status(self, storage_service):
        """Test getting session status"""
        session_hash = storage_service.create_session()
        
        # From memory
        status = storage_service.get_session_status(session_hash)
        assert status is not None
        assert status['session_hash'] == session_hash
        
        # From file (after clearing memory)
        storage_service.sessions.clear()
        status = storage_service.get_session_status(session_hash)
        assert status is not None
        assert status['session_hash'] == session_hash
        
        # Non-existent session
        assert storage_service.get_session_status("invalid-session") is None
        
    def test_update_session_status(self, storage_service):
        """Test updating session status"""
        session_hash = storage_service.create_session()
        
        # Update to processing
        storage_service.update_session_status(
            session_hash,
            ProcessingStatus.PROCESSING,
            progress=25.0,
            message="Processing started",
            current_page=1
        )
        
        status = storage_service.get_session_status(session_hash)
        assert status['status'] == ProcessingStatus.PROCESSING.value
        assert status['progress'] == 25.0
        assert status['message'] == "Processing started"
        assert status['current_page'] == 1
        assert 'started_at' in status
        
        # Update to completed
        storage_service.update_session_status(
            session_hash,
            ProcessingStatus.COMPLETED,
            progress=100.0
        )
        
        status = storage_service.get_session_status(session_hash)
        assert status['status'] == ProcessingStatus.COMPLETED.value
        assert status['progress'] == 100.0
        assert 'completed_at' in status
        assert 'processing_time' in status
        
    def test_update_session_metadata(self, storage_service):
        """Test updating session metadata"""
        session_hash = storage_service.create_session()
        
        metadata = {
            'filename': 'test.pdf',
            'total_pages': 10,
            'custom_field': 'value'
        }
        
        storage_service.update_session_metadata(session_hash, metadata)
        
        status = storage_service.get_session_status(session_hash)
        assert status['filename'] == 'test.pdf'
        assert status['total_pages'] == 10
        assert status['custom_field'] == 'value'
        
    async def test_save_page_image(self, storage_service):
        """Test saving page image"""
        session_hash = storage_service.create_session()
        image_data = b"fake-image-data"
        
        file_path = await storage_service.save_page_image(session_hash, 1, image_data)
        
        assert os.path.exists(file_path)
        assert file_path.endswith("page_001.png")
        
        with open(file_path, 'rb') as f:
            saved_data = f.read()
            assert saved_data == image_data
            
    async def test_save_page_result(self, storage_service):
        """Test saving page OCR result"""
        session_hash = storage_service.create_session()
        text = "# Page 1\nExtracted text content"
        
        file_path = await storage_service.save_page_result(session_hash, 1, text)
        
        assert os.path.exists(file_path)
        assert file_path.endswith("page_001.md")
        
        with open(file_path, 'r', encoding='utf-8') as f:
            saved_text = f.read()
            assert saved_text == text
            
    async def test_save_combined_result(self, storage_service):
        """Test saving combined OCR result"""
        session_hash = storage_service.create_session()
        combined_text = "# Combined Document\n\nAll pages content"
        
        file_path = await storage_service.save_combined_result(session_hash, combined_text)
        
        assert os.path.exists(file_path)
        assert file_path.endswith("combined_output.md")
        
    async def test_get_page_image(self, storage_service):
        """Test retrieving page image"""
        session_hash = storage_service.create_session()
        image_data = b"test-image"
        
        # Save image first
        await storage_service.save_page_image(session_hash, 1, image_data)
        
        # Retrieve image
        retrieved_data = await storage_service.get_page_image(session_hash, 1)
        assert retrieved_data == image_data
        
        # Non-existent image
        assert await storage_service.get_page_image(session_hash, 99) is None
        
    async def test_get_results(self, storage_service):
        """Test retrieving all results"""
        session_hash = storage_service.create_session()
        
        # Save some results
        await storage_service.save_page_result(session_hash, 1, "Page 1 content")
        await storage_service.save_page_result(session_hash, 2, "Page 2 content")
        await storage_service.save_combined_result(session_hash, "Combined content")
        
        # Save metadata
        metadata_path = os.path.join(
            storage_service.get_session_file_path(session_hash, '', 'output'),
            'metadata.json'
        )
        with open(metadata_path, 'w') as f:
            json.dump({'test': 'metadata'}, f)
            
        results = await storage_service.get_results(session_hash)
        
        assert len(results['pages']) == 2
        assert results['pages'][0]['page_number'] == 1
        assert results['pages'][0]['text'] == "Page 1 content"
        assert results['combined_markdown'] == "Combined content"
        assert results['metadata']['test'] == 'metadata'
        
    def test_get_active_sessions(self, storage_service):
        """Test getting active sessions"""
        # Create sessions with different statuses
        session1 = storage_service.create_session()
        storage_service.update_session_status(session1, ProcessingStatus.PENDING)
        
        session2 = storage_service.create_session()
        storage_service.update_session_status(session2, ProcessingStatus.PROCESSING)
        
        session3 = storage_service.create_session()
        storage_service.update_session_status(session3, ProcessingStatus.COMPLETED)
        
        active_sessions = storage_service.get_active_sessions()
        
        assert session1 in active_sessions
        assert session2 in active_sessions
        assert session3 not in active_sessions
        
    async def test_cleanup_old_sessions(self, storage_service, temp_storage_path):
        """Test cleanup of old sessions"""
        # Create old session
        old_session = storage_service.create_session()
        old_status = storage_service.get_session_status(old_session)
        
        # Modify created_at to be older than timeout
        old_time = datetime.utcnow() - timedelta(seconds=settings.session_timeout + 100)
        old_status['created_at'] = old_time.isoformat()
        storage_service._save_status(old_session, old_status)
        
        # Create recent session
        recent_session = storage_service.create_session()
        
        # Run cleanup
        await storage_service.cleanup_old_sessions()
        
        # Check results
        assert not os.path.exists(os.path.join(temp_storage_path, old_session))
        assert os.path.exists(os.path.join(temp_storage_path, recent_session))
        assert old_session not in storage_service.sessions
        
    def test_create_download_archive(self, storage_service):
        """Test creating download archive"""
        session_hash = storage_service.create_session()
        
        # Add some files to archive
        test_file = os.path.join(
            storage_service.get_session_file_path(session_hash, '', 'output'),
            'test.txt'
        )
        with open(test_file, 'w') as f:
            f.write("Test content")
            
        archive_path = storage_service.create_download_archive(session_hash)
        
        assert archive_path is not None
        assert os.path.exists(archive_path)
        assert archive_path.endswith('.zip')


if __name__ == "__main__":
    pytest.main([__file__])