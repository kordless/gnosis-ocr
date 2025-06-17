"""Storage service for managing sessions and files"""
import os
import json
import shutil
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
from uuid import uuid4
import aiofiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import structlog

from app.config import settings, get_storage_path, get_session_file_path
from app.models import ProcessingStatus

logger = structlog.get_logger()


class StorageService:
    """Manages file storage and session lifecycle"""
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self._ensure_storage_directory()
        
    def _ensure_storage_directory(self):
        """Ensure storage directory exists"""
        Path(settings.storage_path).mkdir(parents=True, exist_ok=True)
        
    async def start(self):
        """Start the storage service and cleanup scheduler"""
        # Schedule cleanup job
        self.scheduler.add_job(
            self.cleanup_old_sessions,
            'interval',
            seconds=settings.cleanup_interval,
            id='cleanup_sessions'
        )
        self.scheduler.start()
        logger.info("Storage service started", cleanup_interval=settings.cleanup_interval)
        
    async def stop(self):
        """Stop the storage service"""
        if self.scheduler.running:
            self.scheduler.shutdown()
        logger.info("Storage service stopped")
        
    def create_session(self) -> str:
        """Create a new session and return its hash"""
        session_hash = str(uuid4())
        session_path = get_storage_path(session_hash)
        
        # Create session directories
        for subdir in ['input', 'images', 'output']:
            Path(os.path.join(session_path, subdir)).mkdir(parents=True, exist_ok=True)
            
        # Initialize session metadata
        metadata = {
            'session_hash': session_hash,
            'created_at': datetime.utcnow().isoformat(),
            'status': ProcessingStatus.PENDING.value,
            'progress': 0.0,
            'total_pages': 0,
            'current_page': 0,
            'message': 'Session created'
        }
        
        # Save initial status
        self._save_status(session_hash, metadata)
        self.sessions[session_hash] = metadata
        
        logger.info("Session created", session_hash=session_hash)
        return session_hash
        
    async def save_uploaded_file(self, session_hash: str, filename: str, content: bytes) -> Dict[str, Any]:
        """Save uploaded file to session storage"""
        if not self.validate_session(session_hash):
            raise ValueError(f"Invalid session: {session_hash}")
            
        # Save file
        file_path = get_session_file_path(session_hash, filename, 'input')
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(content)
            
        # Update session metadata
        metadata = {
            'filename': filename,
            'file_size': len(content),
            'uploaded_at': datetime.utcnow().isoformat()
        }
        
        self.update_session_metadata(session_hash, metadata)
        logger.info("File saved", session_hash=session_hash, filename=filename, size=len(content))
        
        return {
            'file_path': file_path,
            'file_size': len(content)
        }
        
    def validate_session(self, session_hash: str) -> bool:
        """Check if session exists and is valid"""
        session_path = get_storage_path(session_hash)
        return os.path.exists(session_path)
        
    def get_session_status(self, session_hash: str) -> Optional[Dict[str, Any]]:
        """Get current session status"""
        if session_hash in self.sessions:
            return self.sessions[session_hash]
            
        status_file = get_session_file_path(session_hash, 'status.json')
        if os.path.exists(status_file):
            with open(status_file, 'r') as f:
                status = json.load(f)
                self.sessions[session_hash] = status
                return status
                
        return None
        
    def update_session_status(self, session_hash: str, status: ProcessingStatus, 
                            progress: float = None, message: str = None, 
                            current_page: int = None):
        """Update session processing status"""
        session_status = self.get_session_status(session_hash)
        if not session_status:
            return
            
        session_status['status'] = status.value
        if progress is not None:
            session_status['progress'] = progress
        if message is not None:
            session_status['message'] = message
        if current_page is not None:
            session_status['current_page'] = current_page
            
        if status == ProcessingStatus.PROCESSING and 'started_at' not in session_status:
            session_status['started_at'] = datetime.utcnow().isoformat()
        elif status in [ProcessingStatus.COMPLETED, ProcessingStatus.FAILED]:
            session_status['completed_at'] = datetime.utcnow().isoformat()
            if 'started_at' in session_status:
                started = datetime.fromisoformat(session_status['started_at'])
                completed = datetime.fromisoformat(session_status['completed_at'])
                session_status['processing_time'] = (completed - started).total_seconds()
                
        self._save_status(session_hash, session_status)
        self.sessions[session_hash] = session_status
        
    def update_session_metadata(self, session_hash: str, metadata: Dict[str, Any]):
        """Update session metadata"""
        session_status = self.get_session_status(session_hash)
        if session_status:
            session_status.update(metadata)
            self._save_status(session_hash, session_status)
            self.sessions[session_hash] = session_status
            
    def _save_status(self, session_hash: str, status: Dict[str, Any]):
        """Save status to file"""
        status_file = get_session_file_path(session_hash, 'status.json')
        with open(status_file, 'w') as f:
            json.dump(status, f, indent=2)
            
    async def save_page_image(self, session_hash: str, page_num: int, image_data: bytes) -> str:
        """Save extracted page image"""
        filename = f"page_{page_num:03d}.png"
        file_path = get_session_file_path(session_hash, filename, 'images')
        
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(image_data)
            
        return file_path
        
    async def save_page_result(self, session_hash: str, page_num: int, text: str) -> str:
        """Save OCR result for a page"""
        filename = f"page_{page_num:03d}.md"
        file_path = get_session_file_path(session_hash, filename, 'output')
        
        async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
            await f.write(text)
            
        return file_path
        
    async def save_combined_result(self, session_hash: str, combined_text: str) -> str:
        """Save combined OCR result"""
        file_path = get_session_file_path(session_hash, 'combined_output.md', 'output')
        
        async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
            await f.write(combined_text)
            
        return file_path
        
    async def get_page_image(self, session_hash: str, page_num: int) -> Optional[bytes]:
        """Get page image data"""
        filename = f"page_{page_num:03d}.png"
        file_path = get_session_file_path(session_hash, filename, 'images')
        
        if os.path.exists(file_path):
            async with aiofiles.open(file_path, 'rb') as f:
                return await f.read()
        return None
        
    async def get_results(self, session_hash: str) -> Dict[str, Any]:
        """Get all results for a session"""
        output_dir = get_session_file_path(session_hash, '', 'output')
        results = {
            'pages': [],
            'combined_markdown': None,
            'metadata': {}
        }
        
        # Read page results
        for file in sorted(Path(output_dir).glob('page_*.md')):
            page_num = int(file.stem.split('_')[1])
            async with aiofiles.open(file, 'r', encoding='utf-8') as f:
                text = await f.read()
                results['pages'].append({
                    'page_number': page_num,
                    'text': text,
                    'filename': file.name
                })
                
        # Read combined result
        combined_file = get_session_file_path(session_hash, 'combined_output.md', 'output')
        if os.path.exists(combined_file):
            async with aiofiles.open(combined_file, 'r', encoding='utf-8') as f:
                results['combined_markdown'] = await f.read()
                
        # Read metadata
        metadata_file = get_session_file_path(session_hash, 'metadata.json', 'output')
        if os.path.exists(metadata_file):
            with open(metadata_file, 'r') as f:
                results['metadata'] = json.load(f)
                
        return results
        
    def get_active_sessions(self) -> List[str]:
        """Get list of active session hashes"""
        active_sessions = []
        for session_dir in Path(settings.storage_path).iterdir():
            if session_dir.is_dir():
                status = self.get_session_status(session_dir.name)
                if status and status.get('status') in [ProcessingStatus.PENDING.value, 
                                                      ProcessingStatus.PROCESSING.value]:
                    active_sessions.append(session_dir.name)
        return active_sessions
        
    async def cleanup_old_sessions(self):
        """Remove sessions older than timeout"""
        try:
            cutoff_time = datetime.utcnow() - timedelta(seconds=settings.session_timeout)
            removed_count = 0
            
            for session_dir in Path(settings.storage_path).iterdir():
                if not session_dir.is_dir():
                    continue
                    
                session_hash = session_dir.name
                status = self.get_session_status(session_hash)
                
                if status:
                    created_at = datetime.fromisoformat(status.get('created_at', ''))
                    if created_at < cutoff_time:
                        shutil.rmtree(session_dir)
                        if session_hash in self.sessions:
                            del self.sessions[session_hash]
                        removed_count += 1
                        
            if removed_count > 0:
                logger.info("Cleaned up old sessions", count=removed_count)
                
        except Exception as e:
            logger.error("Error during session cleanup", error=str(e))
            
    def create_download_archive(self, session_hash: str) -> Optional[str]:
        """Create a ZIP archive of all session results"""
        session_path = get_storage_path(session_hash)
        archive_path = os.path.join(session_path, f"{session_hash}_results.zip")
        
        try:
            shutil.make_archive(
                archive_path.replace('.zip', ''),
                'zip',
                session_path
            )
            return archive_path
        except Exception as e:
            logger.error("Error creating archive", session_hash=session_hash, error=str(e))
            return None


# Global storage service instance
storage_service = StorageService()