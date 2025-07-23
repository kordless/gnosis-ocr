"""
Storage Service V2 - Unified storage layer for local and cloud environments
Inspired by gnosis-wraith storage architecture with user partitioning
"""
import os
import hashlib
import asyncio
import json
import shutil
import io
from typing import Optional, Dict, List, Union, BinaryIO
from datetime import datetime
from pathlib import Path
import logging



logger = logging.getLogger(__name__)

try:
    from google.cloud import storage as gcs
    from google.cloud.exceptions import NotFound
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False
    logger.warning("Google Cloud Storage not available - local mode only")


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
            if not GCS_AVAILABLE:
                raise RuntimeError("Google Cloud Storage client not installed")
            try:
                self._init_gcs()
            except Exception as e:
                logger.error(f"Failed to initialize GCS: {str(e)}")
                raise RuntimeError(f"GCS initialization failed: {str(e)}")
        else:
            self._init_local()
            
        logger.info(f"StorageService initialized - Cloud: {self._is_cloud}, User: {self._user_hash}")


    
    def _compute_user_hash(self, email: str) -> str:
        """Compute 12-char hash for user bucketing"""
        return hashlib.sha256(email.encode()).hexdigest()[:12]
    
    def _init_gcs(self):
        """Initialize Google Cloud Storage client"""
        if not GCS_AVAILABLE:
            raise RuntimeError("Google Cloud Storage client not installed. Install with: pip install google-cloud-storage")
        
        from google.cloud import storage as gcs_module
        self._gcs_client = gcs_module.Client()
        self._bucket = self._gcs_client.bucket(self.config['gcs_bucket'])
        
        # Don't check if bucket exists during init - it causes issues
        # The bucket should exist, but checking can fail due to permissions
        logger.info(f"GCS client initialized for bucket: {self.config['gcs_bucket']}")

    
    def _init_local(self):
        """Initialize local filesystem storage"""
        self._storage_root = "/app/storage"
        self._ensure_local_dirs()
        logger.info(f"Local storage initialized at {self._storage_root}")
    
    def _ensure_local_dirs(self):
        """Ensure required local directories exist"""
        base_dirs = [
            self._storage_root,
            f"{self._storage_root}/users"
        ]
        for dir_path in base_dirs:
            os.makedirs(dir_path, exist_ok=True)
            logger.debug(f"Ensured directory exists: {dir_path}")

    
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
        
        if self._is_cloud:
            # GCS branch
            blob = self._bucket.blob(file_path)
            # Instruct GCS and other caches not to store this object
            if filename.endswith('.json'):
                blob.cache_control = "no-cache, max-age=0"
            if isinstance(content, str):
                content = content.encode('utf-8')
            await asyncio.to_thread(blob.upload_from_string, content)
            logger.info(f"Saved file to GCS: {file_path}")
            
            # Force consistency check for critical files
            if filename in ['metadata.json', 'status.json']:
                # Verify the file was written
                exists = await asyncio.to_thread(blob.exists)
                if not exists:
                    logger.warning(f"GCS consistency issue - file not immediately available: {file_path}")
                else:
                    size = await asyncio.to_thread(lambda: blob.size)
                    logger.debug(f"GCS file verified: {file_path}, size: {size} bytes")
        else:
            # Local filesystem branch
            full_path = f"{self._storage_root}/{file_path}"
            await asyncio.to_thread(os.makedirs, os.path.dirname(full_path), exist_ok=True)
            
            def write_local_file():
                with open(full_path, 'wb') as f:
                    f.write(content)
            
            await asyncio.to_thread(write_local_file)
            logger.info(f"Saved file locally: {full_path}")

        
        return file_path
    
    async def save_file_stream(self, stream, filename: str,
                               session_hash: Optional[str] = None) -> str:
        """
        Save a file from an async stream/generator to storage.
        This is more memory-efficient for large files.
        """
        if session_hash:
            file_path = self.get_session_file_path(session_hash, filename)
        else:
            file_path = f"{self.get_user_path()}/{filename}"

        if self._is_cloud:
            # GCS branch: Collect chunks then upload
            blob = self._bucket.blob(file_path)
            
            try:
                # Collect all chunks into a single buffer
                buffer = io.BytesIO()
                total_size = 0
                chunk_count = 0
                
                logger.info(f"Starting to collect chunks for {file_path}")
                async for chunk in stream:
                    buffer.write(chunk)
                    total_size += len(chunk)
                    chunk_count += 1
                    logger.debug(f"Collected chunk {chunk_count}: {len(chunk)} bytes")
                
                logger.info(f"Collected {chunk_count} chunks, total size: {total_size} bytes")
                
                # Upload the complete buffer
                buffer.seek(0)
                await asyncio.to_thread(blob.upload_from_file, buffer)
                logger.info(f"Successfully saved streamed file to GCS: {file_path} ({total_size} bytes)")
                
                # Verify the upload
                exists = await asyncio.to_thread(blob.exists)
                if exists:
                    size = await asyncio.to_thread(lambda: blob.size)
                    logger.info(f"Verified GCS file: {file_path}, size: {size} bytes")
                else:
                    logger.error(f"GCS file verification failed: {file_path}")
                    
            except Exception as e:
                logger.error(f"Failed to save streamed file to GCS: {file_path}, error: {e}", exc_info=True)
                raise


        else:
            # Local filesystem branch: Stream content directly to a file
            full_path = f"{self._storage_root}/{file_path}"
            await asyncio.to_thread(os.makedirs, os.path.dirname(full_path), exist_ok=True)

            async def write_local_stream():
                with open(full_path, 'wb') as f:
                    async for chunk in stream:
                        f.write(chunk)
            
            # This doesn't need to_thread itself because the generator controls the async flow
            await write_local_stream()
            logger.info(f"Saved streamed file locally: {full_path}")

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
        
        if self._is_cloud:
            # GCS branch
            blob = self._bucket.blob(file_path)
            
            try:
                # Force a metadata refresh to bypass caches and get the latest version info
                await asyncio.to_thread(blob.reload)
            except NotFound:
                # The file doesn't exist at all
                logger.debug(f"GCS file not found: {file_path} in bucket {self._bucket.name}")
                raise FileNotFoundError(f"File not found: {file_path}")
            
            # Now that we've reloaded, the download will be the latest version
            return await asyncio.to_thread(blob.download_as_bytes)
        else:
            # Local filesystem branch
            full_path = f"{self._storage_root}/{file_path}"
            exists = await asyncio.to_thread(os.path.exists, full_path)
            if not exists:
                raise FileNotFoundError(f"File not found: {full_path}")
            
            def read_local_file():
                with open(full_path, 'rb') as f:
                    return f.read()
            
            return await asyncio.to_thread(read_local_file)


    
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
        
        if self._is_cloud:
            # GCS branch
            blob = self._bucket.blob(file_path)
            exists = await asyncio.to_thread(blob.exists)
            if exists:
                await asyncio.to_thread(blob.delete)
                logger.info(f"Deleted file from GCS: {file_path}")
                return True
            return False
        else:
            # Local filesystem branch
            full_path = f"{self._storage_root}/{file_path}"
            exists = await asyncio.to_thread(os.path.exists, full_path)
            if exists:
                await asyncio.to_thread(os.remove, full_path)
                logger.info(f"Deleted file locally: {full_path}")
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
        
        if self._is_cloud:
            # GCS branch
            def list_gcs_blobs():
                blob_list = []
                blobs = self._bucket.list_blobs(prefix=search_prefix)
                for blob in blobs:
                    blob_list.append({
                        'name': blob.name.replace(search_prefix + '/', ''),
                        'size': blob.size,
                        'modified': blob.updated.isoformat() if blob.updated else None
                    })
                return blob_list
            
            files = await asyncio.to_thread(list_gcs_blobs)
        else:
            # Local filesystem branch
            full_path = f"{self._storage_root}/{search_prefix}"
            
            def list_local_files():
                local_files = []
                if os.path.exists(full_path):
                    for item in os.listdir(full_path):
                        item_path = os.path.join(full_path, item)
                        if os.path.isfile(item_path):
                            stat = os.stat(item_path)
                            local_files.append({
                                'name': item,
                                'size': stat.st_size,
                                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
                            })
                return local_files
            
            files = await asyncio.to_thread(list_local_files)

        
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
        
        logger.info(f"Creating session {session_hash} for user {self._user_email} (hash: {self._user_hash}, cloud: {self._is_cloud})")

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
        
        logger.info(f"Session created successfully: {session_hash} at {self.get_session_path(session_hash)}")
        
        return session_hash
    
    async def validate_session(self, session_hash: str) -> bool:
        """Check if session exists and belongs to current user with retry for GCS eventual consistency"""
        import asyncio
        
        logger.debug(f"Starting session validation for {session_hash}, user {self._user_email} (hash: {self._user_hash})")
        
        # Retry logic for GCS eventual consistency
        max_retries = 5
        base_delay = 0.5  # Start with 500ms
        
        for attempt in range(max_retries):
            try:
                metadata_content = await self.get_file("metadata.json", session_hash)
                metadata = json.loads(metadata_content)
                stored_user_hash = metadata.get('user_hash')
                
                logger.debug(f"Session metadata found: {session_hash}, stored_user={stored_user_hash}, current_user={self._user_hash}, match={stored_user_hash == self._user_hash}")
                
                return stored_user_hash == self._user_hash
            except FileNotFoundError:
                if attempt < max_retries - 1:  # Don't wait on last attempt
                    delay = base_delay * (2 ** attempt)  # Exponential backoff
                    logger.debug(f"Session validation retry {attempt + 1}, waiting {delay}s for {session_hash}")
                    await asyncio.sleep(delay)
                    continue
                
                logger.debug(f"Session not found after {max_retries} retries: {session_hash}")
                return False

    
    async def delete_session(self, session_hash: str) -> bool:
        """Delete entire session directory"""
        if not await self.validate_session(session_hash):
            return False
        
        session_path = self.get_session_path(session_hash)
        
        if self._is_cloud:
            # GCS branch
            def delete_gcs_session():
                blobs = list(self._bucket.list_blobs(prefix=session_path))
                for blob in blobs:
                    blob.delete()
            
            await asyncio.to_thread(delete_gcs_session)
            logger.info(f"Deleted session from GCS: {session_path}")
        else:
            # Local filesystem branch
            full_path = f"{self._storage_root}/{session_path}"
            exists = await asyncio.to_thread(os.path.exists, full_path)
            if exists:
                await asyncio.to_thread(shutil.rmtree, full_path)
                logger.info(f"Deleted session locally: {full_path}")

        
        return True

    def force_cloud_mode(self):
        """Force the service to use cloud mode (used in Cloud Run environments)"""
        if not self._is_cloud:
            logger.info("Forcing cloud mode for storage service")
            self._is_cloud = True
            if not GCS_AVAILABLE:
                raise RuntimeError("Cannot force cloud mode - Google Cloud Storage not available")
            try:
                self._init_gcs()
            except Exception as e:
                logger.error(f"Failed to initialize GCS in forced cloud mode: {str(e)}")
                raise RuntimeError(f"GCS initialization failed: {str(e)}")
    

