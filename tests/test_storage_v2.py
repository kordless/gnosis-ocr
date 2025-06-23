"""
Tests for Storage Service V2
"""
import pytest
import asyncio
import os
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from app.storage_service_v2 import StorageService, is_running_in_cloud, get_storage_config, HAS_GCS


class TestEnvironmentDetection:
    """Test environment detection functions"""
    
    def test_is_running_in_cloud_false(self):
        """Test cloud detection returns False by default"""
        with patch.dict(os.environ, {}, clear=True):
            assert is_running_in_cloud() is False
    
    def test_is_running_in_cloud_true(self):
        """Test cloud detection when RUNNING_IN_CLOUD is set"""
        with patch.dict(os.environ, {'RUNNING_IN_CLOUD': 'true'}):
            assert is_running_in_cloud() is True
        
        with patch.dict(os.environ, {'RUNNING_IN_CLOUD': 'TRUE'}):
            assert is_running_in_cloud() is True
    
    def test_get_storage_config_local(self):
        """Test storage config for local environment"""
        with patch.dict(os.environ, {}, clear=True):
            config = get_storage_config()
            assert config['file_storage'] == 'local'
            assert config['storage_path'] == './storage'
            assert config['users_path'] == 'storage/users'
            assert config['gcs_bucket'] == 'gnosis-ocr-storage'
    
    def test_get_storage_config_cloud(self):
        """Test storage config for cloud environment"""
        with patch.dict(os.environ, {
            'RUNNING_IN_CLOUD': 'true',
            'STORAGE_PATH': '/tmp/storage',
            'GCS_BUCKET_NAME': 'my-bucket'
        }):
            config = get_storage_config()
            assert config['file_storage'] == 'gcs'
            assert config['storage_path'] == '/tmp/storage'
            assert config['gcs_bucket'] == 'my-bucket'


