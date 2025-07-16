"""Chunked upload session management for persistent storage"""
import os
import json
import asyncio
from datetime import datetime
from typing import Optional, Tuple
import structlog
from fastapi import HTTPException

logger = structlog.get_logger()


class ChunkedUploadSession:
    """Persistent chunked upload session that survives container restarts"""
    
    def __init__(self, storage_service, upload_id: str):
        self.storage_service = storage_service
        self.upload_id = upload_id
        self.session_file = f"upload_sessions/{upload_id}.json"
    
    async def create(self, filename: str, total_size: int, total_chunks: int, user_email: str = None):
        """Create a new upload session"""
        session_data = {
            'upload_id': self.upload_id,
            'filename': filename,
            'total_size': total_size,
            'total_chunks': total_chunks,
            'chunks_received': 0,
            'chunks': {},  # chunk_number -> True (just track received)
            'created_at': datetime.utcnow().isoformat(),
            'user_email': user_email,
            'status': 'active'
        }
        await self._save_session(session_data)
        return session_data
    
    async def get_session(self):
        """Load session data from storage"""
        try:
            session_json = await self.storage_service.get_file(self.session_file, '_upload_sessions')
            session_data = json.loads(session_json)
            logger.debug(f"Loaded session {self.upload_id}: {session_data['chunks_received']}/{session_data['total_chunks']} chunks")
            return session_data
        except FileNotFoundError:
            logger.warning(f"Session file not found: {self.session_file}")
            return None
        except Exception as e:
            logger.error(f"Error loading session {self.upload_id}: {e}")
            return None
    
    async def add_chunk(self, chunk_number: int, chunk_data: bytes) -> Tuple[dict, bool]:
        """Add a chunk to the session"""
        logger.info(f"add_chunk called for upload {self.upload_id}, chunk {chunk_number}, size {len(chunk_data)} bytes")
        
        session_data = await self.get_session()
        if not session_data:
            logger.error(f"Session not found for upload {self.upload_id}")
            raise HTTPException(status_code=404, detail="Upload session not found")
        
        logger.info(f"Loaded session for {self.upload_id}: {session_data['chunks_received']}/{session_data['total_chunks']} chunks already received")
        
        # Check for duplicate chunks
        if str(chunk_number) in session_data['chunks']:
            logger.warning(f"Chunk {chunk_number} already exists in session {self.upload_id}")
            return session_data, True  # Already received
        
        try:
            # Save chunk data to storage with timeout
            chunk_file = f"upload_chunks/{self.upload_id}/chunk_{chunk_number:04d}.bin"
            logger.info(f"Saving chunk {chunk_number} to {chunk_file} ({len(chunk_data)} bytes)")
            
            try:
                await asyncio.wait_for(
                    self.storage_service.save_file(chunk_data, chunk_file, '_upload_sessions'),
                    timeout=30  # 30 second timeout
                )
                logger.info(f"Successfully saved chunk {chunk_number} to storage")
            except asyncio.TimeoutError:
                logger.error(f"Timeout saving chunk {chunk_number} to storage after 30 seconds")
                raise HTTPException(status_code=503, detail="Storage operation timed out")
            
            # Update session metadata
            session_data['chunks'][str(chunk_number)] = True
            session_data['chunks_received'] += 1
            session_data['updated_at'] = datetime.utcnow().isoformat()
            
            logger.info(f"Updated session metadata: {session_data['chunks_received']}/{session_data['total_chunks']} chunks")
            logger.info(f"Chunks in session: {sorted([int(k) for k in session_data['chunks'].keys()])}")
            
            await self._save_session(session_data)
            logger.info(f"Successfully saved session metadata for {self.upload_id}")
            
            # Verify the save by reading it back
            verify_session = await self.get_session()
            logger.info(f"Verification read: {verify_session['chunks_received']}/{verify_session['total_chunks']} chunks")
            logger.info(f"Verification chunks: {list(verify_session['chunks'].keys())}")
            
            return session_data, False  # Newly added
            
        except Exception as e:
            logger.error(f"Failed to save chunk {chunk_number} for upload {self.upload_id}: {e}")
            raise
    
    async def reassemble_file(self) -> Tuple[bytes, dict]:
        """Reassemble all chunks into complete file"""
        logger.info(f"reassemble_file: Getting session for {self.upload_id}")
        session_data = await self.get_session()
        if not session_data:
            raise HTTPException(status_code=404, detail="Upload session not found")
        
        logger.info(f"reassemble_file: Session loaded - {session_data['chunks_received']}/{session_data['total_chunks']} chunks")
        logger.info(f"reassemble_file: Session chunks: {list(session_data['chunks'].keys())}")
        
        if session_data['chunks_received'] != session_data['total_chunks']:
            missing_chunks = []
            for i in range(session_data['total_chunks']):
                if str(i) not in session_data['chunks']:
                    missing_chunks.append(i)
            if missing_chunks:
                logger.error(f"Missing chunks for upload {self.upload_id}: {missing_chunks}")
                logger.error(f"Session chunks received: {session_data['chunks_received']}/{session_data['total_chunks']}")
                logger.error(f"Chunks in storage: {list(session_data['chunks'].keys())}")
                raise HTTPException(status_code=400, detail=f"Missing chunks: {missing_chunks}")
        
        # Reassemble chunks in order
        complete_file_data = b''
        for i in range(session_data['total_chunks']):
            chunk_file = f"upload_chunks/{self.upload_id}/chunk_{i:04d}.bin"
            chunk_data = await self.storage_service.get_file(chunk_file, '_upload_sessions')
            complete_file_data += chunk_data
        
        return complete_file_data, session_data
    
    async def cleanup(self):
        """Clean up session and chunk files"""
        session_data = await self.get_session()
        if session_data:
            # Delete chunk files
            for i in range(session_data['total_chunks']):
                chunk_file = f"upload_chunks/{self.upload_id}/chunk_{i:04d}.bin"
                try:
                    await self.storage_service.delete_file(chunk_file, '_upload_sessions')
                except:
                    pass  # Ignore errors during cleanup
            
            # Delete session file
            try:
                await self.storage_service.delete_file(self.session_file, '_upload_sessions')
            except:
                pass
    
    async def _save_session(self, session_data: dict):
        """Save session data to storage"""
        session_json = json.dumps(session_data, indent=2)
        await self.storage_service.save_file(session_json, self.session_file, '_upload_sessions')