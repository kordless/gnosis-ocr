"""Simple upload management for storage service"""
import json
from datetime import datetime
import hashlib
from typing import Optional, Dict, List
import logging
import asyncio # Import asyncio
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# A shared, in-memory dictionary to hold a lock for each active upload session.
# This ensures that all requests for the same session_id use the same lock.
_session_locks: Dict[str, asyncio.Lock] = {}

@asynccontextmanager
async def session_lock(session_id: str):
    """A context manager to safely acquire and release session locks."""
    if session_id not in _session_locks:
        _session_locks[session_id] = asyncio.Lock()
    
    lock = _session_locks[session_id]
    await lock.acquire()
    try:
        yield
    finally:
        lock.release()
        # Optional: Clean up the lock if the session is considered done.
        # For simplicity, we'll leave it. In a larger app, you might have a cleanup task.
class UploadManager:
    """Manages uploads using a client-led, stateless approach."""

    def __init__(self, storage_service, session_id: str):
        self.storage_service = storage_service
        self.session_id = session_id
        self.chunker_file = "chunks/chunker.json"

    async def start_chunked_upload(self, filename: str, total_size: int, total_chunks: int) -> Dict:
        """Creates the initial chunker.json file with upload metadata."""
        chunker_data = {
            "filename": filename,
            "total_size": total_size,
            "total_chunks": total_chunks,
            "status": "uploading",
            "created_at": datetime.utcnow().isoformat(),
        }
        await self.storage_service.save_file(
            json.dumps(chunker_data, indent=2), self.chunker_file, self.session_id
        )
        logger.info(f"Started chunked upload for {filename} in session {self.session_id}")
        return chunker_data

    async def add_chunk(self, chunk_number: int, chunk_data: bytes):
        """Stateless method to save a chunk."""
        chunk_filename = f"chunks/chunk_{chunk_number:03d}.bin"
        await self.storage_service.save_file(chunk_data, chunk_filename, self.session_id)
        logger.info(f"Saved chunk {chunk_number} for session {self.session_id}")

    async def assemble_file(self) -> Dict:
        """
        Checks for all chunks by scanning the directory. If complete, it
        assembles the file. If incomplete, it returns the list of missing chunks.
        """
        # 1. Get the upload metadata from the original chunker.json file
        chunker_data = await self.get_status()
        if not chunker_data:
            raise ValueError("Cannot assemble: session not found.")
        
        total_chunks_expected = chunker_data["total_chunks"]
        filename = chunker_data["filename"]

        # 2. Scan the storage directory for all actual chunk files
        chunk_files = await self.storage_service.list_files(prefix="chunks", session_hash=self.session_id)
        
        # 3. Determine which chunks were received from the filenames
        expected_chunks = set(range(total_chunks_expected))
        received_chunks = set()
        for f in chunk_files:
            if f['name'].startswith('chunk_') and f['name'].endswith('.bin'):
                try:
                    chunk_num = int(f['name'].split('_')[1].split('.')[0])
                    received_chunks.add(chunk_num)
                except (ValueError, IndexError):
                    logger.warning(f"Could not parse chunk number from filename: {f['name']}")
        
        # 4. If chunks are missing, return the list instead of raising an error
        missing_chunks = sorted(list(expected_chunks - received_chunks))
        if missing_chunks:
            logger.warning(f"Assembly check for session {self.session_id} failed. Missing chunks: {missing_chunks}")
            return {
                "status": "incomplete",
                "filename": filename,
                "total_chunks": total_chunks_expected,
                "received_chunks_count": len(received_chunks),
                "missing_chunks": missing_chunks
            }

        # 5. Perform the assembly if verification passes
        await self._perform_assembly(filename, total_chunks_expected)
        
        # 6. Update the status file and clean up
        chunker_data["status"] = "complete"
        chunker_data["completed_at"] = datetime.utcnow().isoformat()
        await self.storage_service.save_file(
            json.dumps(chunker_data, indent=2), self.chunker_file, self.session_id
        )
        await self._cleanup_session_files(total_chunks_expected)

        return chunker_data

    async def _perform_assembly(self, filename: str, total_chunks: int):
        """The core logic to assemble chunks into the final file."""
        logger.info(f"Starting assembly of {filename} from {total_chunks} chunks in session {self.session_id}")

        async def read_chunks():
            for i in range(total_chunks):
                chunk_filename = f"chunks/chunk_{i:03d}.bin"
                yield await self.storage_service.get_file(chunk_filename, self.session_id)

        await self.storage_service.save_file_stream(read_chunks(), filename, self.session_id)
        logger.info(f"Successfully saved assembled file: {filename}")
    
    async def _cleanup_session_files(self, total_chunks: int):
        """Deletes all temporary chunk files and the tracker file."""
        logger.info(f"Cleaning up session files for {self.session_id}")
        tasks = []
        for i in range(total_chunks):
            chunk_filename = f"chunks/chunk_{i:03d}.bin"
            tasks.append(self.storage_service.delete_file(chunk_filename, self.session_id))
        
        tasks.append(self.storage_service.delete_file(self.chunker_file, self.session_id))
        await asyncio.gather(*tasks, return_exceptions=True)

    async def get_status(self) -> Optional[Dict]:
        """Gets the raw, initial status from the chunker.json file."""
        try:
            chunker_json = await self.storage_service.get_file(self.chunker_file, self.session_id)
            return json.loads(chunker_json)
        except FileNotFoundError:
            return None

    async def get_status_with_derived_fields(self) -> Optional[Dict]:
        """Return upload status and compute missing chunk info."""
        chunker_data = await self.get_status()
        if not chunker_data:
            return None

        total_chunks = chunker_data.get("total_chunks", 0)

        chunk_files = await self.storage_service.list_files(prefix="chunks", session_hash=self.session_id)

        received_chunks = set()
        for f in chunk_files:
            if f["name"].startswith("chunk_") and f["name"].endswith(".bin"):
                try:
                    num = int(f["name"].split("_")[1].split(".")[0])
                    received_chunks.add(num)
                except (ValueError, IndexError):
                    logger.warning(f"Could not parse chunk number from filename: {f['name']}")

        missing_chunks = sorted(set(range(total_chunks)) - received_chunks)

        chunker_data["received_chunks_count"] = len(received_chunks)
        chunker_data["missing_chunks"] = missing_chunks

        return chunker_data

# These helper functions can remain as they are.
def get_user_email_from_request(request, x_user_email: Optional[str] = None) -> str:
    if x_user_email:
        return x_user_email
    return "anonymous@gnosis-ocr.local"

def get_user_hash_from_request(request, x_user_hash: Optional[str] = None) -> str:
    if x_user_hash:
        return x_user_hash
    user_email = get_user_email_from_request(request, None)
    return hashlib.sha256(user_email.encode()).hexdigest()[:12]