class TestStorageServiceLocal:
    """Test StorageService in local mode"""
    
    @pytest.fixture
    def temp_storage(self):
        """Create temporary storage directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.fixture
    def storage_service(self, temp_storage):
        """Create StorageService instance for testing"""
        with patch.dict(os.environ, {
            'STORAGE_PATH': temp_storage,
            'RUNNING_IN_CLOUD': 'false'
        }):
            service = StorageService(user_email="test@example.com")
            yield service
    
    def test_init_creates_directories(self, temp_storage):
        """Test that initialization creates required directories"""
        with patch.dict(os.environ, {'STORAGE_PATH': temp_storage}):
            service = StorageService()
            
            assert (Path(temp_storage) / 'users').exists()
            assert (Path(temp_storage) / 'logs').exists()
            assert (Path(temp_storage) / 'cache').exists()
    
    def test_user_hash_computation(self):
        """Test user hash generation"""
        service1 = StorageService(user_email="test@example.com")
        service2 = StorageService(user_email="test@example.com")
        service3 = StorageService(user_email="other@example.com")
        
        # Same email should produce same hash
        assert service1._user_hash == service2._user_hash
        # Different email should produce different hash
        assert service1._user_hash != service3._user_hash
        # Hash should be 12 characters
        assert len(service1._user_hash) == 12
    
    @pytest.mark.asyncio
    async def test_save_and_get_file(self, storage_service):
        """Test saving and retrieving a file"""
        content = b"Test file content"
        filename = "test.txt"
        
        # Save file
        path = await storage_service.save_file(content, filename)
        assert storage_service._user_hash in path
        
        # Get file
        retrieved = await storage_service.get_file(filename)
        assert retrieved == content
    
    @pytest.mark.asyncio
    async def test_save_file_with_session(self, storage_service):
        """Test saving file with session context"""
        session_hash = await storage_service.create_session()
        content = "Test content with session"
        filename = "session_test.txt"
        
        path = await storage_service.save_file(content, filename, session_hash)
        assert session_hash in path
        assert filename in path
        
        retrieved = await storage_service.get_file(filename, session_hash)
        assert retrieved.decode('utf-8') == content
    
    @pytest.mark.asyncio
    async def test_delete_file(self, storage_service):
        """Test file deletion"""
        content = b"Delete me"
        filename = "delete_test.txt"
        
        # Save file
        await storage_service.save_file(content, filename)
        
        # Delete file
        deleted = await storage_service.delete_file(filename)
        assert deleted is True
        
        # Try to get deleted file
        with pytest.raises(FileNotFoundError):
            await storage_service.get_file(filename)
        
        # Delete non-existent file
        deleted = await storage_service.delete_file("nonexistent.txt")
        assert deleted is False
    
    @pytest.mark.asyncio
    async def test_list_files(self, storage_service):
        """Test listing files"""
        # Create some files
        await storage_service.save_file(b"file1", "file1.txt")
        await storage_service.save_file(b"file2", "file2.txt")
        await storage_service.save_file(b"file3", "subdir/file3.txt")
        
        # List all files
        files = await storage_service.list_files()
        assert len(files) >= 3
        
        filenames = [f['name'] for f in files]
        assert 'file1.txt' in filenames
        assert 'file2.txt' in filenames
        assert 'subdir/file3.txt' in filenames
        
        # List with prefix
        files = await storage_service.list_files(prefix='subdir')
        assert len(files) == 1
        assert files[0]['name'] == 'file3.txt'
    
    @pytest.mark.asyncio
    async def test_ocr_specific_methods(self, storage_service):
        """Test OCR-specific storage methods"""
        session_hash = await storage_service.create_session()
        
        # Save page image
        image_data = b"fake image data"
        result = await storage_service.save_page_image(session_hash, 1, image_data)
        assert result['page_num'] == 1
        assert result['filename'] == 'page_001.png'
        assert session_hash in result['url']
        
        # Save page result
        text = "Extracted text from page 1"
        result = await storage_service.save_page_result(session_hash, 1, text)
        assert result['page_num'] == 1
        assert result['filename'] == 'page_001_result.txt'
        
        # Save combined result
        markdown = "# Combined Output\n\nAll pages combined"
        result = await storage_service.save_combined_result(session_hash, markdown)
        assert result['filename'] == 'combined_output.md'
        
        # Verify files exist
        files = await storage_service.list_files(session_hash=session_hash)
        filenames = [f['name'] for f in files]
        assert 'page_001.png' in filenames
        assert 'page_001_result.txt' in filenames
        assert 'combined_output.md' in filenames
    
    @pytest.mark.asyncio
    async def test_session_management(self, storage_service):
        """Test session creation and validation"""
        # Create session
        session_hash = await storage_service.create_session({
            'document_name': 'test.pdf',
            'page_count': 5
        })
        assert session_hash is not None
        
        # Validate session
        valid = await storage_service.validate_session(session_hash)
        assert valid is True
        
        # Invalid session
        valid = await storage_service.validate_session("invalid-session")
        assert valid is False
        
        # Get metadata
        metadata_content = await storage_service.get_file("metadata.json", session_hash)
        metadata = json.loads(metadata_content)
        assert metadata['session_id'] == session_hash
        assert metadata['user_hash'] == storage_service._user_hash
        assert metadata['document_name'] == 'test.pdf'
        assert metadata['page_count'] == 5
    
    @pytest.mark.asyncio
    async def test_delete_session(self, storage_service):
        """Test session deletion"""
        # Create session with files
        session_hash = await storage_service.create_session()
        await storage_service.save_file(b"test", "test.txt", session_hash)
        await storage_service.save_page_image(session_hash, 1, b"image")
        
        # Delete session
        deleted = await storage_service.delete_session(session_hash)
        assert deleted is True
        
        # Verify session is gone
        valid = await storage_service.validate_session(session_hash)
        assert valid is False
        
        # Try to get file from deleted session
        with pytest.raises(FileNotFoundError):
            await storage_service.get_file("test.txt", session_hash)
    
    def test_get_file_url(self, storage_service):
        """Test URL generation"""
        # URL without session
        url = storage_service.get_file_url("test.txt")
        assert url == f"/storage/{storage_service._user_hash}/test.txt"
        
        # URL with session
        session_hash = "test-session"
        url = storage_service.get_file_url("test.txt", session_hash)
        assert url == f"/storage/{storage_service._user_hash}/{session_hash}/test.txt"
    
    @pytest.mark.asyncio
    async def test_cache_management(self, storage_service):
        """Test cache-related methods"""
        # Get cache config
        cache_config = storage_service.get_cache_config()
        assert 'cache_dir' in cache_config
        assert cache_config['local_files_only'] is True
        assert cache_config['trust_remote_code'] is True
        
        # Verify model cache (should return False for non-existent model)
        exists = await storage_service.verify_model_cache("fake/model")
        assert exists is False
        
        # Get cache info
        info = await storage_service.get_cache_info()
        assert 'path' in info
        assert 'exists' in info
        assert info['is_cloud'] is False


@pytest.mark.skipif(not HAS_GCS, reason="Google Cloud Storage not available")
class TestStorageServiceCloud:
    """Test StorageService in cloud mode"""
    
    @pytest.fixture
    def mock_gcs(self):
        """Mock GCS client and bucket"""
        with patch('app.storage_service_v2.gcs.Client') as mock_client:
            mock_bucket = Mock()
            mock_bucket.exists.return_value = True
            mock_client.return_value.bucket.return_value = mock_bucket
            yield mock_bucket
    
    @pytest.fixture
    def cloud_storage_service(self, mock_gcs):
        """Create StorageService in cloud mode"""
        with patch.dict(os.environ, {
            'RUNNING_IN_CLOUD': 'true',
            'GCS_BUCKET_NAME': 'test-bucket'
        }):
            service = StorageService(user_email="cloud@example.com")
            yield service
    
    @pytest.mark.asyncio
    async def test_cloud_save_file(self, cloud_storage_service, mock_gcs):
        """Test saving file to GCS"""
        content = b"Cloud content"
        filename = "cloud_test.txt"
        
        mock_blob = Mock()
        mock_gcs.blob.return_value = mock_blob
        
        path = await cloud_storage_service.save_file(content, filename)
        
        # Verify blob was created and uploaded
        mock_gcs.blob.assert_called_once()
        mock_blob.upload_from_string.assert_called_once_with(content)
        assert cloud_storage_service._user_hash in path
    
    @pytest.mark.asyncio
    async def test_cloud_get_file(self, cloud_storage_service, mock_gcs):
        """Test retrieving file from GCS"""
        content = b"Cloud content"
        filename = "cloud_test.txt"
        
        mock_blob = Mock()
        mock_blob.exists.return_value = True
        mock_blob.download_as_bytes.return_value = content
        mock_gcs.blob.return_value = mock_blob
        
        retrieved = await cloud_storage_service.get_file(filename)
        
        assert retrieved == content
        mock_blob.download_as_bytes.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cloud_list_files(self, cloud_storage_service, mock_gcs):
        """Test listing files in GCS"""
        # Mock blob objects
        mock_blob1 = Mock()
        mock_blob1.name = f"users/{cloud_storage_service._user_hash}/file1.txt"
        mock_blob1.size = 100
        mock_blob1.updated = datetime.utcnow()
        
        mock_blob2 = Mock()
        mock_blob2.name = f"users/{cloud_storage_service._user_hash}/file2.txt"
        mock_blob2.size = 200
        mock_blob2.updated = datetime.utcnow()
        
        mock_gcs.list_blobs.return_value = [mock_blob1, mock_blob2]
        
        files = await cloud_storage_service.list_files()
        
        assert len(files) == 2
        assert files[0]['name'] == 'file1.txt'
        assert files[0]['size'] == 100
        assert files[1]['name'] == 'file2.txt'
        assert files[1]['size'] == 200


class TestUserIsolation:
    """Test that users cannot access each other's files"""
    
    @pytest.fixture
    def temp_storage(self):
        """Create temporary storage directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @pytest.mark.asyncio
    async def test_user_isolation(self, temp_storage):
        """Test that different users have isolated storage"""
        with patch.dict(os.environ, {'STORAGE_PATH': temp_storage}):
            # Create two users
            user1_service = StorageService(user_email="user1@example.com")
            user2_service = StorageService(user_email="user2@example.com")
            
            # User 1 saves a file
            await user1_service.save_file(b"User 1 secret", "secret.txt")
            
            # User 2 tries to access it
            with pytest.raises(FileNotFoundError):
                await user2_service.get_file("secret.txt")
            
            # User 2 saves their own file
            await user2_service.save_file(b"User 2 data", "data.txt")
            
            # Verify each user only sees their own files
            user1_files = await user1_service.list_files()
            user2_files = await user2_service.list_files()
            
            user1_names = [f['name'] for f in user1_files]
            user2_names = [f['name'] for f in user2_files]
            
            assert 'secret.txt' in user1_names
            assert 'secret.txt' not in user2_names
            assert 'data.txt' in user2_names
            assert 'data.txt' not in user1_names
    
    @pytest.mark.asyncio
    async def test_session_user_validation(self, temp_storage):
        """Test that sessions are tied to users"""
        with patch.dict(os.environ, {'STORAGE_PATH': temp_storage}):
            user1_service = StorageService(user_email="user1@example.com")
            user2_service = StorageService(user_email="user2@example.com")
            
            # User 1 creates a session
            session_hash = await user1_service.create_session()
            
            # User 1 can validate their session
            assert await user1_service.validate_session(session_hash) is True
            
            # User 2 cannot validate user 1's session
            assert await user2_service.validate_session(session_hash) is False
            
            # User 2 cannot delete user 1's session
            assert await user2_service.delete_session(session_hash) is False