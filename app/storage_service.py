"""
Storage Service V2 - Unified storage layer for local and cloud environments
Inspired by gnosis-wraith storage architecture with user partitioning
"""
import os
import hashlib
import asyncio
import json
import shutil
from typing import Optional, Dict, List, Union, BinaryIO
from datetime import datetime
from pathlib import Path
import logging

try:
    from google.cloud import storage as gcs
    from google.cloud.exceptions import NotFound
    HAS_GCS = True
except ImportError:
    HAS_GCS = False

logger = logging.getLogger(__name__)


def is_running_in_cloud() -> bool:
    """Detect Google Cloud environment"""
    return os.environ.get('RUNNING_IN_CLOUD', '').lower() == 'true'


def get_storage_config() -> Dict[str, str]:
    """Get current storage configuration"""
    return {
        'file_storage': 'gcs',
        'gcs_bucket': os.environ.get('GCS_BUCKET_NAME', 'gnosis-ocr-storage'),
        'model_bucket': os.environ.get('MODEL_BUCKET_NAME', 'gnosis-ocr-models')
    }



class StorageService:
    """Unified storage service for local and cloud environments"""
    
    def __init__(self, user_email: Optional[str] = None):
        """
        Initialize storage service with optional user context
        
        Args:
            user_email: User email for partitioning (defaults to anonymous)
        """
        self.config = get_storage_config()
        self._user_email = user_email or "anonymous@gnosis-ocr.local"
        self._user_hash = self._compute_user_hash(self._user_email)
        self._is_cloud = is_running_in_cloud()
        
        # Initialize storage backend
        if self._is_cloud:
            if not HAS_GCS:
                raise RuntimeError("Google Cloud Storage client not installed")
            self._init_gcs()
        else:
            self._init_local()
            
        # Initialize cache paths
        self._cache_path = self._get_cache_path()
        
        logger.info(f"StorageService initialized - Cloud: {self._is_cloud}, User: {self._user_hash}")
    
    def force_cloud_mode(self):
        """Force storage service to use cloud mode (for Cloud Run deployments)
        
        Deprecated: Storage service now always uses GCS
        """
        logger.debug("force_cloud_mode called but storage always uses GCS now")
    
    def _compute_user_hash(self, email: str) -> str:
        """Compute 12-char hash for user bucketing"""
        return hashlib.sha256(email.encode()).hexdigest()[:12]
    
    def _init_gcs(self):
        """Initialize Google Cloud Storage client"""
        if not HAS_GCS:
            raise RuntimeError("Google Cloud Storage client not installed. Install with: pip install google-cloud-storage")
        
        from google.cloud import storage as gcs_module
        self._gcs_client = gcs_module.Client()
        self._bucket = self._gcs_client.bucket(self.config['gcs_bucket'])
        
        # Verify bucket exists
        if not self._bucket.exists():
            raise RuntimeError(f"GCS bucket {self.config['gcs_bucket']} does not exist")
    
    def _init_local(self):
        """Initialize local storage (deprecated - always use GCS)"""
        logger.warning("Local storage mode deprecated - should use GCS")
        if not HAS_GCS:
            raise RuntimeError("GCS not available and local storage is deprecated. Install google-cloud-storage: pip install google-cloud-storage")
        # Force GCS mode instead
        self._init_gcs()

    
    def _get_cache_path(self) -> str:
        """Get cache path (deprecated - cache now handled by container)"""
        return "/app/cache"
    
    async def get_cache_info(self) -> Dict[str, Union[str, int, bool]]:
        """Get cache information (deprecated - cache now handled by container)"""
        return {
            "message": "Cache handled by container - model cache at /app/cache",
            "cache_path": "/app/cache",
            "available": True
        }



        
    
    
    
    def get_user_path(self) -> str:
        """Get user-specific storage path: users/{hash}"""
        return f"users/{self._user_hash}"
    
    def get_session_path(self, session_hash: str) -> str:
        """Get full session path: users/{hash}/{session}"""
        return f"{self.get_user_path()}/{session_hash}"
    
    def get_session_file_path(self, session_hash: str, filename: str, 
                            subfolder: Optional[str] = None) -> str:
        """Get full path for a file within a session"""
        session_path = self.get_session_path(session_hash)
        if subfolder:
            return f"{session_path}/{subfolder}/{filename}"
        return f"{session_path}/{filename}"
    
    # Core file operations
    async def save_file(self, content: Union[bytes, str], filename: str, 
                       session_hash: Optional[str] = None) -> str:
        """
        Save file to storage
        
        Args:
            content: File content (bytes or string)
            filename: Name of file
            session_hash: Optional session context
            
        Returns:
            Path where file was saved
        """
        if isinstance(content, str):
            content = content.encode('utf-8')
        
        if session_hash:
            file_path = self.get_session_file_path(session_hash, filename)
        else:
            file_path = f"{self.get_user_path()}/{filename}"
        
        blob = self._bucket.blob(file_path)
        blob.upload_from_string(content)
        logger.info(f"Saved file to GCS: {file_path}")
        
        # Force consistency check for critical files
        if filename in ['metadata.json', 'status.json']:
            # Verify the file was written
            if not blob.exists():
                logger.warning(f"GCS consistency issue - file not immediately available: {file_path}")
            else:
                logger.debug(f"GCS file verified: {file_path}, size: {blob.size} bytes")

        
        return file_path
    
    async def get_file(self, filename: str, session_hash: Optional[str] = None) -> bytes:
        """
        Retrieve file from storage
        
        Args:
            filename: Name of file
            session_hash: Optional session context
            
        Returns:
            File content as bytes
            
        Raises:
            FileNotFoundError: If file doesn't exist
        """
        if session_hash:
            file_path = self.get_session_file_path(session_hash, filename)
        else:
            file_path = f"{self.get_user_path()}/{filename}"
        
        blob = self._bucket.blob(file_path)
        exists = blob.exists()
        logger.debug("GCS file check",
                   file_path=file_path,
                   exists=exists,
                   bucket=self._bucket.name)
        if not exists:
            raise FileNotFoundError(f"File not found: {file_path}")
        return blob.download_as_bytes()

    
    async def delete_file(self, filename: str, session_hash: Optional[str] = None) -> bool:
        """
        Delete file from storage
        
        Args:
            filename: Name of file
            session_hash: Optional session context
            
        Returns:
            True if file was deleted, False if it didn't exist
        """
        if session_hash:
            file_path = self.get_session_file_path(session_hash, filename)
        else:
            file_path = f"{self.get_user_path()}/{filename}"
        
        blob = self._bucket.blob(file_path)
        if blob.exists():
            blob.delete()
            logger.info(f"Deleted file from GCS: {file_path}")
            return True
        return False

    
    async def list_files(self, prefix: Optional[str] = None, 
                        session_hash: Optional[str] = None) -> List[Dict[str, Union[str, int]]]:
        """
        List files in storage
        
        Args:
            prefix: Optional prefix to filter files
            session_hash: Optional session context
            
        Returns:
            List of file metadata dicts with 'name', 'size', 'modified' keys
        """
        if session_hash:
            search_prefix = self.get_session_path(session_hash)
        else:
            search_prefix = self.get_user_path()
        
        if prefix:
            search_prefix = f"{search_prefix}/{prefix}"
        
        files = []
        
        blobs = self._bucket.list_blobs(prefix=search_prefix)
        for blob in blobs:
            files.append({
                'name': blob.name.replace(search_prefix + '/', ''),
                'size': blob.size,
                'modified': blob.updated.isoformat() if blob.updated else None
            })
        
        return files

    
    def get_file_url(self, filename: str, session_hash: Optional[str] = None) -> str:
        """
        Get URL for accessing a file
        
        Args:
            filename: Name of file
            session_hash: Optional session context
            
        Returns:
            URL for accessing the file
        """
        if session_hash:
            return f"/storage/{self._user_hash}/{session_hash}/{filename}"
        return f"/storage/{self._user_hash}/{filename}"
    
    # OCR-specific methods
    async def save_page_image(self, session_hash: str, page_num: int, 
                            image_bytes: bytes) -> Dict[str, str]:
        """Save OCR page image"""
        filename = f"page_{page_num:03d}.png"
        path = await self.save_file(image_bytes, filename, session_hash)
        return {
            'page_num': page_num,
            'filename': filename,
            'path': path,
            'url': self.get_file_url(filename, session_hash)
        }
    
    async def save_page_result(self, session_hash: str, page_num: int, 
                             text: str) -> Dict[str, str]:
        """Save OCR page result"""
        filename = f"page_{page_num:03d}_result.txt"
        path = await self.save_file(text, filename, session_hash)
        return {
            'page_num': page_num,
            'filename': filename,
            'path': path,
            'url': self.get_file_url(filename, session_hash)
        }
    
    async def save_combined_result(self, session_hash: str, markdown: str) -> Dict[str, str]:
        """Save combined OCR result"""
        filename = "combined_output.md"
        path = await self.save_file(markdown, filename, session_hash)
        return {
            'filename': filename,
            'path': path,
            'url': self.get_file_url(filename, session_hash)
        }
    
    async def save_session_metadata(self, session_hash: str, metadata: Dict) -> str:
        """Save session metadata"""
        filename = "metadata.json"
        content = json.dumps(metadata, indent=2)
        return await self.save_file(content, filename, session_hash)
    
    # Session management
    async def create_session(self, initial_metadata: Optional[Dict] = None) -> str:
        """
        Create new session with user context
        
        Returns:
            Session hash/ID
        """
        import uuid
        session_hash = str(uuid.uuid4())
        
        logger.info("Creating session", 
                   session_hash=session_hash,
                   user_email=self._user_email,
                   user_hash=self._user_hash,
                   is_cloud=self._is_cloud)
        
        # Create session metadata
        metadata = {
            'session_id': session_hash,
            'user_email': self._user_email,
            'user_hash': self._user_hash,
            'created_at': datetime.utcnow().isoformat(),
            'status': 'created'
        }
        if initial_metadata:
            metadata.update(initial_metadata)
        
        # Save metadata
        await self.save_session_metadata(session_hash, metadata)
        
        logger.info("Session created successfully", 
                   session_hash=session_hash,
                   session_path=self.get_session_path(session_hash))
        
        return session_hash
    
    async def validate_session(self, session_hash: str) -> bool:
        """Check if session exists and belongs to current user with retry for GCS eventual consistency"""
        import asyncio
        
        logger.debug("Starting session validation",
                    session_hash=session_hash,
                    user_hash=self._user_hash,
                    user_email=self._user_email)
        
        # Retry logic for GCS eventual consistency
        max_retries = 5
        base_delay = 0.5  # Start with 500ms
        
        for attempt in range(max_retries):
            try:
                metadata_content = await self.get_file("metadata.json", session_hash)
                metadata = json.loads(metadata_content)
                stored_user_hash = metadata.get('user_hash')
                
                logger.debug("Session metadata found",
                           session_hash=session_hash,
                           stored_user_hash=stored_user_hash,
                           current_user_hash=self._user_hash,
                           stored_email=metadata.get('user_email'),
                           current_email=self._user_email,
                           match=stored_user_hash == self._user_hash)
                
                return stored_user_hash == self._user_hash
            except FileNotFoundError:
                if attempt < max_retries - 1:  # Don't wait on last attempt
                    delay = base_delay * (2 ** attempt)  # Exponential backoff
                    logger.debug(f"Session validation retry {attempt + 1}, waiting {delay}s", 
                               session_hash=session_hash, attempt=attempt + 1)
                    await asyncio.sleep(delay)
                    continue
                
                logger.debug("Session not found after retries",
                           session_hash=session_hash,
                           attempts=max_retries)
                return False

    
    async def delete_session(self, session_hash: str) -> bool:
        """Delete entire session directory"""
        if not await self.validate_session(session_hash):
            return False
        
        session_path = self.get_session_path(session_hash)
        
        # Delete all blobs with session prefix
        blobs = list(self._bucket.list_blobs(prefix=session_path))
        for blob in blobs:
            blob.delete()
        logger.info(f"Deleted session from GCS: {session_path}")
        return True

    
